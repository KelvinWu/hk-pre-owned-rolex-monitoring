#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = SKILL_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from inventory_sentinel.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
