"""Tray application — pystray icon + menu + thread orchestration.

The tray event loop is blocking; the watcher, heartbeat, and updater
all run on their own threads. Module imports are guarded so the module
stays importable on Linux CI where pystray's backend may fail to bind
a display.
"""
from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
import threading
import time
import webbrowser
from enum import Enum
from pathlib import Path
from typing import Any

from agent import __version__
from agent.about_window import AboutWindow
from agent.config import AppConfig, ConfigLoadError, load_config
from agent.log_viewer import LogViewerWindow
from agent.parser import ParsedMatch
from agent.raw_shipper import RawShipper
from agent.sender import AgentSender
from agent.settings_window import SettingsWindow
from agent.updater import apply_update, check_for_update, download_and_verify
from agent.watcher import MTGOWatcher

try:
    import pystray  # type: ignore[import-untyped]
    from PIL import Image  # type: ignore[import-untyped]
    _TRAY_AVAILABLE = True
except Exception:  # pragma: no cover — pystray picks a display backend at
    # import time on Linux; headless CI raises a display-connection error,
    # not ImportError. Swallow anything so the module stays importable.
    pystray = None  # type: ignore[assignment]
    Image = None  # type: ignore[assignment]
    _TRAY_AVAILABLE = False


logger = logging.getLogger(__name__)


def _icons_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "agent" / "icons"  # type: ignore[attr-defined]
    return Path(__file__).parent / "icons"


ICONS_DIR = _icons_dir()
ACTIVE_WINDOW_SECONDS = 180  # 3 minutes — tunable
COLOR_CYCLE = ["W", "U", "B", "R", "G"]
COLOR_CYCLE_SECONDS = 120  # 2 minutes per pip
IDLE_ICON = "C"


class ConnectionStatus(str, Enum):
    UNKNOWN = "unknown"
    NOT_REGISTERED = "not-registered"
    CONNECTED = "connected"
    OFFLINE = "offline"
    PAUSED = "paused"
    CONFIG_ERROR = "config-error"


def _make_default_icon() -> Any:
    if Image is None:
        return None
    return Image.new("RGB", (64, 64), color=(30, 80, 200))


