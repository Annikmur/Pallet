from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import pandas as pd
import yaml

from models.data_structures import (
    BoxItem,
    CatalogItem,
    InstanceData,
    OrderLine,
    RuntimeSettings,
    SolverSettings,
    LoggingSettings,
)


class ValidationError(Exception):
    """Raised when input files fail validation."""


REQUIRED_ORDER_COLUMNS = {"sku", "qty_units"}
REQUIRED_CATALOG_COLUMNS = {
    "sku",
    "length_mm",
    "width_mm",
    "height_mm",
    "units_per_carton",
    "rotations_allowed",
    "place_only_on_bottom",
    "carton_indivisible",
}


def _read_excel(path: Path, sheet_name: str) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    return pd.read_excel(path, sheet_name=sheet_name, engine="openpyxl")


def _parse_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "t", "1", "yes", "y"}:
            return True
        if normalized in {"false", "f", "0", "no", "n"}:
            return False
    raise ValidationError(f"Invalid boolean value: {value}")


@dataclass
class RawInputs:
    order_df: pd.DataFrame
    catalog_df: pd.DataFrame
    settings: RuntimeSettings


def read_inputs(
    order_path: Path, catalog_path: Path, settings_path: Path, preloaded_settings: RuntimeSettings | None = None
) -> InstanceData:
    order_df = _read_excel(order_path, sheet_name="order")
    catalog_df = _read_excel(catalog_path, sheet_name="catalog")
    settings = preloaded_settings or read_settings(settings_path)

    order_lines = _parse_order(order_df)
    catalog = _parse_catalog(catalog_df)
    enrich_order_with_catalog(order_lines, catalog)

    boxes: List[BoxItem] = []
    for idx, order_line in enumerate(order_lines):
        sku = order_line.sku
        if sku not in catalog:
            raise ValidationError(f"Нет габаритов: {sku}")
        catalog_item = catalog[sku]
        for i in range(order_line.boxes_needed):
            box_id = len(boxes)
            boxes.append(BoxItem(id=box_id, sku=sku, catalog_item=catalog_item, order_line=order_line))

    return InstanceData(catalog=catalog, order_lines=order_lines, boxes=boxes, settings=settings)


def read_settings(settings_path: Path) -> RuntimeSettings:
    if not settings_path.exists():
        raise FileNotFoundError(f"File not found: {settings_path}")
    with settings_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if not isinstance(data, dict):
        raise ValidationError("Invalid settings format: expected mapping")

    solver_cfg = data.get("solver", {}) or {}
    logging_cfg = data.get("logging", {}) or {}

    solver = SolverSettings(
        time_limit_sec=solver_cfg.get("time_limit_sec", 120),
        max_pallets_hint=solver_cfg.get("max_pallets_hint"),
        mip_gap=float(solver_cfg.get("mip_gap", 0.0)),
    )

    logging_settings = LoggingSettings(
        level=str(logging_cfg.get("level", "INFO")).upper(),
        to_file=bool(logging_cfg.get("to_file", True)),
    )

    settings = RuntimeSettings(
        pallet_base_length_mm=int(data.get("pallet_base_length_mm", 1200)),
        pallet_base_width_mm=int(data.get("pallet_base_width_mm", 800)),
        pallet_base_height_mm=int(data.get("pallet_base_height_mm", 145)),
    max_total_height_mm=int(data.get("max_total_height_mm", 1800)),
    max_weight_kg=(float(data["max_weight_kg"]) if data.get("max_weight_kg") is not None else None),
        overhang_mm=int(data.get("overhang_mm", 20)),
        height_includes_base=bool(data.get("height_includes_base", True)),
        excel_encoding=str(data.get("excel_encoding", "utf-8")),
        suggestions_mode=str(data.get("suggestions_mode", "all_fit_by_height")),
        solver=solver,
        logging=logging_settings,
    )
    return settings


