from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from statistics import median
from typing import Deque, Dict, Optional, Tuple

from Map import Map


@dataclass(frozen=True)
class Position:
    t: float
    gx: float
    gy: float
    net_worth: float | None = None
    loadout_value: float | None = None
    has_spike: bool | None = None

    def to_image(self, game_map: Map) -> tuple[float, float]:
        return game_map.game_to_image(self.gx, self.gy)

@dataclass
class DownsampleState:
    """
    Holds per-round downsampling / smoothing state.
    """
    # (round_id, bucket) -> list[(t, gx, gy)]
    bucket_samples: Dict[Tuple[int, int], list[Tuple[float, float, float]]] = field(
        default_factory=lambda: defaultdict(list)
    )

    # round_id -> last bucket we emitted
    last_bucket: Dict[int, int] = field(default_factory=dict)

    


class Player:
    def __init__(
        self,
        player_id: str,
        name: str,
        max_samples: int = 2000,
        sample_hz: int = 30,
        enable_downsample: bool = True,
        enable_median: bool = True,
    ):
        self.player_id = player_id
        self.name = name
        self.current_pos: Optional[Position] = None
        self.alive = True
        self.max_samples = max_samples

        # round_id -> deque[Position]
        self.paths: Dict[int, Deque[Position]] = {}

        # smoothing / downsample config
        self.sample_hz = int(sample_hz)
        self.enable_downsample = bool(enable_downsample)
        self.enable_median = bool(enable_median)

        # encapsulated smoothing state
        self._ds = DownsampleState()



    def start_round(self, round_id: int) -> None:
        self.paths[round_id] = deque(maxlen=self.max_samples)
        self.alive = True
        # reset per-round bucketing
        self._ds.last_bucket.pop(round_id, None)

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
        self._trim_time_window(path, t, max_time)

        # No downsampling: keep all points
        if self._should_store_raw():
            self._append_position(
                path,
                Position(
                    t=t,
                    gx=gx,
                    gy=gy,
                    net_worth=net_worth,
                    loadout_value=loadout_value,
                    has_spike=has_spike,
                ),
            )
            return

        # Downsample: bucket samples then possibly emit one representative point
        bucket = self._bucket_index(t)
        key = (round_id, bucket)
        self._ds.bucket_samples[key].append((t, gx, gy))

        if self._is_same_bucket(round_id, bucket):
            return

        samples = self._ds.bucket_samples.get(key)
        if not samples:
            return

        pos = self._representative_position(
            samples, net_worth=net_worth, loadout_value=loadout_value, has_spike=has_spike
        )
        self._append_position(path, pos)
        self._ds.last_bucket[round_id] = bucket
        self._cleanup_old_buckets(round_id, bucket)


    def _should_accept_sample(self, round_id: int) -> bool:
        """Validate player/round state and ensure the round deque exists."""
        if not self.alive:
            return False
        if round_id not in self.paths:
            self.start_round(round_id)
        return True


    def _trim_time_window(self, path: Deque[Position], t: float, max_time: Optional[float]) -> None:
        """Keep only positions within max_time seconds of the newest sample time."""
        if max_time is None:
            return
        while path and t - path[0].t > max_time:
            path.popleft()


    def _should_store_raw(self) -> bool:
        """True if we should append every point without downsampling."""
        return (not self.enable_downsample) or (self.sample_hz <= 0)


    def _bucket_index(self, t: float) -> int:
        """Convert time to an integer bucket index at sample_hz."""
        return int(t * self.sample_hz)


    def _is_same_bucket(self, round_id: int, bucket: int) -> bool:
        """Return True if we've already emitted for this bucket."""
        last_bucket = self._ds.last_bucket.get(round_id)
        return last_bucket is not None and bucket == last_bucket


    def _representative_position(
        self,
        samples: list[Tuple[float, float, float]],
        net_worth: float | None = None,
        loadout_value: float | None = None,
        has_spike: bool | None = None,
    ) -> Position:
        """
        Produce one representative Position from samples in the same bucket.
        Median is robust to outliers; otherwise use last sample.
        """
        if self.enable_median and len(samples) >= 3:
            ts = [s[0] for s in samples]
            xs = [s[1] for s in samples]
            ys = [s[2] for s in samples]
            return Position(
                t=float(median(ts)),
                gx=float(median(xs)),
                gy=float(median(ys)),
                net_worth=net_worth,
                loadout_value=loadout_value,
                has_spike=has_spike,
            )

        out_t, out_gx, out_gy = samples[-1]
        return Position(
            t=out_t,
            gx=out_gx,
            gy=out_gy,
            net_worth=net_worth,
            loadout_value=loadout_value,
            has_spike=has_spike,
        )


    def _append_position(self, path: Deque[Position], pos: Position) -> None:
        """Append position and update current_pos."""
        path.append(pos)
        self.current_pos = pos


    def _cleanup_old_buckets(self, round_id: int, bucket: int) -> None:
        """Prevent unbounded growth in bucket cache."""
        try:
            del self._ds.bucket_samples[(round_id, bucket - 2)]
        except KeyError:
            pass

    def mark_dead(self) -> None:
        self.alive = False
