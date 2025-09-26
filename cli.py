from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from pallet_io.reader import ValidationError, read_inputs, read_settings
from pallet_io.writer import write_outputs
from logging_utils import configure_logging
from solver.cp_sat_solver import solve


SAMPLE_ORDER = [
    {"sku": "PEN60", "name": "Ручки гелевые (60/кор)", "qty_units": 120},
    {"sku": "SOAP24", "name": "Мыло жидкое (24/кор)", "qty_units": 75},
    {"sku": "TOW8", "name": "Полотенца кухонные (8/кор)", "qty_units": 40},
]

SAMPLE_CATALOG = [
    {
        "sku": "PEN60",
        "name": "Ручки гелевые (60/кор)",
        "length_mm": 400,
        "width_mm": 300,
        "height_mm": 200,
        "weight_kg": 6,
        "units_per_carton": 60,
        "rotations_allowed": True,
        "place_only_on_bottom": False,
        "carton_indivisible": True,
    },
    {
        "sku": "SOAP24",
        "name": "Мыло жидкое (24/кор)",
        "length_mm": 300,
        "width_mm": 300,
        "height_mm": 280,
        "weight_kg": 12,
        "units_per_carton": 24,
        "rotations_allowed": False,
        "place_only_on_bottom": True,
        "carton_indivisible": True,
    },
    {
        "sku": "TOW8",
        "name": "Полотенца кухонные (8/кор)",
        "length_mm": 500,
        "width_mm": 400,
        "height_mm": 250,
        "weight_kg": 5,
        "units_per_carton": 8,
        "rotations_allowed": True,
        "place_only_on_bottom": False,
        "carton_indivisible": True,
    },
]

SAMPLE_SETTINGS = {
    "pallet_base_length_mm": 1200,
    "pallet_base_width_mm": 800,
    "pallet_base_height_mm": 145,
    "max_total_height_mm": 1800,
    "max_weight_kg": 500,
    "overhang_mm": 20,
    "height_includes_base": True,
    "excel_encoding": "utf-8",
    "suggestions_mode": "all_fit_by_height",
    "solver": {
        "time_limit_sec": 120,
        "max_pallets_hint": None,
        "mip_gap": 0.0,
    },
    "logging": {"level": "INFO", "to_file": True},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Optimal palletization using OR-Tools CP-SAT")
    parser.add_argument("--order", type=Path, help="Path to order.xlsx")
    parser.add_argument("--catalog", type=Path, help="Path to catalog.xlsx")
    parser.add_argument("--settings", type=Path, help="Path to settings.yaml")
    parser.add_argument("--out", type=Path, required=True, help="Output directory")
    parser.add_argument(
        "--init-samples",
        type=Path,
        help="Create sample input files in the target directory and exit",
    )
    return parser.parse_args()


def create_sample_files(target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    order_df = pd.DataFrame(SAMPLE_ORDER)
    catalog_df = pd.DataFrame(SAMPLE_CATALOG)
    order_path = target_dir / "order.xlsx"
    catalog_path = target_dir / "catalog.xlsx"
    settings_path = target_dir / "settings.yaml"
    order_df.to_excel(order_path, sheet_name="order", index=False)
    catalog_df.to_excel(catalog_path, sheet_name="catalog", index=False)
    settings_path.write_text(_dump_yaml(SAMPLE_SETTINGS), encoding="utf-8")


def _dump_yaml(data: Any) -> str:
    import yaml

    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)


def main() -> None:
    args = parse_args()

    if args.init_samples:
        create_sample_files(args.init_samples)
        print(f"Sample files created in {args.init_samples}")
        return

    if not args.order or not args.catalog or not args.settings:
        raise SystemExit("--order, --catalog, and --settings arguments are required")

    settings = None
    try:
        settings = read_settings(args.settings)
    except FileNotFoundError as exc:
        print(str(exc))
        raise SystemExit(1)
    except ValidationError as exc:
        print(str(exc))
        raise SystemExit(1)

    configure_logging(settings, args.out)

    try:
        instance = read_inputs(args.order, args.catalog, args.settings, preloaded_settings=settings)
    except FileNotFoundError as exc:
        logging.error(str(exc))
        print(str(exc))
        raise SystemExit(1)
    except ValidationError as exc:
        logging.error(str(exc))
        print(str(exc))
        raise SystemExit(1)

    logging.info("Starting solver for %d boxes", len(instance.boxes))
    try:
        result = solve(instance)
    except Exception as exc:  # pragma: no cover
        logging.exception("Solver failed: %s", exc)
        raise SystemExit(1)

    logging.info("Solver status: %s", result.status)
    logging.info("Used pallets: %d", result.used_pallets)
    logging.info("Total height left: %d mm", result.height_left_total)

    write_outputs(instance, result, args.out)
    logging.info("Report generated at %s", args.out)


if __name__ == "__main__":
    main()
