from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Orientation:
    """Possible orthogonal orientation of a box."""

    length_mm: int
    width_mm: int
    height_mm: int

    def as_tuple(self) -> Tuple[int, int, int]:
        return self.length_mm, self.width_mm, self.height_mm


@dataclass
class CatalogItem:
    sku: str
    name: Optional[str]
    length_mm: int
    width_mm: int
    height_mm: int
    units_per_carton: int
    rotations_allowed: bool
    place_only_on_bottom: bool
    carton_indivisible: bool
    weight_kg: Optional[float] = None

    def base_orientation(self) -> Orientation:
        return Orientation(self.length_mm, self.width_mm, self.height_mm)


@dataclass
class OrderLine:
    sku: str
    name: Optional[str]
    qty_units_requested: int
    boxes_needed: int
    units_per_carton: int
    units_effective: int

    @property
    def overdelivered_units(self) -> int:
        return max(0, self.units_effective - self.qty_units_requested)


@dataclass
class BoxItem:
    id: int
    sku: str
    catalog_item: CatalogItem
    order_line: OrderLine


@dataclass
class PalletPlacement:
    pallet_index: int
    box_id: int
    sku: str
    name: Optional[str]
    units_on_pallet: int
    orientation: Orientation
    position: Tuple[int, int, int]


@dataclass
class PalletMetrics:
    pallet_index: int
    height_used_mm: int
    height_left_mm: int
    weight_kg: float
    boxes_count: int
    skus_count: int

    @property
    def height_fill_percent(self) -> float:
        if self.height_used_mm == 0:
            return 0.0
        total = self.height_used_mm + self.height_left_mm
        if total == 0:
            return 0.0
        return 100.0 * self.height_used_mm / total


@dataclass
class PalletSuggestion:
    pallet_index: int
    sku: str
    name: Optional[str]
    max_extra_boxes_by_height: int
    added_height_mm: int
    new_height_left_mm: int


@dataclass
class SolverSettings:
    time_limit_sec: Optional[int] = 120
    max_pallets_hint: Optional[int] = None
    mip_gap: float = 0.0


@dataclass
class LoggingSettings:
    level: str = "INFO"
    to_file: bool = True


@dataclass
class RuntimeSettings:
    pallet_base_length_mm: int = 1200
    pallet_base_width_mm: int = 800
    pallet_base_height_mm: int = 145
    max_total_height_mm: int = 1800
    max_weight_kg: Optional[float] = 500.0
    overhang_mm: int = 20
    height_includes_base: bool = True
    excel_encoding: str = "utf-8"
    suggestions_mode: str = "all_fit_by_height"
    solver: SolverSettings = field(default_factory=SolverSettings)
    logging: LoggingSettings = field(default_factory=LoggingSettings)

    def pallet_length_with_overhang(self) -> int:
        return self.pallet_base_length_mm + 2 * self.overhang_mm

    def pallet_width_with_overhang(self) -> int:
        return self.pallet_base_width_mm + 2 * self.overhang_mm

    def max_load_height_mm(self) -> int:
        if self.height_includes_base:
            return max(0, self.max_total_height_mm - self.pallet_base_height_mm)
        return self.max_total_height_mm


@dataclass
class SolverResult:
    placements: List[PalletPlacement]
    pallet_metrics: List[PalletMetrics]
    height_left_total: int
    used_pallets: int
    status: str


@dataclass
class InstanceData:
    catalog: Dict[str, CatalogItem]
    order_lines: List[OrderLine]
    boxes: List[BoxItem]
    settings: RuntimeSettings

    def boxes_by_sku(self) -> Dict[str, List[BoxItem]]:
        result: Dict[str, List[BoxItem]] = {}
        for box in self.boxes:
            result.setdefault(box.sku, []).append(box)
        return result
