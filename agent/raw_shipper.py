"""Phase A raw-bytes shipper — hoards every .dat / .log to the server.

This is a side-channel to the watcher → parser → sender pipeline:
independent watchdog observer, independent upload queue, independent
local state. Capture now, analyze later — no parsing.

Dedup is by sha256 recorded in a local sqlite so restarts / crashes
don't cause re-uploads. On startup the shipper sweeps the watched dir
for anything it hasn't recorded as uploaded yet.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import queue
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

try:
    from watchdog.events import FileSystemEvent, FileSystemEventHandler
    from watchdog.observers import Observer
    _WATCHDOG_AVAILABLE = True
except ImportError:  # pragma: no cover — watchdog absent on CI app image
    FileSystemEvent = Any  # type: ignore[assignment, misc]
    FileSystemEventHandler = object  # type: ignore[assignment, misc]
    Observer = None  # type: ignore[assignment, misc]
    _WATCHDOG_AVAILABLE = False

from agent.config import AppConfig, get_config_path


logger = logging.getLogger(__name__)


STATE_DB_FILENAME = "upload_state.db"
UPLOAD_ENDPOINT = "/api/v1/agent/gamelogs/upload"
WATCHED_SUFFIXES = {".dat", ".log"}
STABLE_SECONDS = 5.0
MAX_ATTEMPTS = 5
RETRYABLE_STATUSES = {408, 425, 429, 500, 502, 503, 504}


def _state_db_path() -> Path:
    return get_config_path().parent / STATE_DB_FILENAME


def _open_state_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS uploaded_files (
            sha256 TEXT PRIMARY KEY,
            original_path TEXT NOT NULL,
            uploaded_at TEXT NOT NULL,
            server_upload_id INTEGER,
            status TEXT NOT NULL
        )
        """
    )
    return conn


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _file_type_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".dat":
        return "dat"
    if suffix == ".log":
        return "log"
    return "unknown"


class _ShipperEventHandler(FileSystemEventHandler):
    def __init__(self, shipper: "RawShipper") -> None:
        self._shipper = shipper

    def _handle(self, path_str: str) -> None:
        path = Path(path_str)
        if path.suffix.lower() not in WATCHED_SUFFIXES:
            return
        self._shipper.enqueue(path)

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self._handle(event.src_path)

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self._handle(event.src_path)


