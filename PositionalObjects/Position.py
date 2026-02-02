from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PositionalObjects.Map import Map


@dataclass
class Position:
    """Single positional sample in game space with optional metadata."""

    t: float
    gx: float
    gy: float
    net_worth: Optional[float] = None
    loadout_value: Optional[float] = None
    has_spike: Optional[bool] = None

    def to_image(self, game_map: Map) -> tuple[float, float]:
        return game_map.game_to_image(self.gx, self.gy)
