# Аудит chart-систем StormLab

Дата: 2026-11-26. Анализ read-only; код не менялся. Graphify-запросы `query "chart rendering"`, `affected "build_skewt_chart"` и `god-nodes` не выполнены: команда `graphify` недоступна в контейнере. Инвентаризация выполнена поиском по Python-исходникам.

## Инвентаризация

| Система | Вход → библиотека → результат | Вызывающий код и отправка |
| --- | --- | --- |
| Профильный график (`chart_builder.py:71-140`) | `pressure_data.hourly` → NumPy/MetPy `SkewT`/Matplotlib → PNG `BytesIO`; температура, точка росы, парсель/CAPE/CIN, barbs и адиабаты. Это профильный Skew-T без hodograph. | `bot.py:226-228`, `_send_storm_report`, Telegram `reply_photo`; REST `api.py:216-221`, `StreamingResponse(image/png)`. |
| Skew-T + hodograph (`skewt_builder.py:315-371`) | `current`, `hourly`, опционально sounding DataFrame/run time и report → MetPy/Matplotlib → PNG `BytesIO`. Model mode включает Skew-T, годограф и box индексов; sounding mode сравнивает модель и зонд. | `bot.py:260-272`, `_send_skewt`, Telegram `reply_photo`; station switch `bot.py:548-571`, `InputMediaPhoto`; REST `api.py:240-245`, `StreamingResponse(image/png)`. |
| Радар (`radar_builder.py:40-116`, `radar_api.py:35-84`) | Координаты, radar path, zoom/grid → HTTPX + PIL → PNG `BytesIO`: tile mosaic, crop и city marker. | `bot.py:281-297`, `_send_radar`, Telegram `reply_photo`; REST `api.py:250-270`, `StreamingResponse(image/png)`. |

Других production-систем рисования по маркерам Matplotlib, `savefig`, PIL/Image, canvas и tile в Python-файлах не найдено. Отдельный hodograph renderer отсутствует: hodograph является панелью `skewt_builder`.

## Пайплайн и эксплуатация

### Профильный график

- Данные идут из `OpenMeteoAPI.get_pressure_levels` (`openmeteo_api.py:193-215`); `_extract_profile_data` собирает термодинамику и ветер (`chart_builder.py:21-68`). Затем MetPy строит parcel и CAPE/CIN shading, если расчёт проходит, и barbs при наличии ≥2 уровней (`chart_builder.py:97-113`).
- Backend явно установлен как `Agg` до `pyplot` (`chart_builder.py:5-7`). Фигура `9×11 in`, PNG, `dpi=200`, `bbox_inches='tight'` (`chart_builder.py:84,132-134`). Live output: **1779×1089 px**, 3655 уникальных цветов, 301678 байт.
- `plt.close(fig)` выполняется после успешного `savefig` (`chart_builder.py:133-134`), но не в `finally`: исключение после создания фигуры оставит её открытой. На пустом термопрофиле (<2 уровней) возвращается `None` (`chart_builder.py:76-78`); прочая ошибка логируется, также возвращается `None` (`chart_builder.py:138-140`). Storm handler тогда пропускает фото, но отправляет текст отчёта (`bot.py:226-230`).
- Явных emoji в Matplotlib-тексте нет. Вызов в Telegram storm-handler синхронный внутри async-функции (`bot.py:226`); async REST route также вызывает renderer синхронно (`api.py:216`). Это блокирует event loop на время рендера. Scheduled `JobQueue` запускает только alert-check, не chart renderer (`bot.py:627-653,692-696`).
- Кэша готовых изображений нет. Open-Meteo кэширует данные: current 300 секунд, pressure levels 1800 секунд (`openmeteo_api.py:67-72`); это не кэш PNG.

### Skew-T и hodograph

