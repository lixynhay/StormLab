# VERIFICATION — STP / SCP / effective-layer vs SPC (read-only)

Дата: 2026-11-26
Режим: **только чтение**. Код не изменялся; в репозиторий добавлен лишь этот файл.
Метод: чтение кода с номерами строк + fetch первичных страниц SPC (2026-11-26) + дословные цитаты из HTML.

## Источники (primary only)

| id | документ | URL | что берём |
|---|---|---|---|
| **S1** | SPC Mesoanalysis Help — «Supercell Composite Parameter» (текущая help-страница параметра) | <https://www.spc.noaa.gov/exper/mesoanalysis/help/help_scp.html> | SCP с CIN-членом `(-40/muCIN)` |
| **S2** | SPC — R. Thompson, «Explanation of SPC Severe Weather Parameters» | <https://www.spc.noaa.gov/exper/mesoanalysis/help/begin.html> | effective inflow layer, EBWD (50 % EL), STP effective, STP fixed, SCP (legacy, без CIN) |
| **S3** | SPC Mesoanalysis Help — «Effective Storm Relative Helicity» | <https://www.spc.noaa.gov/exper/mesoanalysis/help/help_esrh.html> | правило продолжения слоя: CAPE < 100 **или** CIN < −250 |

Блоги, форумы и сторонние реализации не использовались. Важно: `help_scp.html` содержит **только SCP**, а оба варианта STP — в `begin.html`; это учтено в колонке source.

## Контекст кода

- `report["stp"]` = `calculate_stp(...)` (`storm_indices.py:718-721`), UI — «STP (торнадо)» (`storm_indices.py:849`).
- `report["stp_eff"]` = `stp_effective(...)` (`storm_indices.py:785`), UI — «STP(eff)» (`:850`).
- `report["scp"]` = `calculate_scp(...)` (`storm_indices.py:724-727`), UI — «SCP (суперячейки)» (`:851`).
- `report["scp_eff"]` = `scp_effective(...)` (`storm_indices.py:786`), UI — «SCP(eff)» (`:852`).
- `report["srh"]` — SRH 0–3 км (`storm_indices.py:503`, `depth=depth_03` из `:479`).
- `report["cape"]` — MUCAPE, ML/SB только fallback (`storm_indices.py:652-663`).
- `report["bulk_shear_06"]` — 0–6 км (`storm_indices.py:481-484`).

---

## Таблица вердиктов

### A. Fixed-layer STP (`calculate_stp`, canonical = S2)

| # | parameter | code (file:line) | SPC canonical | verdict | source |
|---|---|---|---|---|---|
| 1 | слой SRH | `storm_indices.py:719` передаёт `report["srh"]`; `:503` — SRH с `depth_03` (0–3 км) | 0–1 км SRH (SRH1) | **CORRECTED** | S2 |
| 2 | база CAPE | `storm_indices.py:719` передаёт `report["cape"]`; `:652-656` — MUCAPE первым | sbCAPE (surface parcel) | **CORRECTED** | S2 |
| 3 | CIN-член | `storm_indices.py:192-195` — `clip((200-\|CIN\|)/150, 0, 1)`, входит в произведение | в формуле fixed-STP CIN-члена нет | **CORRECTED** | S2 |
| 4 | нижний клип 6BWD | `storm_indices.py:190` — `clip(6BWD/20, 0, 1.5)`; ниже 12.5 даёт > 0 | 6BWD < 12.5 м/с → 0.0 | **CORRECTED** | S2 |
| 5 | верхний cap 6BWD | `storm_indices.py:190` — cap 1.5 | 6BWD > 30 м/с → cap 1.5 | **CONFIRMED** | S2 |
| 6 | значение 6BWD | `storm_indices.py:481-484,720` — `bulk_shear(depth=6000 м)` | 0–6 км bulk wind difference | **CONFIRMED** | S2 |
| 7 | база LCL | `storm_indices.py:715` → `lcl_height_m`; `:350` — `lcl(p[0], …)` (SB) | sbLCL | **CONFIRMED** | S2 |
| 8 | LCL-член, нижняя граница | `storm_indices.py:187` — `clip((2000−LCL)/1000, 0, 1)` → 1.0 при LCL ≤ 1000 м | 1.0 при sbLCL < 1000 м AGL | **CONFIRMED** | S2 |
| 9 | cap CAPE и SRH | `storm_indices.py:182,189` — `min(1.0, CAPE/1500)` и `min(1.0, SRH/150)` | формула без cap; SPC явно оговаривает cap только для LCL и 6BWD | **CORRECTED** | S2 |

