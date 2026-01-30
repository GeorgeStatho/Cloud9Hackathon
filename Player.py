from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional

from Map import Map


@dataclass(frozen=True)
class Position:
    t: float
    gx: float
    gy: float

    def to_image(self, game_map: Map) -> tuple[float, float]:
        return game_map.game_to_image(self.gx, self.gy)


class Player:
    def __init__(self, player_id: str, name: str, max_samples: int = 2000):
        self.player_id = player_id
        self.name = name
        self.current_pos: Optional[Position] = None
        self.alive = True
        self.max_samples = max_samples
        self.paths: Dict[int, Deque[Position]] = {}

    def start_round(self, round_id: int) -> None:
        self.paths[round_id] = deque(maxlen=self.max_samples)
        self.alive = True

    def record_position(
        self,
        round_id: int,
        t: float,
        gx: float,
        gy: float,
        max_time: Optional[float] = None,
    ) -> None:
        if not self.alive:
            return
        if round_id not in self.paths:
            self.start_round(round_id)

        path = self.paths[round_id]
        if max_time is not None:
            while path and t - path[0].t > max_time:
                path.popleft()

        pos = Position(t=t, gx=gx, gy=gy)
        path.append(pos)
        self.current_pos = pos

    def mark_dead(self) -> None:
        self.alive = False

