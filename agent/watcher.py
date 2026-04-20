"""Filesystem watcher over the MTGO log directory.

On file create/modify for .dat or .log files, parse the file and invoke
the on_match callback if a ParsedMatch was extractable. A 2-second
debounce skips files currently being written.

The watchdog Observer runs in its own thread — the tray event loop
stays responsive.

watchdog is guarded so this module stays importable on Linux CI where
the package is not installed (app image only; agent runtime installs it).
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

try:
    from watchdog.events import FileSystemEvent, FileSystemEventHandler
    from watchdog.observers import Observer
    _WATCHDOG_AVAILABLE = True
except ImportError:  # pragma: no cover — watchdog absent on CI app image
    FileSystemEvent = Any  # type: ignore[assignment, misc]
    FileSystemEventHandler = object  # type: ignore[assignment, misc]
    Observer = None  # type: ignore[assignment, misc]
    _WATCHDOG_AVAILABLE = False

from agent.parser import ParsedMatch, parse_file


logger = logging.getLogger(__name__)

WATCHED_SUFFIXES = {".dat", ".log"}
DEBOUNCE_SECONDS = 2.0


class _LogEventHandler(FileSystemEventHandler):
    def __init__(self, on_match: Callable[[ParsedMatch], None]) -> None:
        self._on_match = on_match
        self._lock = threading.Lock()
        self._last_seen: dict[str, float] = {}

    def _handle(self, path_str: str) -> None:
        path = Path(path_str)
        if path.suffix.lower() not in WATCHED_SUFFIXES:
            return
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return
        if time.time() - mtime < DEBOUNCE_SECONDS:
            return

        with self._lock:
            prev = self._last_seen.get(path_str)
            if prev is not None and mtime <= prev:
                return
            self._last_seen[path_str] = mtime

        result = parse_file(path)
        if result is None:
            return
        try:
            self._on_match(result)
        except Exception:
            logger.exception("on_match callback raised")

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self._handle(event.src_path)

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self._handle(event.src_path)


class MTGOWatcher:
    def __init__(self, log_dir: Path, on_match: Callable[[ParsedMatch], None]) -> None:
        self._log_dir = log_dir
        self._handler = _LogEventHandler(on_match)
        self._observer: Any | None = None

    def start(self) -> None:
        if self._observer is not None:
            return
        if not self._log_dir.exists():
            logger.warning("MTGO log dir does not exist: %s", self._log_dir)
            self._log_dir.mkdir(parents=True, exist_ok=True)
        observer = Observer()
        observer.schedule(self._handler, str(self._log_dir), recursive=True)
        observer.start()
        self._observer = observer
        logger.info("Watching %s", self._log_dir)

    def stop(self) -> None:
        if self._observer is None:
            return
        self._observer.stop()
        self._observer.join(timeout=5)
        self._observer = None
