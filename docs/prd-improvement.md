# PRD улучшения — promo-margin-lab

> Тезис: лаборатория измеряет промо в рублях контрибуционной маржи. Отрицательный лифт маржи — это решение (потолок глубины по breakeven, финансировать только ячейки с положительной ожидаемой маржой), а не проваленный эксперимент.

| | |
|---|---|
| Owner | Никита Бояркин (аналитика) |
| Дата | 2026-10-25 |
| Область | `promo-margin-lab/`; гейт `scripts/check_claims.py` и сайт — внешние по отношению к члену |
| Видимость | public; кейс сайта `projects/promo.md` |
| Родительский PRD (планирование) | `/Users/nikitaboarkin/Desktop/00 ide/00 portfolio/reports/prd/promo-margin-lab.md` — цитируется как parent, не пересказывается |
| Источник чисел | `reports/*.json` на коммите `f4e6d9d`; старые значения (`+70.5m`, `−17.6m`, `95.3%`, MDE 612, ICC 0.138) не используются |

## 1. Что это и для кого

`promo-margin-lab` — продукт для категорийного менеджера и promo-аналитика офлайн-ритейла: где, на какую глубину и на каких SKU запускать промо при фиксированном trade spend. Пользователь приходит с вопросом «сколько заработает следующий промо-рубль», а не «какой был ROI акции». Лаборатория отвечает в рублях инкрементальной контрибуционной маржи, с контрфактуалом, декомпозицией каннибализации и потолком глубины по категории. Ключевая рамка: измерение даёт два знака одновременно — выручка растёт, маржа падает, — и второй знак и есть управленческий результат. Поэтому «не промоить на глубине 25.4%» — это решение с ценой, а не отсутствие результата. Продукт не для продакшн-сервинга и не для реальных данных Магнита: это воспроизводимый метод с известной правдой, который переносится на реальные данные без переноса чисел.

## 2. Вопрос, на который отвечает продукт

Сколько стоит промо в рублях маржи и при какой глубине следующий рубль trade spend перестаёт уничтожать маржу? На панели 120 магазинов × 60 SKU × 78 недель промо даёт **+68 495 020 ₽** инкрементальной выручки и **−24 397 020 ₽** инкрементальной контрибуционной маржи; **97.88%** из 9 053 волн убыточны, медиана волны **−2 050.6 ₽** (`reports/margin.json:59-64`, `reports/ledger.json:6-22`). При фактической средней глубине **25.43%** breakeven-потолок **1.0–19.5%** пробит во всех шести категориях — 6/6 (`reports/margin.json:2-56`, `reports/marts.json:2-9`). Вопрос продукта поэтому не «работает ли промо», а «какая глубина и какой набор ячеек дают положительную ожидаемую маржу при том же бюджете».

## 3. Что уже есть