### B. Effective-layer STP (`stp_effective`, canonical = S2)

| # | parameter | code (file:line) | SPC canonical | verdict | source |
|---|---|---|---|---|---|
| 10 | база CAPE | `effective_layer.py:141` параметр `mucape`; `storm_indices.py:757-760,785` — `most_unstable_cape_cin` (MU) | mlCAPE (100 mb mean parcel) | **CORRECTED** | S2 |
| 11 | нижний клип EBWD | `effective_layer.py:21` (`EBWD_MIN=12.5`), `:144` → 0 | EBWD < 12.5 м/с → 0 | **CONFIRMED** | S2 |
| 12 | верхний cap EBWD | `effective_layer.py:22` (`EBWD_MAX=30`), `:168` → 30/20 = 1.5 | EBWD > 30 м/с → cap 1.5 | **CONFIRMED** | S2 |
| 13 | CIN-член | `effective_layer.py:160-166` — `clip((200+mlCIN)/150, 0, 1)`, 0 при < −200 | `(mlCIN+200)/150`; 1.0 при mlCIN > −50 | **CONFIRMED** | S2 |
| 14 | LCL-член | `effective_layer.py:149-156` — `clip((2000−mlLCL)/1000, 0, 1)` | 1.0 при mlLCL < 1000 м AGL | **CONFIRMED** | S2 |
| 15 | гейт inflow base | `effective_layer.py:141-175` — проверки `z_bot > 0` нет; вызов `storm_indices.py:777-787` при любом найденном слое | весь индекс = 0.0, если effective inflow base выше земли | **CORRECTED** | S2 |

### C. SCP (`calculate_scp` / `scp_effective`, canonical = S1; legacy = S2)

| # | parameter | code (file:line) | SPC canonical | verdict | source |
|---|---|---|---|---|---|
| 16 | нормировка ESRH | `storm_indices.py:207` — `srh / 100.0` | `ESRH / 50` | **CORRECTED** | S1, S2 |
| 17 | нижний клип EBWD | `effective_layer.py:181` + `:21` — 12.5 м/с | EBWD < 10 м/с → 0 | **CORRECTED** | S1 |
| 18 | верхний cap EBWD | `effective_layer.py:186` + `:22` — `min(EBWD,30)/20` = до 1.5 | EBWD > 20 м/с → 1.0 | **CORRECTED** | S1 |
| 19 | наличие CIN-члена в effective-SCP | `effective_layer.py:178-191` — сигнатура `scp_effective(mucape, esrh, ebwd)`, CIN отсутствует | S1: `* (-40/muCIN)`; S2 (legacy): без CIN | **AMBIGUOUS** | S1 vs S2 |
| 20 | формула CIN в `calculate_scp` | `storm_indices.py:211` — `clip((200−\|CIN\|)/150, 0, 1)` | `(-40 / muCIN)`, 1.0 при muCIN > −40 | **CORRECTED** | S1 |
| 21 | сдвиг в `calculate_scp` | `storm_indices.py:208` — 0–6 км shear (`report["bulk_shear_06"]`) | EBWD (effective bulk wind difference) | **CORRECTED** | S1 |
| 22 | fixed-layer SCP как канон | `storm_indices.py:199-215` — отдельная fixed-версия | S1/S2 определяют SCP только через effective-ингедиенты; fixed-SCP отсутствует | **AMBIGUOUS** | S1, S2 |

### D. Effective inflow layer и EBWD (canonical = S2 + S3)

| # | parameter | code (file:line) | SPC canonical | verdict | source |
|---|---|---|---|---|---|
| 23 | гейт CIN ≥ −250 | `effective_layer.py:74` — проверяются только `CAPE ≥ 100` и `z_top−z_bot ≥ 50` | CAPE ≥ 100 **И** CIN ≥ −250 | **CORRECTED** | S2, S3 |
| 24 | верх слоя | `effective_layer.py:66-75` — `z_top` = EL (`mpcalc.el`) | вверх, пока CAPE < 100 **или** CIN < −250 | **CORRECTED** | S2, S3 |
| 25 | верх для ESRH | `effective_layer.py:89` — `top = min(z_top, 10000)`, `z_top` = EL; вызов `:783` | верх effective inflow layer | **CORRECTED** | S2, S3 |
| 26 | верх EBWD | `effective_layer.py:121` — `min(z_top, 10000)`, `z_top` = полный EL | 50 % высоты EL MU-парцеля | **CORRECTED** | S2 |
| 27 | база EBWD | `effective_layer.py:136` — `wind_at(z_bot)` | effective inflow base | **CONFIRMED** | S2 |

