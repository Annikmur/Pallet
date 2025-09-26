from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from ortools.sat.python import cp_model

from models.data_structures import (
    InstanceData,
    Orientation,
    PalletMetrics,
    PalletPlacement,
    SolverResult,
)
from models.orientation import generate_orientations


@dataclass
class _BoxVariables:
    orientation_bools: List[cp_model.IntVar]
    dims_x: cp_model.IntVar
    dims_y: cp_model.IntVar
    dims_z: cp_model.IntVar
    assign: List[cp_model.IntVar]
    start_x: List[cp_model.IntVar]
    start_y: List[cp_model.IntVar]
    start_z: List[cp_model.IntVar]
    end_z: List[cp_model.IntVar]


def solve(instance: InstanceData) -> SolverResult:
    settings = instance.settings
    if not instance.boxes:
        return SolverResult(
            placements=[],
            pallet_metrics=[],
            height_left_total=0,
            used_pallets=0,
            status="NO_BOXES",
        )

    max_pallets_hint = settings.solver.max_pallets_hint or len(instance.boxes)
    best_result: SolverResult | None = None

    for pallet_count in range(1, max_pallets_hint + 1):
        candidate = _solve_with_pallet_limit(instance, pallet_count)
        if candidate is None:
            continue
        best_result = candidate
        break

    if best_result is None:
        raise RuntimeError("Unable to find feasible palletization with given constraints")

    return best_result