| Слой | Артефакт | Доказательство |
|---|---|---|
| Панель и DGP | 561 600 ячеек, 37 016 промо-ячеек (6.59%), глубина 25.43%, hash `ae38964b1eb003e9` | `reports/w0_summary.json:3-20`; `src/dgp.py`; `tests/test_dgp.py:11` (тождество восьми компонент), `tests/test_reproducibility.py:13` |
| Контрфактуал | WAPE naive/forecast/matched: 24.49% / 7.64% / 20.33%; bias −19.90% / −3.74% / −14.02% | `reports/baseline.json:12-17,51-56,90-95`; `tests/test_baseline.py:23-38` |
| Ledger | own +932 049.8 юнитов, net +740 541.3 (−20.55% к own); pantry −199 865.4, cannibalization −176 886.7, halo +185 243.5 | `reports/ledger.json:9-22`; `src/ledger.py:66-86`; `tests/test_ledger.py:22-53` |
| P&L и breakeven | выручка +68 495 020 ₽, прибыль −24 397 020 ₽, скидка 59 976 927 ₽, funding +15 584 496 ₽; потолок 1.0–19.5% при 25.43% факта | `reports/margin.json:2-64`; `reports/ledger.json:67-71`; `tests/test_ledger.py:85-95` |
| Дизайн эксперимента и симуляция | ICC 0.2197 (net, 78 недель), MDE 786.1 ₽/store-week; FPR 4.3%, power 77.8%, coverage 95.3% | `reports/experiment_design.json:2-23`; `reports/simulation.json:2-22`; pre-registration — `docs/experiment-design.md` (не пересказывается) |
| Модель отклика и сравнение политик | R² 0.9252, MAE 89.7 ₽, Qini 0.9629; qini_rank −55 396 ₽, threshold +54 361 ₽ (285 ячеек), threshold − rank +109 758 ₽ | `reports/response.json:29-40,107-141,156-165`; `tests/test_response.py:16-44` |
| Аллокация | blanket 15%: −851 508 ₽ (−0.191 ₽/₽); tight: random +21 888, top-15% +136 648, optimised +231 496; loose: optimised +267 850 при расходе 841 068 | `reports/policy.json:12-17,19-55,56-103`; `src/allocation.py:111-170`; `tests/test_allocation.py:15-70` |
| SQL-марты и Superset | 4 марта, 9 053 волны; тест пинует прибыль к ledger в пределах 1 ₽; живой SQL Lab: `COUNT(*)=9053`, `SUM(net_profit)=−24 397 020.0` | `sql/marts/*.sql`; `reports/marts.json:2-9`; `tests/test_marts.py:44-49`; `superset/provision.py:65,197-205` |
| PySpark-паритет | 780 store-week строк, max abs diff 0.0, `BroadcastHashJoin` + `Window` | `reports/spark_parity.json:6,15`; `src/spark_job.py:149-153,200-210`; `tests/test_spark.py:23-43` |
| Тесты | 10 файлов; инварианты зерна, тождества, as-of, изоляции правды, W2–W8 | `tests/`; ключевые — `tests/test_ledger.py:22-53`, `tests/test_experiment.py:24-56`, `tests/test_allocation.py:15-70` |

## 4. Найденные дефекты правды, закрытые в цикле 2026-10-25

| Дефект | Доказательство | Что сделано | Механизм, который теперь не даёт вернуться |
|---|---|---|---|
| Pantry-атрибуция: drag бронировался на сдвинутую неделю, lag-2/3 терялись, знак бакета переворачивался | `git show f4e6d9d -- src/ledger.py`; `src/ledger.py:66-86`; прибыль до/после: `../reports/prd/promo-margin-lab.md:195` (−17.6m) vs `reports/margin.json:60` (−24.4m) | Исправлено в `f4e6d9d` (origin_week) | `tests/test_ledger.py:43` (post-promo бакет против answer key), `:53` (pnl bridge сходится к net), `:68` (committed report = fresh run) |
| Дрейф README: W5-блок держал 0.138 / 612 / 4.7% / 95.0% | было `git show HEAD:README.md:188-192`; сейчас `README.md:216-220` — 0.2197 / 786 / 4.3% / 95.3% | Закрыто в этом цикле правкой прозы — **диф проверить в README** | Пока нет: `check_claims` не покрывает ICC (REQ-1, REQ-6) |
| Дрейф `decision-memo`: breakeven-таблица 20.5 / 10.0 / 4.5 / 2.5 / 2.0 | было `git show HEAD:docs/decision-memo.md:15-18`; сейчас `docs/decision-memo.md:15-18` — 19.5 / 8.5 / 9.0 / 3.0 / 2.0 / 1.0 (`reports/margin.json:2-56`) | Закрыто в этом цикле правкой прозы — **диф проверить в decision-memo** | Нет: claims-гейт читает README и сайт, не docs |
| Битая ссылка на PRD | было `git show HEAD:README.md:365-366` → `reports/prd/promo-margin-lab.md`; файла нет ни в члене, ни в `NikitaBoyarkin/obsidian` (проверено `ls`) | Создан этот файл; README теперь ссылается на `docs/prd-improvement.md:405-406` — **диф проверить** | Ссылка резолвится в репозитории; проверка — `test -f` в CI |
| Противоречие статуса: «W0–W9 complete» и «W9 not started» одновременно | было `git show HEAD:README.md:8` vs `:360`; сейчас `README.md:8` и `:397` согласованы | Закрыто в этом цикле правкой прозы — **диф проверить в README** | Нет: prose review |
| MDE и % недельной выручки не из одной базы: 786 ₽ был подписан как 0.407% | было `README.md:217`; `docs/experiment-design.md:70` (0.367% для 786.1); `reports/ab_test_readiness.json:48` (0.407% для 871.7) | Частично закрыто: 0.367% и window ICC 0.3572 добавлены (`README.md:216-218`, `docs/decision-memo.md:48`) | Нет: выбор одной primary base остаётся REQ-1 |

