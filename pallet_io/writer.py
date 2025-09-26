from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Sequence

import pandas as pd

from models.data_structures import (
    InstanceData,
    OrderLine,
    PalletMetrics,
    PalletPlacement,
    PalletSuggestion,
    SolverResult,
)
from models.orientation import generate_orientations


def write_outputs(instance: InstanceData, result: SolverResult, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    sorted_metrics = sorted(result.pallet_metrics, key=lambda m: m.pallet_index)
    pallet_id_map = {metrics.pallet_index: idx + 1 for idx, metrics in enumerate(sorted_metrics)}

    summary_records = _build_summary_records(instance, sorted_metrics, pallet_id_map)
    summary_df = pd.DataFrame(summary_records)
    summary_path = output_dir / "summary.csv"
    summary_df.to_csv(summary_path, index=False, encoding=instance.settings.excel_encoding)

    report_path = output_dir / "report.xlsx"
    with pd.ExcelWriter(report_path, engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="summary", index=False)
        rounding_df = _build_rounding_df(instance.order_lines)
        rounding_df.to_excel(writer, sheet_name="rounding", index=False)

        placements_by_pallet = _group_placements_by_pallet(result.placements)

        for pallet_index in sorted(placements_by_pallet):
            placements = placements_by_pallet[pallet_index]
            pallet_sheet_name = f"pallet_{pallet_id_map[pallet_index]}"
            pallet_df = _build_pallet_sheet(placements)
            pallet_df.to_excel(writer, sheet_name=pallet_sheet_name, index=False)

        suggestions_by_pallet = _build_suggestions(instance, result, pallet_id_map)
        for pallet_index in sorted(suggestions_by_pallet):
            suggestions = suggestions_by_pallet[pallet_index]
            if not suggestions:
                continue
            sheet_name = f"suggestions_{pallet_index}"
            suggestions_df = pd.DataFrame([
                {
                    "sku": s.sku,
                    "name": s.name,
                    "max_extra_boxes_by_height": s.max_extra_boxes_by_height,
                    "added_height_mm": s.added_height_mm,
                    "new_height_left_mm": s.new_height_left_mm,
                }
                for s in suggestions
            ])
            suggestions_df.to_excel(writer, sheet_name=sheet_name, index=False)


def _build_summary_records(
    instance: InstanceData, metrics_list: Sequence[PalletMetrics], pallet_id_map: Dict[int, int]
) -> List[Dict[str, object]]:
    records: List[Dict[str, object]] = []
    settings = instance.settings
    for metrics in metrics_list:
        pallet_id = pallet_id_map[metrics.pallet_index]
        if settings.height_includes_base:
            height_limit = settings.max_total_height_mm
            height_used = metrics.height_used_mm
        else:
            height_limit = settings.max_total_height_mm
            height_used = metrics.height_used_mm - settings.pallet_base_height_mm
        height_used = max(0, height_used)
        fill_percent = 0.0
        if height_limit > 0:
            fill_percent = round(100.0 * height_used / height_limit, 2)
        record = {
            "pallet_id": pallet_id,
            "height_used_mm": metrics.height_used_mm,
            "height_left_mm": metrics.height_left_mm,
            "weight_kg": metrics.weight_kg,
            "boxes_count": metrics.boxes_count,
            "skus_count": metrics.skus_count,
            "percent_height_fill": fill_percent,
        }
        records.append(record)
    return records


def _build_rounding_df(order_lines: Sequence[OrderLine]) -> pd.DataFrame:
    data = []
    for line in order_lines:
        data.append(
            {
                "sku": line.sku,
                "qty_units_requested": line.qty_units_requested,
                "units_per_carton": line.units_per_carton,
                "boxes_used": line.boxes_needed,
                "units_effective": line.units_effective,
                "overdelivered_units": line.overdelivered_units,
            }
        )
    return pd.DataFrame(data)


def _group_placements_by_pallet(placements: Sequence[PalletPlacement]) -> Dict[int, List[PalletPlacement]]:
    grouped: Dict[int, List[PalletPlacement]] = defaultdict(list)
    for placement in placements:
        grouped[placement.pallet_index].append(placement)
    return grouped


def _build_pallet_sheet(placements: Sequence[PalletPlacement]) -> pd.DataFrame:
    sorted_placements = sorted(placements, key=lambda p: (p.position[2], p.position[1], p.position[0]))
    z_levels = sorted({p.position[2] for p in sorted_placements})
    layer_index_map = {z: idx for idx, z in enumerate(z_levels)}

    rows = []
    for placement in sorted_placements:
        layer_idx = layer_index_map[placement.position[2]]
        rows.append(
            {
                "sku": placement.sku,
                "name": placement.name,
                "boxes_on_pallet": 1,
                "units_on_pallet": placement.units_on_pallet,
                "layer_index_or_z": layer_idx,
                "orientation(L×W×H)": f"{placement.orientation.length_mm}×{placement.orientation.width_mm}×{placement.orientation.height_mm}",
                "box_dims_mm": placement.orientation.as_tuple(),
                "pos_x_mm": placement.position[0],
                "pos_y_mm": placement.position[1],
                "pos_z_mm": placement.position[2],
            }
        )
    return pd.DataFrame(rows)


def _build_suggestions(
    instance: InstanceData, result: SolverResult, pallet_id_map: Dict[int, int]
) -> Dict[int, List[PalletSuggestion]]:
    settings = instance.settings
    suggestions_by_pallet: Dict[int, List[PalletSuggestion]] = {}

    for metrics in result.pallet_metrics:
        pallet_id = pallet_id_map[metrics.pallet_index]
        height_left = metrics.height_left_mm
        if settings.height_includes_base:
            height_left_load = height_left
        else:
            height_left_load = height_left
        weight_left = None
        if settings.max_weight_kg is not None:
            weight_left = max(0.0, settings.max_weight_kg - metrics.weight_kg)
        rows: List[PalletSuggestion] = []
        for line in instance.order_lines:
            item = instance.catalog[line.sku]
            if item.place_only_on_bottom:
                continue
            orientations = generate_orientations(item)
            min_height = min(o.height_mm for o in orientations)
            if min_height <= 0:
                continue
            if height_left_load <= 0:
                continue
            max_boxes_by_height = height_left_load // min_height
            if max_boxes_by_height <= 0:
                continue
            if weight_left is not None and item.weight_kg:
                if item.weight_kg <= 0:
                    max_boxes_by_weight = max_boxes_by_height
                else:
                    max_boxes_by_weight = int(weight_left // item.weight_kg)
                max_boxes = min(max_boxes_by_height, max_boxes_by_weight)
            else:
                max_boxes = max_boxes_by_height
            if max_boxes <= 0:
                continue
            added_height = max_boxes * min_height
            new_height_left = height_left_load - added_height
            suggestion = PalletSuggestion(
                pallet_index=pallet_id,
                sku=line.sku,
                name=line.name,
                max_extra_boxes_by_height=int(max_boxes),
                added_height_mm=int(added_height),
                new_height_left_mm=int(new_height_left),
            )
            rows.append(suggestion)
        rows.sort(key=lambda s: (s.new_height_left_mm, s.sku))
        suggestions_by_pallet[pallet_id] = rows
    return suggestions_by_pallet
