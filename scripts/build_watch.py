#!/usr/bin/env python3
"""Backward-compatible entry — delegates to bw package (v2)."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from bw.cli import main

if __name__ == "__main__":
    main()