"""MTGO Match Tracker agent — Windows tray service.

All modules here must be cross-platform importable so tests run on Linux CI.
Windows-only calls are guarded with sys.platform checks at call sites, not
at import time.
"""
from __future__ import annotations

__version__ = "0.3.7"