class RawShipper:
    """Ships raw log bytes to the server in the background."""

    def __init__(
        self,
        config: AppConfig,
        watched_dir: Path | None,
        state_db_path: Path | None = None,
    ) -> None:
        self._config = config
        self._watched_dir = watched_dir
        self._state_path = state_db_path or _state_db_path()
        self._queue: queue.Queue[Path | None] = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._observer: Any | None = None
        self._db: sqlite3.Connection | None = None
        self._db_lock = threading.Lock()

    # ---- lifecycle ----------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._db = _open_state_db(self._state_path)
        self._thread = threading.Thread(
            target=self._run_loop, name="manalog-raw-shipper", daemon=True
        )
        self._thread.start()
        self._start_observer()

    def stop(self) -> None:
        self._stop.set()
        if self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join(timeout=5)
            except Exception:
                logger.exception("raw_shipper observer stop raised")
            self._observer = None
        if self._thread is not None:
            self._queue.put(None)  # wake the loop
            self._thread.join(timeout=10)
            self._thread = None
        if self._db is not None:
            try:
                self._db.close()
            except sqlite3.Error:
                logger.exception("Error closing raw_shipper state DB")
            self._db = None

    def _start_observer(self) -> None:
        if not _WATCHDOG_AVAILABLE or Observer is None:
            logger.info("raw_shipper: watchdog unavailable — observer disabled")
            return
        if self._watched_dir is None:
            logger.info("raw_shipper: no watched_dir — observer disabled")
            return
        if not self._watched_dir.exists():
            try:
                self._watched_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                logger.warning("raw_shipper: cannot create watched dir %s", self._watched_dir)
                return
        observer = Observer()
        observer.schedule(_ShipperEventHandler(self), str(self._watched_dir), recursive=True)
        observer.start()
        self._observer = observer
        logger.info("raw_shipper: observing %s", self._watched_dir)

    # ---- public queueing ---------------------------------------------

    def enqueue(self, path: Path) -> None:
        if path.suffix.lower() not in WATCHED_SUFFIXES:
            return
        self._queue.put(path)

    # ---- loop ---------------------------------------------------------

    def _run_loop(self) -> None:
        try:
            asyncio.run(self._async_main())
        except Exception:
            logger.exception("raw_shipper loop crashed")

    async def _async_main(self) -> None:
        verify = self._config.server.tls_verify
        headers: dict[str, str] = {}
        if self._config.agent.api_token:
            headers["Authorization"] = f"Bearer {self._config.agent.api_token}"
        async with httpx.AsyncClient(
            base_url=self._config.server.url,
            verify=verify,
            headers=headers,
            timeout=60.0,
        ) as client:
            await self._startup_scan()
            while not self._stop.is_set():
                item = await asyncio.to_thread(self._queue.get)
                if item is None:
                    continue
                try:
                    await self._process_path(client, item)
                except Exception:
                    logger.exception("raw_shipper failed processing %s", item)

    async def _startup_scan(self) -> None:
        if self._watched_dir is None or not self._watched_dir.exists():
            return
        for suffix in WATCHED_SUFFIXES:
            for path in self._watched_dir.rglob(f"*{suffix}"):
                if not path.is_file():
                    continue
                self._queue.put(path)

    # ---- per-file workflow -------------------------------------------

    async def _process_path(self, client: httpx.AsyncClient, path: Path) -> None:
        if not path.is_file():
            return

        if not await self._wait_until_stable(path):
            return

        try:
            sha = await asyncio.to_thread(_sha256_of, path)
        except OSError:
            logger.exception("raw_shipper: failed reading %s", path)
            return

        if self._already_uploaded(sha):
            return

        try:
            data = await asyncio.to_thread(path.read_bytes)
            stat = path.stat()
        except OSError:
            logger.exception("raw_shipper: failed reading %s", path)
            return

        metadata = {
            "original_name": path.name,
            "file_type": _file_type_for(path),
            "captured_at": datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.utc
            ).isoformat(),
            "size": stat.st_size,
            "sha256": sha,
        }
        self._record_state(sha, path, status="pending", server_upload_id=None)
        await self._upload_with_retry(client, path, sha, data, metadata)

    async def _wait_until_stable(self, path: Path) -> bool:
        try:
            prev = path.stat()
        except OSError:
            return False
        churn_rounds = 0
        while not self._stop.is_set():
            await asyncio.sleep(STABLE_SECONDS)
            try:
                cur = path.stat()
            except OSError:
                return False
            if cur.st_mtime == prev.st_mtime and cur.st_size == prev.st_size:
                return True
            prev = cur
            churn_rounds += 1
            if churn_rounds > 12:  # ~1 minute of continuous churn
                logger.info("raw_shipper: giving up on stability check for %s", path)
                return False
        return False

    async def _upload_with_retry(
        self,
        client: httpx.AsyncClient,
        path: Path,
        sha: str,
        data: bytes,
        metadata: dict[str, Any],
    ) -> None:
        backoff = 2.0
        for attempt in range(1, MAX_ATTEMPTS + 1):
            if self._stop.is_set():
                return
            try:
                resp = await client.post(
                    UPLOAD_ENDPOINT,
                    files={"file": (path.name, data, "application/octet-stream")},
                    data={"metadata": json.dumps(metadata)},
                )
            except httpx.HTTPError as exc:
                logger.info(
                    "raw_shipper: upload network error for %s (attempt %d): %s",
                    path,
                    attempt,
                    exc,
                )
                if attempt == MAX_ATTEMPTS:
                    self._record_state(sha, path, status="failed", server_upload_id=None)
                    return
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)
                continue

            if resp.status_code in (200, 201):
                body: dict[str, Any] = {}
                try:
                    body = resp.json()
                except ValueError:
                    pass
                upload_id = None
                created = None
                if isinstance(body, dict):
                    upload_id = body.get("upload_id") or body.get("id")
                    created = body.get("created")
                if upload_id is not None and created is not None:
                    logger.info(
                        "raw_shipper: uploaded %s (upload_id=%s, new=%s)",
                        path.name,
                        upload_id,
                        created,
                    )
                elif upload_id is not None:
                    logger.info(
                        "raw_shipper: uploaded %s (upload_id=%s)", path.name, upload_id
                    )
                else:
                    logger.info("raw_shipper: uploaded %s", path.name)
                self._record_state(
                    sha,
                    path,
                    status="uploaded",
                    server_upload_id=int(upload_id) if upload_id is not None else None,
                )
                return

            if resp.status_code == 409:
                logger.info("raw_shipper: server already has %s (409)", path.name)
                self._record_state(sha, path, status="uploaded", server_upload_id=None)
                return

            if resp.status_code in RETRYABLE_STATUSES:
                logger.info(
                    "raw_shipper: upload %s returned %d (attempt %d)",
                    path.name,
                    resp.status_code,
                    attempt,
                )
                if attempt == MAX_ATTEMPTS:
                    self._record_state(sha, path, status="failed", server_upload_id=None)
                    return
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)
                continue

            logger.warning(
                "raw_shipper: upload %s rejected with %d %s",
                path.name,
                resp.status_code,
                resp.text[:200],
            )
            self._record_state(sha, path, status="failed", server_upload_id=None)
            return

    # ---- state helpers ------------------------------------------------

    def _already_uploaded(self, sha: str) -> bool:
        if self._db is None:
            return False
        with self._db_lock:
            row = self._db.execute(
                "SELECT status FROM uploaded_files WHERE sha256 = ?", (sha,)
            ).fetchone()
        return bool(row and row[0] == "uploaded")

    def _record_state(
        self,
        sha: str,
        path: Path,
        *,
        status: str,
        server_upload_id: int | None,
    ) -> None:
        if self._db is None:
            return
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._db_lock:
            self._db.execute(
                """
                INSERT INTO uploaded_files
                    (sha256, original_path, uploaded_at, server_upload_id, status)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(sha256) DO UPDATE SET
                    original_path = excluded.original_path,
                    uploaded_at   = excluded.uploaded_at,
                    server_upload_id = COALESCE(
                        excluded.server_upload_id, uploaded_files.server_upload_id
                    ),
                    status        = excluded.status
                """,
                (sha, str(path), now_iso, server_upload_id, status),
            )
