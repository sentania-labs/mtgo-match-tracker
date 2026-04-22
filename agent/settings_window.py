"""Settings window — tkinter UI for editing AppConfig.

Opens from the tray 'Settings…' menu item. Runs in its own thread so
the tkinter mainloop doesn't interfere with pystray's event loop. On
Save, validates fields, writes config atomically, and invokes an
`on_save` callback so the tray can hot-reload the new config without
restart.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path

from agent.config import (
    AgentConfig,
    AppConfig,
    HeartbeatConfig,
    MtgoConfig,
    ServerConfig,
    UpdatesConfig,
    detect_mtgo_log_dir,
    get_config_path,
    save_config,
)


logger = logging.getLogger(__name__)


def auto_detect_mtgo_log_dir() -> Path | None:
    """Backwards-compatible alias — delegates to ``detect_mtgo_log_dir``."""
    return detect_mtgo_log_dir()


def normalize_server_url(value: str) -> str:
    value = value.strip()
    if not value:
        return value
    if value.startswith(("http://", "https://")):
        return value
    return f"https://{value}"


def _open_in_editor(path: Path) -> None:
    if not path.exists():
        logger.warning("Path does not exist: %s", path)
        return
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])  # noqa: S603,S607
    else:
        subprocess.Popen(["xdg-open", str(path)])  # noqa: S603,S607


class SettingsWindow:
    """Tkinter settings dialog, displayed in a dedicated thread."""

    def __init__(
        self,
        config: AppConfig,
        on_save: Callable[[], None],
    ) -> None:
        self._config = config
        self._on_save = on_save
        self._thread: threading.Thread | None = None

    def show(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run,
            name="manalog-settings",
            daemon=True,
        )
        self._thread.start()

    def _run(self) -> None:
        try:
            import tkinter as tk
            from tkinter import filedialog, messagebox, ttk
        except ImportError:
            logger.exception("tkinter unavailable — cannot open Settings window")
            return

        cfg = self._config

        root = tk.Tk()
        root.title("Manalog Settings")
        try:
            root.minsize(520, 0)
        except tk.TclError:
            pass

        url_var = tk.StringVar(value=cfg.server.url)
        tls_verify_default = (
            bool(cfg.server.tls_verify)
            if isinstance(cfg.server.tls_verify, bool)
            else True
        )
        tls_verify_var = tk.BooleanVar(value=tls_verify_default)
        machine_var = tk.StringVar(value=cfg.agent.machine_name)
        log_dir_var = tk.StringVar(value=cfg.mtgo.log_dir)
        interval_var = tk.IntVar(
            value=max(1, int(cfg.updates.check_interval_hours))
        )
        prerelease_var = tk.BooleanVar(value=bool(cfg.updates.include_prereleases))

        frame = ttk.Frame(root, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(1, weight=1)
        header_font = ("TkDefaultFont", 10, "bold")

        row = 0
        ttk.Label(frame, text="Server", font=header_font).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(0, 4)
        )
        row += 1
        ttk.Label(frame, text="Server hostname or URL:").grid(
            row=row, column=0, sticky="w", padx=(0, 8)
        )
        ttk.Entry(frame, textvariable=url_var).grid(
            row=row, column=1, columnspan=2, sticky="ew", pady=2
        )
        row += 1
        ttk.Checkbutton(
            frame, text="Verify TLS certificate", variable=tls_verify_var
        ).grid(row=row, column=1, columnspan=2, sticky="w", pady=2)
        row += 1
        ttk.Separator(frame).grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=8
        )
        row += 1

        ttk.Label(frame, text="Agent", font=header_font).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(0, 4)
        )
        row += 1
        ttk.Label(frame, text="Machine name:").grid(
            row=row, column=0, sticky="w", padx=(0, 8)
        )
        ttk.Entry(frame, textvariable=machine_var).grid(
            row=row, column=1, columnspan=2, sticky="ew", pady=2
        )
        row += 1
        ttk.Separator(frame).grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=8
        )
        row += 1

        ttk.Label(frame, text="MTGO", font=header_font).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(0, 4)
        )
        row += 1
        ttk.Label(frame, text="Log directory:").grid(
            row=row, column=0, sticky="w", padx=(0, 8)
        )
        ttk.Entry(frame, textvariable=log_dir_var).grid(
            row=row, column=1, sticky="ew", pady=2
        )

        def _browse() -> None:
            start_dir = log_dir_var.get() or str(Path.home())
            selected = filedialog.askdirectory(initialdir=start_dir, parent=root)
            if selected:
                log_dir_var.set(selected)

        ttk.Button(frame, text="Browse…", command=_browse).grid(
            row=row, column=2, sticky="e", padx=(4, 0)
        )
        row += 1

        def _auto_detect() -> None:
            if sys.platform != "win32":
                messagebox.showinfo(
                    "Auto-detect",
                    "Auto-detect is only available on Windows.",
                    parent=root,
                )
                return
            detected = auto_detect_mtgo_log_dir()
            if detected is None:
                messagebox.showinfo(
                    "Auto-detect",
                    "MTGO log directory not found. Please set it manually.",
                    parent=root,
                )
                return
            log_dir_var.set(str(detected))

        ttk.Button(frame, text="Auto-detect", command=_auto_detect).grid(
            row=row, column=1, sticky="w", pady=2
        )
        row += 1
        ttk.Separator(frame).grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=8
        )
        row += 1

        ttk.Label(frame, text="Updates", font=header_font).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(0, 4)
        )
        row += 1
        ttk.Label(frame, text="Check interval (hours):").grid(
            row=row, column=0, sticky="w", padx=(0, 8)
        )
        ttk.Spinbox(
            frame, from_=1, to=168, textvariable=interval_var, width=6
        ).grid(row=row, column=1, sticky="w", pady=2)
        row += 1
        ttk.Checkbutton(
            frame, text="Include pre-releases", variable=prerelease_var
        ).grid(row=row, column=1, columnspan=2, sticky="w", pady=2)
        row += 1
        ttk.Separator(frame).grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=12
        )
        row += 1

        def _save() -> None:
            try:
                interval = int(interval_var.get())
            except (ValueError, tk.TclError):
                messagebox.showerror(
                    "Invalid input",
                    "Check interval must be a positive integer.",
                    parent=root,
                )
                return
            if interval < 1:
                messagebox.showerror(
                    "Invalid input",
                    "Check interval must be at least 1 hour.",
                    parent=root,
                )
                return

            normalized_url = normalize_server_url(url_var.get())
            if not normalized_url:
                messagebox.showerror(
                    "Invalid input",
                    "Server URL is required.",
                    parent=root,
                )
                return

            new_config = AppConfig(
                server=ServerConfig(
                    url=normalized_url,
                    tls_verify=bool(tls_verify_var.get()),
                ),
                agent=AgentConfig(
                    agent_id=cfg.agent.agent_id,
                    api_token=cfg.agent.api_token,
                    machine_name=machine_var.get().strip(),
                ),
                mtgo=MtgoConfig(log_dir=log_dir_var.get().strip()),
                updates=UpdatesConfig(
                    check_interval_hours=interval,
                    include_prereleases=bool(prerelease_var.get()),
                    github_token=cfg.updates.github_token,
                ),
                heartbeat=HeartbeatConfig(
                    interval_seconds=cfg.heartbeat.interval_seconds,
                ),
            )
            try:
                save_config(new_config)
            except Exception as exc:
                logger.exception("Failed to save config")
                messagebox.showerror(
                    "Save failed",
                    f"Could not save config: {exc}",
                    parent=root,
                )
                return
            try:
                self._on_save()
            except Exception:
                logger.exception("on_save callback raised")
            root.destroy()

        def _cancel() -> None:
            root.destroy()

        def _open_raw() -> None:
            _open_in_editor(get_config_path())

        button_row = ttk.Frame(frame)
        button_row.grid(row=row, column=0, columnspan=3, sticky="ew")
        button_row.columnconfigure(0, weight=1)
        ttk.Button(
            button_row, text="Open config file", command=_open_raw
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(button_row, text="Cancel", command=_cancel).grid(
            row=0, column=1, sticky="e", padx=(0, 6)
        )
        ttk.Button(button_row, text="Save", command=_save).grid(
            row=0, column=2, sticky="e"
        )

        root.protocol("WM_DELETE_WINDOW", _cancel)
        try:
            root.mainloop()
        except Exception:
            logger.exception("Settings window mainloop raised")


__all__ = ["SettingsWindow", "auto_detect_mtgo_log_dir", "normalize_server_url"]