- `_draw_skewt` строит температурный профиль, parcel/CAPE/CIN, LCL/LFC/EL и wind barbs; `_draw_hodograph` строит u/v годограф; `_draw_indices_box` добавляет surface/indices (`skewt_builder.py:40-151,153-203,205-245`). Для зонда используется дополнительный `_draw_sounding_skewt` (`skewt_builder.py:281-309`).
- `Agg` задан явно (`skewt_builder.py:3-6`). Model figure `14×9 in`, sounding figure `16×9 in`, PNG, `dpi=180`, tight bbox (`skewt_builder.py:330,342,369`). Live model output: **1665×1509 px**, 4403 уникальных цветов, 348201 байт. Sounding-вариант отдельно live не рендерился.
- При менее чем двух термодинамических уровнях `_draw_skewt` возвращает пустой результат и builder закрывает фигуру, возвращая `None` (`skewt_builder.py:67-68,350-353`). Исключение перехватывается и возвращается `None` (`skewt_builder.py:373-375`), но созданная фигура на общем exception path не гарантированно закрывается. Бот сообщает «Не удалось построить Skew-T» (`bot.py:264-267`).
- Glyph sources (все literal emoji в Matplotlib-контексте): `skewt_builder.py:78` 🌡️, `79` 💧, `85` 📦, `149` ⚡, `197` 🌪️, `215` 🌡️, `217` 💧, `219` 📊, `222` 💦, `225` 📈, `237` ⚡, `301` 📡. `chart_builder.py` literal emoji не содержит.
- На live model render stderr содержал **9 missing-glyph warnings** при `skewt_builder.py:369`: thermometer, droplet, package, cloud-with-tornado и chart-upwards-trend для DejaVu Sans; thermometer, droplet, bar-chart и splashing-sweat для DejaVu Sans Mono. В live PNG видны tofu-квадраты вместо нескольких emoji.
- В Telegram builder вызывается через `asyncio.to_thread` (`bot.py:260-261,548-550,566-568`), но Matplotlib/`pyplot` использует общие глобальные `rcParams` (`skewt_builder.py:317-324`); параллельные вызовы не сериализованы. Синхронный вызов также есть в async REST handler (`api.py:240`), который блокирует event loop. Image cache отсутствует.

### Радар

- `radar_api.get_latest_radar_frame` берёт последний допустимый path из RainViewer; метаданные path/time кэшируются на 300 секунд (`radar_api.py:28-45,48-73`). Builder вычисляет tile/pixel координаты (`radar_builder.py:24-38`), запрашивает 3×3 последовательными sync HTTPX GET (`radar_builder.py:53-84`), размещает PNG на canvas, crop 600×600 и marker (`radar_builder.py:48-51,86-112`). На MOSCOWе zoom 6: tile `(42,18)`, local pixel `(170,170)`, marker в crop `(300,300)`.
- Код использует `httpx.Client(timeout=15.0)`, а не `requests` (`radar_builder.py:55`); один client переиспользуется, запросы последовательные. Telegram запускает builder в worker thread (`bot.py:289`), но async REST route вызывает его синхронно (`api.py:262`). Девять запросов могут суммарно ждать до ~135 секунд при timeout на каждом; это задержка, но зависание Windows отдельно не воспроизводилось.
- Текущий URL в коде: `{base}{radar_path}/{zoom}/{x}/{y}.png` (`radar_builder.py:61`). На live path `/v2/radar/14b429d6636c`, zoom 6, tile `(42,18)` он ответил HTTP 200 изображением 256×256 с надписью “Zoom Level Not Supported”; production mosaic сохранена как `charts_audit_out/radar_mosaic.png`. Проверенный полный RainViewer URL содержит size/color/options: `/{path}/256/{z}/{x}/{y}/2/1_1.png`; все 9 таких текущих тайлов были прозрачными без radar echoes. Референс-мозаика сохранена отдельно.
- `_is_stub_tile` распознаёт только строго одноцветное видимое grayscale изображение 256/512 (`radar_builder.py:13-22`). Реальная заглушка содержит **11 цветов**, поэтому проверка её пропустила. Текущие unit-тесты покрывают белый/серый, прозрачный, прозрачный multicolor и multicolor, но не реальный RainViewer stub (`tests/test_radar_builder.py:8-39`).
- HTTP 404 только логируется на DEBUG и пропускается (`radar_builder.py:80-84`); если не загрузился ни один тайл, builder всё равно возвращает фон с marker. Прозрачный PNG не считается stub, но `canvas.paste(tile_img, ...)` без alpha mask копирует прозрачный alpha поверх canvas (`radar_builder.py:79`); текущие no-echo tiles поэтому не дают географической подложки. Кэшируется radar frame path, но не mosaic/image.

## Findings

