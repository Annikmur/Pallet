from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from pallet_io.reader import ValidationError, enrich_order_with_catalog, read_inputs
from models.data_structures import CatalogItem, OrderLine, RuntimeSettings


def test_boxes_needed_rounding():
    catalog = {
        "SKU1": CatalogItem(
            sku="SKU1",
            name="Test",
            length_mm=100,
            width_mm=100,
            height_mm=100,
            units_per_carton=50,
            rotations_allowed=True,
            place_only_on_bottom=False,
            carton_indivisible=True,
        ),
    }
    order_line = OrderLine(
        sku="SKU1",
        name="Test",
        qty_units_requested=120,
        boxes_needed=0,
        units_per_carton=0,
        units_effective=0,
    )
    enrich_order_with_catalog([order_line], catalog)
    assert order_line.boxes_needed == 3
    assert order_line.units_effective == 150
    assert order_line.overdelivered_units == 30


def test_missing_dimensions_raises(tmp_path: Path):
    order_path = tmp_path / "order.xlsx"
    catalog_path = tmp_path / "catalog.xlsx"
    settings_path = tmp_path / "settings.yaml"

    pd.DataFrame([
        {"sku": "SKU1", "qty_units": 10},
    ]).to_excel(order_path, sheet_name="order", index=False)
    pd.DataFrame([
        {"sku": "OTHER", "length_mm": 100, "width_mm": 100, "height_mm": 100, "units_per_carton": 10,
         "rotations_allowed": True, "place_only_on_bottom": False, "carton_indivisible": True},
    ]).to_excel(catalog_path, sheet_name="catalog", index=False)

    settings = RuntimeSettings()
    with pytest.raises(ValidationError) as exc:
        read_inputs(order_path, catalog_path, settings_path, preloaded_settings=settings)
    assert str(exc.value) == "Нет габаритов: SKU1"
