import io
import logging
import math
import httpx
from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

TILE_BASE_URL = "https://tilecache.rainviewer.com"
TILE_SIZE = 256
COLOR = 2
OPTIONS = "1_1"
# Tile URL format: https://www.rainviewer.com/api/weather-maps-api.html#radar-maps-api


def _is_stub_tile(tile_img):
    if tile_img.size not in ((256, 256), (512, 512)):
        return False

    colors = tile_img.getcolors(maxcolors=tile_img.width * tile_img.height)
    if colors is None:
        return False

    total_pixels = tile_img.width * tile_img.height
    dominant_count, dominant_color = max(colors, key=lambda item: item[0])
    red, green, blue, _ = dominant_color
    alpha_is_opaque = tile_img.getchannel("A").getextrema() == (255, 255)
    if alpha_is_opaque:
        return red == green == blue and red >= 128 and dominant_count > total_pixels / 2

    visible_colors = [(count, color) for count, color in colors if color[3] > 0]
    visible_pixels = sum(count for count, _ in visible_colors)
    if not visible_pixels:
        return False

    grayscale_pixels = sum(
        count for count, (red, green, blue, _) in visible_colors
        if red == green == blue
    )
    return grayscale_pixels / visible_pixels >= 0.95

def _lat_lon_to_tile(lat, lon, zoom):
    """Переводит географические координаты в номер тайла и пиксель внутри него."""
    n = 2.0 ** zoom
    xtile = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)

    # Дробная часть для точного позиционирования внутри тайла (0.0 - 1.0)
    x_frac = ((lon + 180.0) / 360.0 * n) - xtile
    y_frac = ((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n) - ytile

    px_in_tile = int(x_frac * TILE_SIZE)
    py_in_tile = int(y_frac * TILE_SIZE)

    return xtile, ytile, px_in_tile, py_in_tile

def build_radar_image(lat, lon, radar_path, zoom=6, grid_size=3):
    """
    Скачивает сетку тайлов вокруг города, склеивает их,
    вырезает область и ставит маркер.
    """
    try:
        x_center, y_center, px_in_tile, py_in_tile = _lat_lon_to_tile(lat, lon, zoom)

        tile_size = TILE_SIZE
        canvas_size = tile_size * grid_size
        # Темный фон для красивой подложки
        canvas = Image.new("RGBA", (canvas_size, canvas_size), (20, 22, 28, 255))

        half_grid = grid_size // 2
        total_tiles = grid_size * grid_size
        loaded_tiles = 0
        has_echoes = False

        with httpx.Client(timeout=15.0) as client:
            for dy in range(grid_size):
                for dx in range(grid_size):
                    x = x_center - half_grid + dx
                    y = y_center - half_grid + dy

                    tile_url = (
                        f"{TILE_BASE_URL}{radar_path}/{tile_size}/{zoom}/{x}/{y}/"
                        f"{COLOR}/{OPTIONS}.png"
                    )

                    try:
                        resp = client.get(tile_url)
                        if resp.status_code == 200:
                            tile_img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
                            logger.info("Tile size: %s", tile_img.size)
                            if _is_stub_tile(tile_img):
                                logger.warning(
                                    "Tile %s is a stub (Zoom Level Not Supported)", tile_url
                                )
                                continue
                            if tile_img.size != (tile_size, tile_size):
                                logger.warning(
                                    "Unexpected tile size %s from %s; expected %s",
                                    tile_img.size, tile_url, (tile_size, tile_size),
                                )
                                continue
                            canvas.paste(tile_img, (dx * tile_size, dy * tile_size))
                            loaded_tiles += 1
                            if tile_img.getchannel("A").getbbox() is not None:
                                has_echoes = True
                        else:
                            logger.debug(f"Tile {tile_url} returned {resp.status_code}, skipping")
                    except Exception as e:
                        logger.debug(f"Tile download failed ({tile_url}): {e}")
                        continue  # Пропускаем битые или отсутствующие тайлы

        logger.info("Loaded %s/%s valid radar tiles", loaded_tiles, total_tiles)
        if loaded_tiles == 0:
            logger.warning("No valid radar tile coverage for %s", radar_path)
            return None

        # Город находится в центре канваса + смещение внутри центрального тайла
        center_x = (half_grid * tile_size) + px_in_tile
        center_y = (half_grid * tile_size) + py_in_tile

        # Вырезаем квадрат 600x600 вокруг города
        crop_size = 600
        half_crop = crop_size // 2
        left = max(0, center_x - half_crop)
        top = max(0, center_y - half_crop)
        right = min(canvas_size, center_x + half_crop)
        bottom = min(canvas_size, center_y + half_crop)

        final_img = canvas.crop((left, top, right, bottom))

        # Рисуем маркер ровно по центру вырезанного изображения
        draw = ImageDraw.Draw(final_img)
        draw_x = center_x - left
        draw_y = center_y - top

        # Белый круг с красной точкой внутри
        draw.ellipse([draw_x - 10, draw_y - 10, draw_x + 10, draw_y + 10], outline="white", width=3)
        draw.ellipse([draw_x - 4, draw_y - 4, draw_x + 4, draw_y + 4], fill="red")

        buf = io.BytesIO()
        final_img.save(buf, format="PNG", optimize=True)
        buf.seek(0)
        buf.no_echo = not has_echoes
        return buf

    except Exception as e:
        logger.error(f"Ошибка построения радара: {e}", exc_info=True)
        return None