class TrayApp:
    def __init__(
        self,
        config: AppConfig,
        sender: AgentSender,
        log_file: Path | None = None,
        config_error: ConfigLoadError | None = None,
    ) -> None:
        self._config = config
        self._sender = sender
        self._log_file = log_file
        self._config_error = config_error
        self._paused = False
        self._stop = threading.Event()
        self._watcher: MTGOWatcher | None = None
        self._icon: Any = None
        self._heartbeat_thread: threading.Thread | None = None
        self._update_thread: threading.Thread | None = None
        self._last_heartbeat_ok: bool | None = None
        self._staged_update: Path | None = None
        self._staged_update_tag: str | None = None
        self._staged_lock = threading.Lock()
        # Tags whose download or checksum failed this session — skip until
        # next scheduled check or until user explicitly clicks Check for
        # Updates. Avoids burning bandwidth on a busted release.
        self._failed_update_tags: set[str] = set()
        self._manual_check_override = False
        # Dedicated loop for sender operations (heartbeat + upload + close).
        # httpx.AsyncClient binds its connection pool to the first loop that
        # uses it; routing every sender coroutine through a single persistent
        # loop avoids "Event loop is closed" on subsequent calls.
        self._sender_loop: asyncio.AbstractEventLoop | None = None
        self._sender_loop_thread: threading.Thread | None = None
        self._settings_window: SettingsWindow | None = None
        self._log_viewer: LogViewerWindow | None = None
        self._about_window: AboutWindow | None = None
        # Central registry of open sub-windows so _on_quit can close them
        # all. Each entry exposes a ``close()`` that schedules destroy on
        # its own tkinter event loop.
        self._sub_windows: list[Any] = []
        self._sub_windows_lock = threading.Lock()
        self._raw_shipper: RawShipper | None = None
        self._icon_timer_thread: threading.Thread | None = None

    # ---- raw-shipper hook (icon cycling) ------------------------------

    def set_raw_shipper(self, shipper: RawShipper) -> None:
        self._raw_shipper = shipper

    def _is_tray_active(self) -> bool:
        if self._raw_shipper is None:
            return False
        last = self._raw_shipper.last_upload_at
        if last is None:
            return False
        return (time.time() - last) < ACTIVE_WINDOW_SECONDS

    def _current_pip_name(self) -> str:
        """Returns the icon filename stem: IDLE_ICON or one of COLOR_CYCLE."""
        if not self._is_tray_active():
            return IDLE_ICON
        last = self._raw_shipper.last_upload_at  # type: ignore[union-attr]
        if last is None:
            return IDLE_ICON
        elapsed = time.time() - last
        total_cycle = COLOR_CYCLE_SECONDS * len(COLOR_CYCLE)
        pos = elapsed % total_cycle
        idx = int(pos // COLOR_CYCLE_SECONDS)
        return COLOR_CYCLE[idx]

    def _load_pip_icon(self, name: str) -> Any:
        """Load a pip icon from agent/icons/<name>.ico; fall back to default."""
        if Image is None:
            return None
        ico_path = ICONS_DIR / f"{name}.ico"
        if ico_path.exists():
            try:
                return Image.open(ico_path)
            except Exception:
                logger.exception("Failed to load pip icon %s", ico_path)
        return _make_default_icon()

    def _update_tray_icon(self) -> None:
        """Swap the tray icon to match current state."""
        if self._icon is None:
            return
        name = self._current_pip_name()
        img = self._load_pip_icon(name)
        if img is None:
            return
        try:
            self._icon.icon = img
        except Exception:
            logger.exception("Failed to update tray icon to %s", name)

    def _start_icon_timer(self) -> None:
        """Background thread that updates the tray icon every 30 seconds."""
        def _loop() -> None:
            while not self._stop.is_set():
                self._update_tray_icon()
                self._stop.wait(30)

        t = threading.Thread(target=_loop, name="manalog-icon-timer", daemon=True)
        t.start()
        self._icon_timer_thread = t

    # ---- lifecycle -----------------------------------------------------

    def run(self) -> None:
        if not _TRAY_AVAILABLE:
            logger.warning("pystray/PIL unavailable — tray not started")
            return

        icon_image = self._load_pip_icon(IDLE_ICON)
        menu = self._build_menu()
        self._icon = pystray.Icon(
            "manalog", icon_image, f"Manalog v{__version__}", menu
        )

        self._start_sender_loop()
        self._start_watcher()
        self._start_heartbeat_loop()
        self._start_update_loop()
        self._start_icon_timer()
        self._update_tray_icon()  # set initial icon immediately
        self._icon.run()

    # ---- sender loop ---------------------------------------------------

    def _start_sender_loop(self) -> None:
        ready = threading.Event()

        def _runner() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._sender_loop = loop
            ready.set()
            try:
                loop.run_forever()
            finally:
                try:
                    loop.run_until_complete(loop.shutdown_asyncgens())
                except Exception:
                    logger.exception("Error shutting down async generators")
                loop.close()

        thread = threading.Thread(target=_runner, name="mtgo-sender-loop", daemon=True)
        thread.start()
        ready.wait(timeout=5.0)
        self._sender_loop_thread = thread

    def _run_on_sender_loop(self, coro: Any, timeout: float = 60.0) -> Any:
        loop = self._sender_loop
        if loop is None or not loop.is_running():
            # Fallback for tests / early-teardown paths: spin a throwaway
            # loop. Production path always has the worker running.
            tmp = asyncio.new_event_loop()
            try:
                return tmp.run_until_complete(coro)
            finally:
                tmp.close()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=timeout)

    def _stop_sender_loop(self) -> None:
        loop = self._sender_loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        if self._sender_loop_thread is not None:
            self._sender_loop_thread.join(timeout=5.0)

    # ---- status --------------------------------------------------------

    def connection_status(self) -> ConnectionStatus:
        if self._config_error is not None:
            return ConnectionStatus.CONFIG_ERROR
        if not self._config.agent.api_token:
            return ConnectionStatus.NOT_REGISTERED
        if self._paused:
            return ConnectionStatus.PAUSED
        if self._last_heartbeat_ok is None:
            return ConnectionStatus.UNKNOWN
        return ConnectionStatus.CONNECTED if self._last_heartbeat_ok else ConnectionStatus.OFFLINE

    def _status_text(self) -> str:
        labels = {
            ConnectionStatus.NOT_REGISTERED: "Status: Not registered",
            ConnectionStatus.PAUSED: "Status: Paused",
            ConnectionStatus.UNKNOWN: "Status: Connecting…",
            ConnectionStatus.CONNECTED: "Status: Connected",
            ConnectionStatus.OFFLINE: "Status: Offline",
            ConnectionStatus.CONFIG_ERROR: "Status: Config error — click Settings to fix",
        }
        return labels[self.connection_status()]

    # ---- watcher -------------------------------------------------------

    def _start_watcher(self) -> None:
        log_dir = Path(self._config.mtgo.log_dir) if self._config.mtgo.log_dir else None
        if log_dir is None:
            logger.info("No MTGO log_dir configured — watcher idle")
            return
        self._watcher = MTGOWatcher(log_dir, self._on_match)
        self._watcher.start()

    def _stop_watcher(self) -> None:
        if self._watcher is not None:
            self._watcher.stop()
            self._watcher = None

    def _on_match(self, match: ParsedMatch) -> None:
        if self._paused:
            return
        try:
            self._run_on_sender_loop(self._sender.upload(match))
        except Exception:
            logger.exception("Failed to upload match %s", match.mtgo_match_id)

    # ---- heartbeat loop ------------------------------------------------

    def _start_heartbeat_loop(self) -> None:
        interval = max(5, int(self._config.heartbeat.interval_seconds))

        def _loop() -> None:
            while not self._stop.is_set():
                if self._paused or not self._config.agent.api_token:
                    if self._stop.wait(interval):
                        return
                    continue
                try:
                    ok = self._run_on_sender_loop(self._sender.heartbeat())
                except Exception:
                    logger.exception("Heartbeat raised")
                    ok = False
                self._set_heartbeat_result(ok)
                if self._stop.wait(interval):
                    return

        thread = threading.Thread(target=_loop, name="mtgo-heartbeat", daemon=True)
        thread.start()
        self._heartbeat_thread = thread

    def _set_heartbeat_result(self, ok: bool) -> None:
        changed = self._last_heartbeat_ok != ok
        self._last_heartbeat_ok = ok
        if changed:
            self._refresh_menu()

    # ---- update loop ---------------------------------------------------

    def _start_update_loop(self) -> None:
        interval_hours = max(1, int(self._config.updates.check_interval_hours))
        interval_seconds = interval_hours * 3600

        def _loop() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                while not self._stop.is_set():
                    self._check_updates_once_on_loop(loop)
                    if self._stop.wait(interval_seconds):
                        return
            finally:
                loop.close()

        thread = threading.Thread(target=_loop, name="mtgo-updater", daemon=True)
        thread.start()
        self._update_thread = thread

    def _check_updates_once(self) -> None:
        """Poll GitHub, download + verify if newer, stage for restart.

        Public entry point — used by the tray menu's manual check, which
        spawns a fresh thread each time. Creates and closes its own loop.
        """
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            self._check_updates_once_on_loop(loop)
        finally:
            loop.close()
            asyncio.set_event_loop(None)

    def _check_updates_once_on_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        try:
            result = loop.run_until_complete(check_for_update(self._config))
        except Exception:
            logger.exception("Update check failed")
            return
        if result is None:
            return
        tag, url = result

        with self._staged_lock:
            if self._staged_update_tag == tag and self._staged_update is not None:
                return

        if tag in self._failed_update_tags and not self._manual_check_override:
            logger.info(
                "updater: skipping re-download of %s — previous attempt "
                "failed this session",
                tag,
            )
            return

        token = self._config.updates.github_token or None
        try:
            staged = loop.run_until_complete(download_and_verify(url, token))
        except Exception:
            logger.exception("Update download raised")
            staged = None

        if staged is None:
            self._failed_update_tags.add(tag)
            self._notify(f"Update {tag} download failed — check log.")
            return

        with self._staged_lock:
            self._staged_update = staged
            self._staged_update_tag = tag
        self._failed_update_tags.discard(tag)
        self._refresh_menu()
        self._notify(f"Update {tag} downloaded — click 'Restart to Update' to apply.")

    def _has_staged_update(self) -> bool:
        return self._staged_update is not None

    def _refresh_menu(self) -> None:
        if self._icon is None:
            return
        try:
            self._icon.update_menu()
        except Exception:
            logger.exception("Failed to refresh tray menu")

    # ---- menu handlers -------------------------------------------------

    def _build_menu(self) -> Any:
        if not _TRAY_AVAILABLE:
            return None
        MenuItem = pystray.MenuItem  # noqa: N806
        Menu = pystray.Menu  # noqa: N806
        return Menu(
            MenuItem(lambda item: self._status_text(), None, enabled=False),
            Menu.SEPARATOR,
            MenuItem(
                lambda item: "Resume Monitoring" if self._paused else "Pause Monitoring",
                self._on_pause_resume,
            ),
            MenuItem("Open Dashboard", self._on_open_dashboard),
            Menu.SEPARATOR,
            MenuItem(
                "Restart to Update",
                self._on_restart_to_update,
                visible=lambda item: self._has_staged_update(),
            ),
            MenuItem("Check for Updates", self._on_check_updates),
            MenuItem("Settings…", self._on_settings),
            MenuItem("Reload Config", self._on_reload_config),
            MenuItem("Open Log", self._on_open_log),
            Menu.SEPARATOR,
            MenuItem("About", self._on_about),
            MenuItem("Quit", self._on_quit),
        )

    def _on_pause_resume(self, icon: Any, item: Any) -> None:
        self._paused = not self._paused
        logger.info("Monitoring %s", "paused" if self._paused else "resumed")
        self._refresh_menu()

    def _on_open_dashboard(self, icon: Any, item: Any) -> None:
        webbrowser.open(self._config.server.url)

    def _on_check_updates(self, icon: Any, item: Any) -> None:
        def _run() -> None:
            self._manual_check_override = True
            try:
                self._check_updates_once()
            finally:
                self._manual_check_override = False

        threading.Thread(target=_run, daemon=True).start()

    def _on_restart_to_update(self, icon: Any, item: Any) -> None:
        with self._staged_lock:
            staged = self._staged_update
        if staged is None:
            return
        logger.info("Applying staged update: %s", staged)
        try:
            apply_update(staged)
        except SystemExit:
            raise
        except Exception:
            logger.exception("apply_update failed")
            return
        # Only reached on non-win32 where apply_update is a no-op.
        with self._staged_lock:
            self._staged_update = None
            self._staged_update_tag = None
        self._refresh_menu()

    def _register_sub_window(self, window: Any) -> None:
        with self._sub_windows_lock:
            self._sub_windows.append(window)

    def _unregister_sub_window(self, window: Any) -> None:
        with self._sub_windows_lock:
            try:
                self._sub_windows.remove(window)
            except ValueError:
                pass

    def _on_settings(self, icon: Any, item: Any) -> None:
        existing = self._settings_window
        if existing is not None and existing._thread is not None and existing._thread.is_alive():
            return
        window = SettingsWindow(
            self._config,
            on_save=self.reload_config,
            on_close=lambda: self._unregister_sub_window(window),
        )
        self._settings_window = window
        self._register_sub_window(window)
        window.show()

    def _on_reload_config(self, icon: Any, item: Any) -> None:
        self.reload_config()

    def reload_config(self) -> None:
        """Re-read config.toml and rebuild watcher + sender in place."""
        try:
            new_config = load_config()
        except Exception:
            logger.exception("Failed to load config from disk")
            self._notify("Config reload failed — check log.")
            return

        self._config = new_config

        self._stop_watcher()
        self._start_watcher()

        old_sender = self._sender
        self._sender = AgentSender(new_config)
        try:
            self._run_on_sender_loop(old_sender.close())
        except Exception:
            logger.exception("Error closing previous sender during reload")

        logger.info("config: hot-reloaded from disk")
        self._notify("Config reloaded.")
        self._refresh_menu()

    def _on_open_log(self, icon: Any, item: Any) -> None:
        existing = self._log_viewer
        if existing is not None and existing._thread is not None and existing._thread.is_alive():
            return
        viewer = LogViewerWindow(
            self._log_file,
            on_close=lambda: self._unregister_sub_window(viewer),
        )
        self._log_viewer = viewer
        self._register_sub_window(viewer)
        viewer.show()

    def _on_about(self, icon: Any, item: Any) -> None:
        existing = self._about_window
        if existing is not None and existing._thread is not None and existing._thread.is_alive():
            return
        window = AboutWindow(
            self._config,
            on_close=lambda: self._unregister_sub_window(window),
        )
        self._about_window = window
        self._register_sub_window(window)
        window.show()

    def _on_quit(self, icon: Any, item: Any) -> None:
        self._stop.set()
        self._stop_watcher()
        self._close_sub_windows()
        try:
            self._run_on_sender_loop(self._sender.close())
        except Exception:
            logger.exception("Error closing sender")
        self._stop_sender_loop()
        if self._icon is not None:
            self._icon.stop()
        sys.exit(0)

    def _close_sub_windows(self, grace_seconds: float = 0.3) -> None:
        """Close every registered sub-window.

        ``close()`` schedules ``root.destroy`` on the window's own tkinter
        loop — calling from this thread is safe because ``tk.after`` is
        the cross-thread-safe handoff. A short grace period lets those
        destroys actually land before the interpreter exits.
        """
        with self._sub_windows_lock:
            windows = list(self._sub_windows)
        for window in windows:
            try:
                window.close()
            except Exception:
                logger.exception("Error closing sub-window %r", window)
        if windows:
            time.sleep(grace_seconds)

    # ---- helpers -------------------------------------------------------

    def _open_in_editor(self, path: Path) -> None:
        if not path.exists():
            logger.warning("Path does not exist: %s", path)
            return
        if sys.platform == "win32":
            import os as _os
            _os.startfile(str(path))  # type: ignore[attr-defined]  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])  # noqa: S603,S607
        else:
            subprocess.Popen(["xdg-open", str(path)])  # noqa: S603,S607

    def _notify(self, message: str) -> None:
        logger.info("TRAY: %s", message)
        if self._icon is not None and hasattr(self._icon, "notify"):
            try:
                self._icon.notify(message, "Manalog")
            except Exception:
                logger.exception("Failed to show tray notification")