## 5. Требования следующего цикла

### REQ-1 — Одна объявленная база ICC/MDE (P1, High, M)

**Находка.** Сосуществуют четыре ICC: 0.2197 net / 78 недель (`reports/experiment_design.json:13`), 0.3572 gross-base / окно (`reports/ab_test_readiness.json:33`), 0.4222 net-base / окно (`:26`), 0.2791 full panel (`:19`). MDE тоже расщеплён: 786.1 ₽ (`reports/experiment_design.json:20`, gross base по `ab_test_readiness.json:53`) и 871.7 ₽ (net base, `:45`). README берёт 786.1 и подписывает 0.407%, хотя 0.407% — это 871.7; для 786.1 арифметика даёт 0.367% (`docs/experiment-design.md:70`).
**Требование.** Объявить одну primary base для headline-пары ICC/MDE (рекомендация: net-base window, чтобы совпасть с pre-registered `net_units`, `docs/metric-definitions.md:18-23`; тогда headline MDE 871.7, а 786.1 уходит в sensitivity). Остальные три ICC публиковать как sensitivity с явной меткой базы и окна. `check_claims` должен падать на ICC без базы/окна.
**Приёмка.** В `reports/experiment_design.json` есть ровно один `primary_base`; README и сайт используют ту же пару; в `scripts/check_claims.py` есть строки по базам и negative-контроль на unqualified ICC.
**Проверка.** `uv run python run.py --stage experiment`; `../.eda-tools/.venv/bin/python scripts/check_claims.py`.
**Приоритет.** P1, High; выбор базы — гейт владельца.

### REQ-2 — Числа сайта пересобрать из канонических отчётов (P1, High, S; human gate)

**Находка.** Публичный кейс всё ещё держит прошлую генерацию: +70.5m / −17.6m / 95.3% / MDE 612 / ICC 0.138 / breakeven 2.0–20.5% (`../NikitaBoyarkin.github.io/src/content/projects/promo.md:3,8,14,86,90,116,118,126,134`), статический demo — те же числа (`../NikitaBoyarkin.github.io/public/demos/promo/index.html:49,61`), baseline фиксирует их как токены (`../NikitaBoyarkin.github.io/docs/content-baseline.json:2857-3019`). Гейт дрейфа существует, но не запускается в `make check`/CI (`../NikitaBoyarkin.github.io/docs/prd-improvement.md:25-26`).
**Требование.** После одобрения владельцем перегенерировать baseline сайта из `reports/margin.json`, `reports/ledger.json`, `reports/experiment_design.json` @ `f4e6d9d`; обновить RU+EN, demo и OG-описание; включить `audit:content` в проверку.
**Приёмка.** Пять headline-чисел страницы совпадают с отчётами; `bun test` и `bun run audit:content` зелёные; `content-baseline.json` пересобран одной командой.
**Проверка.** `cd NikitaBoyarkin.github.io && bun test && bun run audit:content`.
**Приоритет.** P1, High; публичные утверждения — только через человека.

### REQ-3 — Spark-тесты: skip без JDK должен быть настоящим (P2, Med, S)

**Находка.** Исходно README обещал «skips only when no JDK is available» (`git show HEAD:README.md:354-356`); сейчас README уже честно описывает gap (`README.md:386-393`). Код при этом не исправлен: `pytest.importorskip` проверяет только `pyspark` (`tests/test_spark.py:7`); fixture ловит `RuntimeError` от `ensure_java()` (`:14-17`, `src/spark_job.py:35-48`), но `test_session_can_restart` вызывает `session()` без этой защиты (`tests/test_spark.py:50-55`). Без JDK четыре теста skip, пятый падает. На этой машине Homebrew JDK найден, поэтому падение локально не воспроизведено — **не проверено**; вывод из кода.
**Требование.** Сделать skip module-level (проверка JDK до импорта/создания `SparkSession`) либо обернуть `test_session_can_restart`; README приводит фактическое поведение.
**Приёмка.** На машине без JDK `pytest tests/test_spark.py -q` — все skipped, exit 0; с JDK — все pass; удаление guard'а ломает тест (mutation control).
**Проверка.** `uv run pytest tests/test_spark.py -q` в обоих окружениях.
**Приоритет.** P2, Med.

