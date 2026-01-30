from __future__ import annotations

import sys
from pathlib import Path

# Ensure the project root is on sys.path so PathScripts modules can import root-level files.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
