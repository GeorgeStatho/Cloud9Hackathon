from __future__ import annotations

from typing import Dict, Optional

from PositionalObjects.Path import Path
from PositionalObjects.Position import Position


class Player:
    def __init__(
        self,
        player_id: str,
        name: str,
        max_samples: int = 2000,
        sample_hz: int = 30,
        enable_downsample: bool = True,
        enable_median: bool = True,
    ) -> None:
        self.player_id = player_id
        self.name = name
        self.current_pos: Optional[Position] = None
        self.alive = True

        self.max_samples = int(max_samples)
        self.sample_hz = int(sample_hz)
        self.enable_downsample = bool(enable_downsample)
        self.enable_median = bool(enable_median)

        # round_id -> Path
        self.paths: Dict[int, Path] = {}

    def start_round(self, round_id: int) -> None:
        self.paths[round_id] = Path(
            max_samples=self.max_samples,
            sample_hz=self.sample_hz,
            enable_downsample=self.enable_downsample,
            enable_median=self.enable_median,
        )
        self.alive = True

    def record_position(
        self,
        round_id: int,
        t: float,
        gx: float,
        gy: float,
        max_time: Optional[float] = None,
        net_worth: float | None = None,
        loadout_value: float | None = None,
        has_spike: bool | None = None,
    ) -> None:
        if not self._should_accept_sample(round_id):
            return

        path = self.paths[round_id]
        pos = path.add_sample(
            t=t,
            gx=gx,
            gy=gy,
            max_time=max_time,
            net_worth=net_worth,
            loadout_value=loadout_value,
            has_spike=has_spike,
        )
        if pos is not None:
            self.current_pos = pos

    def _should_accept_sample(self, round_id: int) -> bool:
        if not self.alive:
            return False
        if round_id not in self.paths:
            self.start_round(round_id)
        return True

    def mark_dead(self) -> None:
        self.alive = False
