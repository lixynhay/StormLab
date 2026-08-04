import io
import logging
import math
import httpx
from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

TILE_BASE_URL = "https://tilecache.rainviewer.com"

def _lat_lon_to_tile(lat, lon, zoom):
    """Переводит географические координаты в номер тайла и пиксель внутри него."""
    n = 2.0 ** zoom
    xtile = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)

    # Дробная часть для точного позиционирования внутри тайла (0.0 - 1.0)
    x_frac = ((lon + 180.0) / 360.0 * n) - xtile
    y_frac = ((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n) - ytile

    px_in_tile = int(x_frac * 512) # Умножаем на 512, т.к. берем тайлы 512x512
    py_in_tile = int(y_frac * 512)

    return xtile, ytile, px_in_tile, py_in_tile

def build_radar_image(lat, lon, radar_path, zoom=6, grid_size=3):
    """
    Скачивает сетку тайлов вокруг города, склеивает их,
    вырезает область и ставит маркер.
    """
    try:
        x_center, y_center, px_in_tile, py_in_tile = _lat_lon_to_tile(lat, lon, zoom)

        tile_size = 512
        canvas_size = tile_size * grid_size
        # Темный фон для красивой подложки
        canvas = Image.new("RGBA", (canvas_size, canvas_size), (20, 22, 28, 255))

        half_grid = grid_size // 2

        with httpx.Client(timeout=15.0) as client:
            for dy in range(grid_size):
                for dx in range(grid_size):
                    x = x_center - half_grid + dx
                    y = y_center - half_grid + dy

                    # Формируем URL тайла. Заменяем 256x256 на 512x512 для четкости
                    clean_path = radar_path.replace("256x256", "512x512")
                    tile_url = f"{TILE_BASE_URL}{clean_path}/{zoom}/{x}/{y}.png"

                    try:
                        resp = client.get(tile_url)
                        if resp.status_code == 200:
                            tile_img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
                            canvas.paste(tile_img, (dx * tile_size, dy * tile_size))
                        else:
                            logger.debug(f"Tile {tile_url} returned {resp.status_code}, skipping")
                    except Exception as e:
                        logger.debug(f"Tile download failed ({tile_url}): {e}")
                        continue  # Пропускаем битые или отсутствующие тайлы

        # Город находится в центре канваса + смещение внутри центрального тайла
        center_x = (canvas_size // 2) + px_in_tile
        center_y = (canvas_size // 2) + py_in_tile

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
        return buf

    except Exception as e:
        logger.error(f"Ошибка построения радара: {e}", exc_info=True)
        return None