| ID | Severity | File:line | Факт | Предложение |
| --- | --- | --- | --- | --- |
| C1 | High | `radar_builder.py:61` | Live URL вернул HTTP 200 stub “Zoom Level Not Supported”; в URL отсутствуют size/color/options. | Формировать полный поддерживаемый tile URL, передавать параметры RainViewer явно. |
| C2 | High | `radar_builder.py:13-22` | Detector ищет только один grayscale цвет; реальный stub имеет 11 цветов и попал в Telegram mosaic. | Детектировать stub-content/текстовый шаблон и добавить сохранённую fixture реального ответа в тесты. |
| C3 | Medium | `skewt_builder.py:78-301,369` | Зафиксированы 9 missing-glyph warnings, tofu-квадраты видны в live PNG. | Заменить emoji в plot text на поддерживаемые текстовые обозначения или glyph-capable font. |
| C4 | Medium | `bot.py:226`, `api.py:216,240,262` | Sync Matplotlib/PIL render вызывается напрямую из async handlers/routes и блокирует event loop. | Оффлоадить все render calls в worker threads/processes; REST учитывать те же ограничения. |
| C5 | Medium | `skewt_builder.py:317-324,330-370` | `pyplot` и `rcParams` общие, thread renders не сериализованы; исключение после создания фигуры может не закрыть её. | Сериализовать Matplotlib renders и гарантировать `plt.close(fig)` через `finally`. |
| C6 | Low | `radar_builder.py:55,80-84`; `api.py:262` | 9 последовательных HTTPX запросов с timeout 15 с; 404 пропускается и может дать пустую карту, а REST вызывает sync путь. | Ограничить общий бюджет времени, логировать число успешных тайлов и возвращать ошибку при нулевом покрытии. |
| C7 | Low | `chart_builder.py:133-134`, `skewt_builder.py:369-370` | Фигуры закрываются на happy path/некоторых early returns, но не гарантированно на всех исключениях. | Закрывать фигуру в `finally`. |

## Live renders

Профиль Open-Meteo для геокодированных координат MOSCOWа: `55.7558, 37.6173`; получение current + pressure profile заняло 0.164 с. Файлы PNG были декодированы Pillow; unique colors рассчитаны по RGBA pixels.

| Renderer / артефакт | Результат | Время | Glyph stderr / статус |
| --- | --- | ---: | --- |
| `chart_builder` — `charts_audit_out/profile_chart.png` | 1779×1089 px; 3655 colors; 301678 B | 0.931 с | 0 glyph warnings; реальный профиль отрисован. |
| `skewt_builder` model + hodograph — `charts_audit_out/skewt_hodograph.png` | 1665×1509 px; 4403 colors; 348201 B | 0.792 с | 9 missing-glyph warnings; tofu виден. Model-only ветка live; sounding branch не проверялась. |
| `radar_builder` production — `charts_audit_out/radar_mosaic.png` | 600×600 px; 13 colors; 12585 B; marker центр `(300,300)` | 0.269 с | Неуспешный live render: картинка содержит повторённый stub “Zoom Level Not Supported”; код не распознал. |
| RainViewer full-URL reference — `charts_audit_out/radar_mosaic_correct_url.png` | 600×600 px; 3 colors; 2496 B; 9/9 тайлов 256×256; marker `(300,300)` | 0.242 с | Stub tiles: 0/9; все тайлы прозрачны и без echoes, поэтому карта однотонная, но это не stub. |

Все созданные PNG меньше 0.35 MB, их стороны меньше 1800 px — в Telegram photo limits укладываются. `charts_audit_out/live-render-stderr.log` содержит API warnings, 9 glyph warnings и 9 строк `Tile size: (256, 256)`.

## Артефакты

- `charts_audit_out/profile_chart.png`
- `charts_audit_out/skewt_hodograph.png`
- `charts_audit_out/radar_mosaic.png` — stub от текущего production URL
- `charts_audit_out/radar_mosaic_correct_url.png` — корректный URL, текущие no-echo tiles
- `charts_audit_out/live-render-stderr.log`

На старте аудита рабочее дерево уже содержало `M radar_builder.py` и `?? tests/test_radar_builder.py`; эти изменения не редактировались и не откатывались. После добавления отчёта и артефактов состояние включает их плюс `CHARTS_AUDIT.md` и `charts_audit_out/`.