def _parse_order(order_df: pd.DataFrame) -> List[OrderLine]:
    missing = REQUIRED_ORDER_COLUMNS - set(order_df.columns.str.lower())
    if missing:
        raise ValidationError(f"Missing columns in order.xlsx: {sorted(missing)}")

    normalized_columns = {col.lower(): col for col in order_df.columns}

    results: List[OrderLine] = []
    for _, row in order_df.iterrows():
        sku = str(row[normalized_columns["sku"]]).strip()
        if not sku:
            raise ValidationError("Empty SKU in order.xlsx")
        name = None
        if "name" in normalized_columns:
            value = row[normalized_columns["name"]]
            name = None if pd.isna(value) else str(value)
        qty_units = row[normalized_columns["qty_units"]]
        if pd.isna(qty_units):
            raise ValidationError(f"Missing qty_units for SKU {sku}")
        qty_units_int = int(qty_units)
        if qty_units_int < 0:
            raise ValidationError(f"qty_units must be non-negative for SKU {sku}")

        order_line = OrderLine(
            sku=sku,
            name=name,
            qty_units_requested=qty_units_int,
            boxes_needed=0,  # placeholder
            units_per_carton=0,
            units_effective=0,
        )
        results.append(order_line)

    return results


def _parse_catalog(catalog_df: pd.DataFrame) -> Dict[str, CatalogItem]:
    missing = REQUIRED_CATALOG_COLUMNS - set(catalog_df.columns.str.lower())
    if missing:
        raise ValidationError(f"Missing columns in catalog.xlsx: {sorted(missing)}")

    normalized_columns = {col.lower(): col for col in catalog_df.columns}

    catalog: Dict[str, CatalogItem] = {}
    for _, row in catalog_df.iterrows():
        sku = str(row[normalized_columns["sku"]]).strip()
        if not sku:
            raise ValidationError("Empty SKU in catalog.xlsx")
        if sku in catalog:
            raise ValidationError(f"Duplicate SKU in catalog.xlsx: {sku}")

        length = _require_positive(row[normalized_columns["length_mm"]], f"length_mm for {sku}")
        width = _require_positive(row[normalized_columns["width_mm"]], f"width_mm for {sku}")
        height = _require_positive(row[normalized_columns["height_mm"]], f"height_mm for {sku}")
        units_per_carton = _require_int_ge(row[normalized_columns["units_per_carton"]], 1, f"units_per_carton for {sku}")
        rotations_allowed = _parse_bool(row[normalized_columns["rotations_allowed"]])
        place_only_on_bottom = _parse_bool(row[normalized_columns["place_only_on_bottom"]])
        carton_indivisible = _parse_bool(row[normalized_columns["carton_indivisible"]])

        name = None
        if "name" in normalized_columns:
            name_value = row[normalized_columns["name"]]
            name = None if pd.isna(name_value) else str(name_value)

        weight = None
        if "weight_kg" in normalized_columns:
            weight_value = row[normalized_columns["weight_kg"]]
            if not pd.isna(weight_value):
                weight = float(weight_value)
                if weight < 0:
                    raise ValidationError(f"weight_kg must be non-negative for {sku}")

        catalog[sku] = CatalogItem(
            sku=sku,
            name=name,
            length_mm=int(length),
            width_mm=int(width),
            height_mm=int(height),
            units_per_carton=int(units_per_carton),
            rotations_allowed=rotations_allowed,
            place_only_on_bottom=place_only_on_bottom,
            carton_indivisible=carton_indivisible,
            weight_kg=weight,
        )

    return catalog


def enrich_order_with_catalog(order_lines: List[OrderLine], catalog: Dict[str, CatalogItem]) -> None:
    for order_line in order_lines:
        sku = order_line.sku
        if sku not in catalog:
            raise ValidationError(f"Нет габаритов: {sku}")
        catalog_item = catalog[sku]
        units_per_carton = catalog_item.units_per_carton
        boxes_needed = math.ceil(order_line.qty_units_requested / units_per_carton) if units_per_carton else 0
        units_effective = boxes_needed * units_per_carton
        order_line.units_per_carton = units_per_carton
        order_line.boxes_needed = boxes_needed
        order_line.units_effective = units_effective


def _require_positive(value, label: str) -> int:
    if pd.isna(value):
        raise ValidationError(f"Missing {label}")
    numeric = float(value)
    if numeric <= 0:
        raise ValidationError(f"{label} must be positive")
    return int(round(numeric))


def _require_int_ge(value, minimum: int, label: str) -> int:
    if pd.isna(value):
        raise ValidationError(f"Missing {label}")
    intval = int(value)
    if intval < minimum:
        raise ValidationError(f"{label} must be >= {minimum}")
    return intval