**Итог: 16 × CORRECTED, 9 × CONFIRMED, 2 × AMBIGUOUS (27 строк).**

---

## Канон SPC — дословно

### S2: fixed-layer STP

> STP = (sbCAPE / 1500 J kg⁻¹) * ((2000 − sbLCL) / 1000 m) * (0-1 km SRH / 150 m² s⁻²) * (6BWD / 20 m s⁻¹)
>
> where the sbLCL term is set to 1.0 for sbLCL heights < 1000 m AGL; the 6BWD term is capped at 1.5 for 6BWD > 30 m s⁻¹, and set to 0.0 for 6BWD < 12.5 m s⁻¹.

В списке ингредиентов перед формулой упомянут `surface parcel CIN (sbCIN)`, но **в формуле CIN-члена нет** — см. caveat 1.

### S2: effective-layer STP

> STP = (mlCAPE / 1500 J kg⁻¹) * ((2000 − mlLCL) / 1000 m) * (ESRH / 150 m² s⁻²) * (EBWD / 20 m s⁻¹) * ((mlCIN + 200) / 150 J kg⁻¹)
>
> where the mlLCL term is set to 1.0 for mlLCL heights < 1000 m AGL; the EBWD term is capped at 1.5 for EBWD > 30 m s⁻¹, and set to 0.0 for EBWD < 12.5 m s⁻¹; the mlCIN term is set to 1.0 for mlCIN > -50 J kg⁻¹; the entire index is set to 0.0 when the effective inflow base is above the ground.

### S1: SCP (текущая страница)

> SCP = (muCAPE / 1000 J kg⁻¹) * (ESRH / 50 m² s⁻²) * (EBWD / 20 m s⁻¹) * (-40 J kg⁻¹ / muCIN)
>
> EBWD is divided by 20 m s⁻¹ in the range of 10-20 m s⁻¹. EBWD less than 10 m s⁻¹ is set to zero, and EBWD greater than 20 m s⁻¹ is set to one. The muCIN term is based on work by Gropp and Davenport (2018), and it is set to 1.0 when muCIN is greater than -40 kg⁻¹.

### S2: SCP (та же страница Thompson, legacy-блок)

> SCP = (muCAPE / 1000 J kg⁻¹) * (ESRH / 50 m² s⁻²) * (EBWD / 20 m s⁻¹)
>
> EBWD is divided by 20 m s⁻¹ in the range of 10-20 m s⁻¹. EBWD less than 10 m s⁻¹ is set to zero, and EBWD greater than 20 m s⁻¹ is set to one.

CIN-члена нет — источник расхождения для вердикта #19.

### S2: effective inflow layer

> Effective Inflow Layer = the first layer in a sounding where all contiguous lifted parcels have CAPE >= 100 J kg⁻¹ and CIN >= -250 J kg⁻¹.

### S3: продолжение слоя вверх

> … we continue to look upward in the sounding until a lifted parcel has a CAPE less than 100 J kg⁻¹ OR a CIN less than -250 J kg⁻¹.

### S2: EBWD

> Effective Bulk Wind Difference = magnitude of the bulk vector shear from the "effective inflow base" upward to 50% of the equilibrium level height with the most unstable parcel in the lowest 300 mb.

---

## Source caveats

