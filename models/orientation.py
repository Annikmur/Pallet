from __future__ import annotations

from itertools import permutations
from typing import List

from models.data_structures import CatalogItem, Orientation


def generate_orientations(item: CatalogItem) -> List[Orientation]:
    """Return all orthogonal orientations allowed for the catalog item."""
    base = item.base_orientation()
    dims = (base.length_mm, base.width_mm, base.height_mm)
    if not item.rotations_allowed:
        return [base]
    seen = set()
    for perm in permutations(dims, 3):
        seen.add(perm)
    return [Orientation(*dims) for dims in sorted(seen)]
