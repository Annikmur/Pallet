# Palletizer

Автономное консольное приложение для точной паллетизации заказов с использованием OR-Tools CP-SAT. Программа читает Excel-файлы заказов и каталога коробок, оптимизирует раскладку по паллетам с учётом всех ограничений и формирует Excel-отчёт.

## Возможности

- Поддержка поворотов коробок и ограничений по высоте/весу.
- Учёт запрета на размещение коробки выше нижнего слоя.
- Генерация детализированного отчёта `report.xlsx` и краткой сводки `summary.csv`.
- Режим рекомендаций «добивки» с расчётом дополнительных коробок по высоте.
- Создание примерных входных файлов командой `--init-samples`.
- Сбор логов в консоль и файл `run.log`.

## Установка зависимостей

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Запуск

```bash
python palletizer.py --order path/to/order.xlsx --catalog path/to/catalog.xlsx --settings path/to/settings.yaml --out out_dir
```

Дополнительные опции:

- `--init-samples <dir>` — создать примерные `order.xlsx`, `catalog.xlsx`, `settings.yaml` и завершить работу.

## Формат входных файлов

- **order.xlsx** — лист `order`, поля `sku`, `name` (опц.), `qty_units`.
- **catalog.xlsx** — лист `catalog`, поля `sku`, `length_mm`, `width_mm`, `height_mm`, `units_per_carton`, `rotations_allowed`, `place_only_on_bottom`, `carton_indivisible`, `weight_kg` (опц.).
- **settings.yaml** — параметры паллеты, ограничений, логирования и решателя (см. `data/examples/settings.yaml`).

## Отчёт

Файл `out/report.xlsx` содержит листы:

- `summary` — итоги по паллетам.
- `pallet_<id>` — детальная 3D-раскладка.
- `suggestions_<id>` — рекомендации по добивке.
- `rounding` — влияние округления штук в коробки.

Дополнительно создаётся `out/summary.csv`.

## Структура проекта

- `pallet_io/` — чтение/валидация данных и запись отчётов (переименовано из `io/`, чтобы не конфликтовать со стандартным модулем Python `io`).
- `models/` — основные датаклассы и вспомогательные структуры.
- `solver/` — постановка задачи CP-SAT и извлечение решения.
- `tests/` — модульные тесты на pytest.
- `data/examples/` — шаблон `settings.yaml`; Excel-файлы генерируются по требованию через `--init-samples`.
- `cli.py` / `palletizer.py` — точка входа и CLI.

## Сборка .exe (Windows)

После установки зависимостей выполните:

```bash
pyinstaller --onefile --name palletizer palletizer.py
```

При необходимости добавьте `--hidden-import` для `ortools` или `openpyxl`.

## Тесты

```bash
pytest
```

## Пример использования

```bash
python palletizer.py --init-samples data/examples
python palletizer.py --order data/examples/order.xlsx --catalog data/examples/catalog.xlsx --settings data/examples/settings.yaml --out out
```
