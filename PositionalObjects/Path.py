from __future__ import annotations

from collections import deque
from statistics import median
from typing import Deque, Iterable, List, Optional, Tuple, Dict

from PositionalObjects.DownSampleState import DownsampleState
from PositionalObjects.Position import Position


class Path:
    """Collection of time-ordered Position samples for a single round."""

    def __init__(
        self,
        max_samples: int = 2000,
        sample_hz: int = 30,
        enable_downsample: bool = True,
        enable_median: bool = True,
    ) -> None:
        self.max_samples = int(max_samples)
        self.sample_hz = int(sample_hz)
        self.enable_downsample = bool(enable_downsample)
        self.enable_median = bool(enable_median)

        self.samples: Deque[Position] = deque(maxlen=self.max_samples)
        self._ds = DownsampleState()

    def __iter__(self) -> Iterable[Position]:
        return iter(self.samples)

    def __len__(self) -> int:
        return len(self.samples)

    def add_sample(
        self,
        t: float,
        gx: float,
        gy: float,
        max_time: Optional[float] = None,
        net_worth: float | None = None,
        loadout_value: float | None = None,
        has_spike: bool | None = None,
    ) -> Optional[Position]:
        self._trim_time_window(t, max_time)

        if self._should_store_raw():
            pos = Position(
                t=t,
                gx=gx,
                gy=gy,
                net_worth=net_worth,
                loadout_value=loadout_value,
                has_spike=has_spike,
            )
            self._append_position(pos)
            return pos

        bucket = self._bucket_index(t)
        self._ds.bucket_samples[bucket].append((t, gx, gy))

        if self._is_same_bucket(bucket):
            return None

        samples = self._ds.bucket_samples.get(bucket)
        if not samples:
            return None

        pos = self._representative_position(
            samples,
            net_worth=net_worth,
            loadout_value=loadout_value,
            has_spike=has_spike,
        )
        self._append_position(pos)
        self._ds.last_bucket = bucket
        self._cleanup_old_buckets(bucket)
        return pos

    def _should_store_raw(self) -> bool:
        return (not self.enable_downsample) or (self.sample_hz <= 0)

    def _bucket_index(self, t: float) -> int:
        return int(t * self.sample_hz)

    def _is_same_bucket(self, bucket: int) -> bool:
        return self._ds.last_bucket is not None and bucket == self._ds.last_bucket

    def _trim_time_window(self, t: float, max_time: Optional[float]) -> None:
        if max_time is None:
            return
        while self.samples and t - self.samples[0].t > max_time:
            self.samples.popleft()

    def _append_position(self, pos: Position) -> None:
        self.samples.append(pos)

    def _cleanup_old_buckets(self, bucket: int) -> None:
        try:
            del self._ds.bucket_samples[bucket - 2]
        except KeyError:
            pass

    def _representative_position(
        self,
        samples: list[Tuple[float, float, float]],
        net_worth: float | None = None,
        loadout_value: float | None = None,
        has_spike: bool | None = None,
    ) -> Position:
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

    @classmethod
    def from_json_samples(
        cls,
        samples: List[Dict[str, float]],
        max_samples: int = 2000,
        sample_hz: int = 30,
        enable_downsample: bool = False,
        enable_median: bool = True,
    ) -> "Path":
        """
        Build a Path from JSON samples (dicts with t/gx/gy + optional fields).
        Downsampling defaults to off to preserve exact stored samples.
        """
        path = cls(
            max_samples=max_samples,
            sample_hz=sample_hz,
            enable_downsample=enable_downsample,
            enable_median=enable_median,
        )
        for sample in samples:
            t = sample.get("t")
            gx = sample.get("gx")
            gy = sample.get("gy")
            if t is None or gx is None or gy is None:
                continue
            pos = Position(
                t=float(t),
                gx=float(gx),
                gy=float(gy),
                net_worth=sample.get("netWorth"),
                loadout_value=sample.get("loadoutValue"),
                has_spike=sample.get("hasSpike"),
            )
            path.samples.append(pos)
        return path