### REQ-4 — `matplotlib` объявлен, но не импортируется (P3, Low, S)

**Находка.** `pyproject.toml:10` объявляет `matplotlib>=3.8`; ни один `.py` файл его не импортирует (`grep -rn "matplotlib" --include="*.py" .` → пусто). Рисунки проекта — HTML/SVG-рендеры, не matplotlib.
**Требование.** Удалить зависимость или обосновать её наличие в `pyproject.toml`/README. Если удаление меняет `uv.lock` — это гейт владельца (публичный lock).
**Приёмка.** `grep` пуст И зависимость удалена, либо в README есть строка, зачем она; `uv lock --check` проходит.
**Проверка.** `grep -rn "matplotlib" --include="*.py" .`; `uv lock --check`.
**Приоритет.** P3, Low.

### REQ-5 — Доказательные артефакты: regenerable и честно помечены (P2, Med, M)

**Находка.** Статический рендер дашборда существует и честно подписан (`reports/superset/dashboard.html`; `src/render.py:93` — `dashboard (static render)`; `README.md:193`). Скриншоты появились: `reports/superset/dashboard-live.png` (3200×2000) и `dashboard-static.png` (3200×3408), mtime 2026-10-25 18:08. Имя `dashboard-live.png` — растровая копия живого инстанса, но сам файл статичен; без манифеста это склоняет читателя к «интерактивно». Сайтовый demo — статический HTML с устаревшими числами (`../NikitaBoyarkin.github.io/public/demos/promo/index.html:49`). Дек в репозитории не найден — **не проверено**, возможно вне репо.
**Требование.** Каждый доказательный артефакт (deck, оба PNG, dashboard.html, demo) получает запись в манифесте: путь, тип `static|live`, команда перегенерации, исходный коммит. `dashboard-live.png` подписывается как «static screenshot of the live instance, <дата>», а не «interactive». Статический артефакт нигде не описывается как интерактивный; скриншоты перегенерируются из `dashboard.html`, а не рисуются руками.
**Приёмка.** Манифест покрывает все артефакты; `tests/test_marts.py:64` (self-contained render) остаётся зелёным; в README/кейсе нет слова «интерактивный» рядом со статикой.
**Проверка.** `uv run pytest tests/test_marts.py -q`; прогон команд из манифеста даёт те же файлы.
**Приоритет.** P2, Med.

### REQ-6 — `check_claims` пинует прошлую генерацию и сейчас красный (P0, High, S)

**Находка (Verified 2026-10-25).** Прогон `.eda-tools/.venv/bin/python scripts/check_claims.py` даёт `FAIL — 9 claim(s) drifted`, из них 7 promo: own lift 959 699 vs 932 049.8, net profit −17.584 vs −24.397 m, negative share 95.32% vs 97.88%, net lift 996 423 vs 740 541.3, forecast bias −0.88% vs −3.74%, MDE 611.7 vs 786.1, alloc tight 222 301 vs 231 496 (`scripts/check_claims.py:1925-1935` vs `reports/ledger.json:9-10`, `reports/margin.json:59-64`, `reports/policy.json:33-37`).
**Требование.** Обновить expected-значения до генерации `f4e6d9d`, добавить пропущенные claims (revenue, discount, breakeven range, ICC с базой), а значения брать из отчётов, не вписывать литералами. Гейт должен падать при мутации любого из чисел.
**Приёмка.** `check_claims` зелёный на текущих отчётах; мутация одного значения в `reports/*.json` даёт DRIFT; stale-литералов прошлой генерации нет.
**Проверка.** `../.eda-tools/.venv/bin/python scripts/check_claims.py`.
**Приоритет.** P0, High: красный truth-гейт хуже отсутствующего — он учит игнорировать FAIL.

### REQ-7 — Primary metric: net base или явная метка gross (P1, High, M)

