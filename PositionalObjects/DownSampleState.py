from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class DownsampleState:
    """Holds per-path downsampling state."""

    bucket_samples: Dict[int, List[Tuple[float, float, float]]] = field(
        default_factory=lambda: defaultdict(list)
    )
    last_bucket: Optional[int] = None