1. **fixed-STP: текст vs формула (S2).** В перечислении ингредиентов есть `sbCIN`, в формуле — нет. Вердикт #3 выставлен по формуле. Если считать каноном вводный текст, #3 становится **AMBIGUOUS**.
2. **SCP: два первичных документа расходятся.** S1 (текущая help-страница параметра) включает `(-40/muCIN)`; S2 (документ Thompson) — нет. Отсюда **AMBIGUOUS** для #19. Если каноном считать S1 (страница, обслуживающая отображаемый параметр), #19 → **CORRECTED** (CIN-члена в коде нет).
3. **Fixed-SCP не существует в SPC.** S1/S2 определяют SCP только через effective-ингедиенты → #22 **AMBIGUOUS**, а не «неверно».
4. **`calculate_scp` — не SCP вообще.** Помимо CIN-формулы, он берёт 0–6 км shear вместо EBWD (#21) и нормирует ESRH на 100 вместо 50 (#16). Даже при исправлении констант это другая величина.
5. **Нижние clamp'ы, не оговорённые SPC.** Поведение при LCL > 2000 м и mlCIN < −200 в источниках не описано; код клипует в 0. Это не выделено в отдельные вердикты, чтобы не выдумывать канон.
6. **`find_effective_layer` считает не то, что описано.** `effective_layer.py:67` берёт `mixed_layer_cape_cin` для подложки `p_sub` (от текущего уровня вверх), а не CAPE индивидуальных поднятых парцелл, и не проверяет CIN. Поэтому даже «CAPE ≥ 100» в `:74` — это mlCAPE слоя, а не CAPE парцеллы.

---

## Практические выводы (без правок кода)

- **fixed-STP** (`calculate_stp`) — гибрид: sbLCL и 6BWD совпадают с S2, но MUCAPE вместо sbCAPE, SRH 0–3 км вместо 0–1 км, лишний CIN-член, нет нуля при 6BWD < 12.5. Как «fixed STP по SPC» не валиден.
- **effective-STP** (`stp_effective`) — ближе всего к канону: LCL/EBWD/CIN-клипы совпадают (S2), но CAPE — MU вместо ML и нет обнуления при inflow base выше земли.
- **SCP(eff)** (`scp_effective`) — завышен: нижний порог 12.5 вместо 10, cap 1.5 вместо 1.0, CIN-член отсутствует.
- **`calculate_scp`** — нормировка ESRH /100, 0–6 км shear вместо EBWD, CIN-формула `(200−|CIN|)/150`. Это не SCP ни по одной из версий SPC.
- **Effective inflow layer** реализован как base→EL без CIN-гейта; верх слоя, ESRH и EBWD не соответствуют S2/S3. Это искажает `esrh`, `ebwd`, а значит `stp_eff` и `scp_eff`.

---

## Состояние репозитория

`git status --short` на момент проверки:

```text
 D .env.example
 M radar_api.py
 M requirements.txt
?? .opencode/
?? AGENTS.md
?? AUDIT.md
?? VERIFICATION.md
?? bot.log
?? graphify-out/
?? tests/test_radar_api.py
```

`D .env.example`, `M radar_api.py`, `M requirements.txt`, `tests/test_radar_api.py`, `AUDIT.md` — pre-existing состояние после предыдущих задач. В рамках этой read-only проверки добавлен только `VERIFICATION.md`; `storm_indices.py`, `effective_layer.py` и остальной код не изменялись.

---

## Обновление (Batch 3A/3B, текущий снапшот)

- `escape_markdown()` (`core/text_safety.py`) применяется **только к динамике**: `md(city)` в `bot.py`, поля LLM/Alert. Захардкоженные лейблы (`"🌩 STP: "`, `"📡 Радар осадков:"`) не эскейпятся. `grep -rn "escape_markdown" --include="*.py"` — `core/text_safety.py`, `bot.py` (через `md()`).
- `Defaults(parse_mode=MarkdownV2)` в `bot.py` **нет**; AI-ответ (`analysis`) отправляется отдельным сообщением **без `parse_mode`**, после `redact_secrets(analysis)`. Заголовок `/ai` — fixed Markdown с `md(city)`.
- OWM-ошибки логируются только через `redact_secrets(e)` (`clients/openweathermap_api.py`, `bot.py`, `api.py`); URL с `appid=` в логи не попадает.
- `concurrent_updates=False` (`bot.py`, `Application.builder()`) — намеренно, до завершения lock-дизайна 3B.
- `sqlite3.connect(DB_PATH)` вызывается только внутри `_connect()` в `alert_manager.py`; `prune_history()` запускается в `alerts_background_task`.
- `SPC-аудит 3A`: вышеприведённые строки про «SCP(eff) завышен / inflow layer неверен» относились к более раннему снапшоту; текущий код (`EFFECTIVE_CONSTANTS`, `find_effective_layer`, `stp_effective`, `scp_effective`) приведён к SPC mesoanalysis и покрыт pin-тестами. Конфликт двух живых SPC-страниц (SCP cap 1.0/>20 vs 1.5/>30; STP EBWD min 12.5 vs 12) задокументирован в отчёте батча.