def _solve_with_pallet_limit(instance: InstanceData, max_pallets: int) -> SolverResult | None:
    settings = instance.settings
    model = cp_model.CpModel()

    pallet_length = settings.pallet_length_with_overhang()
    pallet_width = settings.pallet_width_with_overhang()
    max_load_height = settings.max_load_height_mm()

    orientations_map: Dict[str, List[Orientation]] = {
        sku: generate_orientations(item) for sku, item in instance.catalog.items()
    }

    num_boxes = len(instance.boxes)

    box_vars: List[_BoxVariables] = []

    for box in instance.boxes:
        orientations = orientations_map[box.sku]
        orient_bools = [model.NewBoolVar(f"box{box.id}_orient_{i}") for i in range(len(orientations))]
        model.Add(sum(orient_bools) == 1)

        dims_x = model.NewIntVar(min(o.length_mm for o in orientations), max(o.length_mm for o in orientations), f"box{box.id}_x")
        dims_y = model.NewIntVar(min(o.width_mm for o in orientations), max(o.width_mm for o in orientations), f"box{box.id}_y")
        dims_z = model.NewIntVar(min(o.height_mm for o in orientations), max(o.height_mm for o in orientations), f"box{box.id}_z")

        model.Add(sum(orient_bools[i] * orientations[i].length_mm for i in range(len(orientations))) == dims_x)
        model.Add(sum(orient_bools[i] * orientations[i].width_mm for i in range(len(orientations))) == dims_y)
        model.Add(sum(orient_bools[i] * orientations[i].height_mm for i in range(len(orientations))) == dims_z)

        assign = [model.NewBoolVar(f"box{box.id}_p{p}") for p in range(max_pallets)]
        model.Add(sum(assign) == 1)

        start_x = [model.NewIntVar(0, pallet_length, f"box{box.id}_p{p}_xstart") for p in range(max_pallets)]
        start_y = [model.NewIntVar(0, pallet_width, f"box{box.id}_p{p}_ystart") for p in range(max_pallets)]
        start_z = [model.NewIntVar(0, max_load_height, f"box{box.id}_p{p}_zstart") for p in range(max_pallets)]
        end_z = [model.NewIntVar(0, max_load_height, f"box{box.id}_p{p}_zend") for p in range(max_pallets)]

        for p in range(max_pallets):
            model.Add(start_x[p] + dims_x <= pallet_length).OnlyEnforceIf(assign[p])
            model.Add(start_y[p] + dims_y <= pallet_width).OnlyEnforceIf(assign[p])
            model.Add(start_z[p] + dims_z <= max_load_height).OnlyEnforceIf(assign[p])

            model.Add(start_x[p] == 0).OnlyEnforceIf(assign[p].Not())
            model.Add(start_y[p] == 0).OnlyEnforceIf(assign[p].Not())
            model.Add(start_z[p] == 0).OnlyEnforceIf(assign[p].Not())
            model.Add(end_z[p] == 0).OnlyEnforceIf(assign[p].Not())
            model.Add(end_z[p] == start_z[p] + dims_z).OnlyEnforceIf(assign[p])

            if box.catalog_item.place_only_on_bottom:
                model.Add(start_z[p] == 0).OnlyEnforceIf(assign[p])

        box_vars.append(
            _BoxVariables(
                orientation_bools=orient_bools,
                dims_x=dims_x,
                dims_y=dims_y,
                dims_z=dims_z,
                assign=assign,
                start_x=start_x,
                start_y=start_y,
                start_z=start_z,
                end_z=end_z,
            )
        )

    used = [model.NewBoolVar(f"pallet_{p}_used") for p in range(max_pallets)]

    for p in range(max_pallets):
        model.Add(sum(box_vars[b].assign[p] for b in range(num_boxes)) >= used[p])
        for b in range(num_boxes):
            model.Add(box_vars[b].assign[p] <= used[p])

    pallet_height = [model.NewIntVar(0, max_load_height, f"pallet_{p}_height") for p in range(max_pallets)]
    height_left = [model.NewIntVar(0, max_load_height, f"pallet_{p}_height_left") for p in range(max_pallets)]

    for p in range(max_pallets):
        model.Add(pallet_height[p] == 0).OnlyEnforceIf(used[p].Not())
        model.Add(height_left[p] == 0).OnlyEnforceIf(used[p].Not())
        model.Add(pallet_height[p] + height_left[p] == max_load_height).OnlyEnforceIf(used[p])
        model.Add(pallet_height[p] <= max_load_height * used[p])

    for vars_b in box_vars:
        for p in range(max_pallets):
            model.Add(pallet_height[p] >= vars_b.end_z[p]).OnlyEnforceIf(vars_b.assign[p])

    for p in range(max_pallets):
        model.AddMaxEquality(pallet_height[p], [vars_b.end_z[p] for vars_b in box_vars])
    # Pairwise non-overlap constraints
    for i in range(num_boxes):
        for j in range(i + 1, num_boxes):
            vars_i = box_vars[i]
            vars_j = box_vars[j]
            for p in range(max_pallets):
                left = model.NewBoolVar(f"box{i}_before_box{j}_x_p{p}")
                right = model.NewBoolVar(f"box{j}_before_box{i}_x_p{p}")
                front = model.NewBoolVar(f"box{i}_before_box{j}_y_p{p}")
                back = model.NewBoolVar(f"box{j}_before_box{i}_y_p{p}")
                below = model.NewBoolVar(f"box{i}_below_box{j}_p{p}")
                above = model.NewBoolVar(f"box{j}_below_box{i}_p{p}")

                for var in (left, right, front, back, below, above):
                    model.Add(var <= vars_i.assign[p])
                    model.Add(var <= vars_j.assign[p])

                model.Add(vars_i.start_x[p] + vars_i.dims_x <= vars_j.start_x[p]).OnlyEnforceIf(left)
                model.Add(vars_j.start_x[p] + vars_j.dims_x <= vars_i.start_x[p]).OnlyEnforceIf(right)
                model.Add(vars_i.start_y[p] + vars_i.dims_y <= vars_j.start_y[p]).OnlyEnforceIf(front)
                model.Add(vars_j.start_y[p] + vars_j.dims_y <= vars_i.start_y[p]).OnlyEnforceIf(back)
                model.Add(vars_i.start_z[p] + vars_i.dims_z <= vars_j.start_z[p]).OnlyEnforceIf(below)
                model.Add(vars_j.start_z[p] + vars_j.dims_z <= vars_i.start_z[p]).OnlyEnforceIf(above)

                model.AddBoolOr(
                    [
                        left,
                        right,
                        front,
                        back,
                        below,
                        above,
                        vars_i.assign[p].Not(),
                        vars_j.assign[p].Not(),
                    ]
                )

    # Weight constraints
    if settings.max_weight_kg is not None:
        weight_scale = 1000  # grams
        max_weight_scaled = int(round(settings.max_weight_kg * weight_scale))
        for p in range(max_pallets):
            weight_terms = []
            for box, vars_b in zip(instance.boxes, box_vars):
                weight = box.catalog_item.weight_kg or 0.0
                weight_scaled = int(round(weight * weight_scale))
                if weight_scaled:
                    weight_terms.append(weight_scaled * vars_b.assign[p])
            if weight_terms:
                model.Add(sum(weight_terms) <= max_weight_scaled)

    model.Add(sum(used) >= 1)

    # Objective: lexicographic: minimize height left, then total elevation
    total_height_left = sum(height_left)
    total_start_z = sum(vars_b.start_z[p] for vars_b in box_vars for p in range(max_pallets))
    objective = total_height_left * (max_load_height + 1) + total_start_z
    model.Minimize(objective)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = settings.solver.time_limit_sec or 120
    solver.parameters.relative_gap_limit = settings.solver.mip_gap
    solver.parameters.num_search_workers = 8

    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None

    placements: List[PalletPlacement] = []
    pallet_metrics: Dict[int, PalletMetrics] = {}

    pallet_height_values = {}
    height_left_values = {}
    used_pallet_indices: List[int] = []

    for p in range(max_pallets):
        if solver.BooleanValue(used[p]):
            used_pallet_indices.append(p)
            pallet_height_values[p] = solver.Value(pallet_height[p])
            height_left_values[p] = solver.Value(height_left[p])
        else:
            pallet_height_values[p] = 0
            height_left_values[p] = max_load_height

    for box, vars_b in zip(instance.boxes, box_vars):
        assigned_p = None
        for p in range(max_pallets):
            if solver.BooleanValue(vars_b.assign[p]):
                assigned_p = p
                break
        if assigned_p is None:
            continue
        orientation_index = None
        orientations = orientations_map[box.sku]
        for i, var in enumerate(vars_b.orientation_bools):
            if solver.BooleanValue(var):
                orientation_index = i
                break
        if orientation_index is None:
            orientation_index = 0
        orientation = orientations[orientation_index]
        position = (
            solver.Value(vars_b.start_x[assigned_p]),
            solver.Value(vars_b.start_y[assigned_p]),
            solver.Value(vars_b.start_z[assigned_p]),
        )
        placements.append(
            PalletPlacement(
                pallet_index=assigned_p,
                box_id=box.id,
                sku=box.sku,
                name=box.order_line.name,
                units_on_pallet=box.order_line.units_per_carton,
                orientation=orientation,
                position=position,
            )
        )

    pallet_metrics_list: List[PalletMetrics] = []
    for p in used_pallet_indices:
        boxes_on_pallet = [pl for pl in placements if pl.pallet_index == p]
        height_used = pallet_height_values[p] + settings.pallet_base_height_mm
        height_left_total = settings.max_total_height_mm - height_used if settings.height_includes_base else max_load_height - pallet_height_values[p]
        weight_sum = 0.0
        sku_set = set()
        for placement in boxes_on_pallet:
            sku_set.add(placement.sku)
            weight = instance.catalog[placement.sku].weight_kg or 0.0
            weight_sum += weight
        metrics = PalletMetrics(
            pallet_index=p,
            height_used_mm=height_used,
            height_left_mm=height_left_total,
            weight_kg=weight_sum,
            boxes_count=len(boxes_on_pallet),
            skus_count=len(sku_set),
        )
        pallet_metrics_list.append(metrics)

    total_height_left = sum(m.height_left_mm for m in pallet_metrics_list)

    status_map = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
    }

    return SolverResult(
        placements=placements,
        pallet_metrics=pallet_metrics_list,
        height_left_total=total_height_left,
        used_pallets=len(pallet_metrics_list),
        status=status_map.get(status, str(status)),
    )
