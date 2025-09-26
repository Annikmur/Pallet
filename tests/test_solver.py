from __future__ import annotations

from typing import List

import pytest

from models.data_structures import BoxItem, CatalogItem, InstanceData, OrderLine, RuntimeSettings
from solver.cp_sat_solver import solve


def _build_order_line(sku: str, name: str, units_per_carton: int, boxes: int, qty_units: int | None = None) -> OrderLine:
    qty = qty_units if qty_units is not None else units_per_carton * boxes
    return OrderLine(
        sku=sku,
        name=name,
        qty_units_requested=qty,
        boxes_needed=boxes,
        units_per_carton=units_per_carton,
        units_effective=boxes * units_per_carton,
    )


def _build_catalog_item(
    sku: str,
    length: int,
    width: int,
    height: int,
    *,
    rotations_allowed: bool = True,
    place_only_on_bottom: bool = False,
    weight: float | None = None,
) -> CatalogItem:
    return CatalogItem(
        sku=sku,
        name=sku,
        length_mm=length,
        width_mm=width,
        height_mm=height,
        units_per_carton=1,
        rotations_allowed=rotations_allowed,
        place_only_on_bottom=place_only_on_bottom,
        carton_indivisible=True,
        weight_kg=weight,
    )


def _build_instance(settings: RuntimeSettings, catalog_items: List[CatalogItem], order_lines: List[OrderLine]) -> InstanceData:
    boxes: List[BoxItem] = []
    catalog = {item.sku: item for item in catalog_items}
    box_id = 0
    for line in order_lines:
        item = catalog[line.sku]
        for _ in range(line.boxes_needed):
            boxes.append(BoxItem(id=box_id, sku=line.sku, catalog_item=item, order_line=line))
            box_id += 1
    return InstanceData(catalog=catalog, order_lines=order_lines, boxes=boxes, settings=settings)


def test_non_overlap_enforced():
    settings = RuntimeSettings()
    settings.solver.time_limit_sec = 30
    catalog = [
        _build_catalog_item("A", 600, 600, 200),
        _build_catalog_item("B", 600, 600, 200),
    ]
    order_lines = [
        _build_order_line("A", "A", 1, 1),
        _build_order_line("B", "B", 1, 1),
    ]
    instance = _build_instance(settings, catalog, order_lines)
    result = solve(instance)
    placements = {p.box_id: p for p in result.placements}
    pos_a = placements[0].position
    pos_b = placements[1].position
    orientation_a = placements[0].orientation
    orientation_b = placements[1].orientation

    overlap_x = not (
        pos_a[0] + orientation_a.length_mm <= pos_b[0]
        or pos_b[0] + orientation_b.length_mm <= pos_a[0]
    )
    overlap_y = not (
        pos_a[1] + orientation_a.width_mm <= pos_b[1]
        or pos_b[1] + orientation_b.width_mm <= pos_a[1]
    )
    overlap_z = not (
        pos_a[2] + orientation_a.height_mm <= pos_b[2]
        or pos_b[2] + orientation_b.height_mm <= pos_a[2]
    )
    assert not (overlap_x and overlap_y and overlap_z)


def test_bottom_only_on_base_layer():
    settings = RuntimeSettings()
    settings.solver.time_limit_sec = 30
    catalog = [
        _build_catalog_item("BOTTOM", 400, 400, 300, place_only_on_bottom=True),
        _build_catalog_item("TOP", 300, 300, 200),
    ]
    order_lines = [
        _build_order_line("BOTTOM", "Bottom", 1, 1),
        _build_order_line("TOP", "Top", 1, 1),
    ]
    instance = _build_instance(settings, catalog, order_lines)
    result = solve(instance)
    for placement in result.placements:
        if placement.sku == "BOTTOM":
            assert placement.position[2] == 0


def test_orientation_minimizes_height_left():
    settings = RuntimeSettings(max_total_height_mm=1200)
    settings.solver.time_limit_sec = 30
    catalog_item = _build_catalog_item("BOX", 300, 200, 400)
    order_line = _build_order_line("BOX", "Box", 1, 1)
    instance = _build_instance(settings, [catalog_item], [order_line])
    result = solve(instance)
    assert len(result.placements) == 1
    placement = result.placements[0]
    # Orientation should choose the tallest dimension as height to minimize leftover
    assert placement.orientation.height_mm == 400