**Находка.** Pre-registered метрика определена на `net_units` (`docs/metric-definitions.md:18-23`), а `store_week_profit` считает на `units_sold` (`src/experiment.py:43`). Искажение зафиксировано в двух местах с разным охватом: весь панель — 3.51 mn ₽ / 17.2% (`docs/metric-definitions.md:21`), окно эксперимента — 409 833.7 ₽ / 15.68% (`reports/ab_test_readiness.json:61-66`).
**Требование.** Либо перевести `store_week_profit` на `net_units` и перегенерировать `reports/simulation.json`/`ab_test_readiness.json`, либо объявить headline MDE и power gross-base, а net-base опубликовать рядом. В любом случае одно поле `metric_base` в отчётах и одна формулировка в README.
**Приёмка.** `metric_base` присутствует в отчётах; числа README и сайта подписаны той же базой; тест падает при расхождении базы.
**Проверка.** `uv run python run.py --stage experiment`; diff `reports/simulation.json`.
**Приоритет.** P1, High; связан с REQ-1 (одна база).

### REQ-8 — Живой дашборд Superset пуст: чарты не связаны и не строят запрос (P0, High, M)

**Находка (Verified 2026-10-25).** Скриншот живого инстанса `:8088` показал пустые слоты: «There is no chart definition associated with this component». Две причины, обе в коде. (1) `ensure_dashboard` пишет `position_json`, но не отправляет поле `charts` (`superset/provision.py:197-206`), поэтому связь `dashboard_slices` не создаётся и `/api/v1/dashboard/{id}/charts` возвращает пусто. (2) Четыре сохранённых чарта используют legacy time-series viz (`bar`/`line`), а `promo_waves.week` — INTEGER без `main_dttm_col`, поэтому Explore отвечает «Datetime column not provided»; `/api/v1/chart/{id}/data` дополнительно даёт 400 «Chart has no query context saved». Диагностический снимок — `/tmp/superset-shot/dashboard-live-broken.png` (вне репо).
**Требование.** Передавать `charts` при создании и обновлении дашборда; задать `main_dttm_col` либо перевести чарты на table-based viz; сохранять `query_context`; переpropagate и снять скриншот; README говорит о живом инстансе только то, что подтверждается API-вызовом.
**Приёмка.** `/api/v1/dashboard/{id}/charts` возвращает 4 чарта; PNG живого дашборда показывает бары, а не пустые слоты; SQL Lab-числа по-прежнему сходятся с `reports/margin.json`; `superset/export/superset-assets.zip` пересобран.
**Проверка.** `superset/bootstrap_local.sh` + `python superset/provision.py --db-uri ...`; затем API-запрос и Playwright-скриншот.
**Приоритет.** P0, High: до этой правки публичное утверждение «live instance is verified» было ложным на уровне чартов.

## 6. Не-цели

- Продакшн-сервинг модели, MLOps, онлайн-инференс — это роль ML-инженера, не этот продукт.
- Реальные данные Магнита, NDA-материалы, реконструкция их витрин.
- Заявления о throughput Spark: `local[4]` — один JVM, доказан только паритет и план.
- Победа в forecasting-бенчмарке: точность прогноза — инструмент, не продукт.
- Категорийные рекомендации шире глубины и выбора ячеек (ассортимент, полка, supply chain).

## 7. Гейты

| Что | Тип | Почему |
|---|---|---|
| `git push`, первый публичный коммит цикла | human | внешнее действие; без явного «да» владельца не выполняется |
| Числа сайта и `content-baseline.json` (REQ-2) | human | публичные утверждения о себе; baseline заморожен |
| Выбор primary base ICC/MDE (REQ-1) | human | дизайн-решение меняет headline-число и публичную формулировку |
| Удаление/перемещение файлов, удаление зависимости при изменении `uv.lock` (REQ-4) | human | публичный lock и история репозитория |
| Правка прозы README/docs, этот PRD | autonomous | не меняет числа и публичные утверждения |
| Перегенерация `reports/*.json`, тесты, новые тесты (REQ-3, REQ-7) | autonomous | воспроизводимо из `run.py`, проверяется pytest |
| Манифест артефактов и метки static (REQ-5) | autonomous | в репозитории, без внешних эффектов |
| Обновление `scripts/check_claims.py` до канонических значений (REQ-6) | human | правка самого гейта — human-gate по `LOOP.md`; без правки truth-гейт остаётся красным |
