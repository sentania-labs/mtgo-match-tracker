"""Agent entry point.

Loads config, prompts for registration on first run (Windows only —
tkinter dialog), wires up the sender and tray, and hands control to
pystray's event loop.
"""
from __future__ import annotations

import asyncio
import logging
import socket
import sys
from pathlib import Path

from agent.config import AppConfig, get_config_path, load_config, save_config
from agent.sender import AgentSender
from agent.tray import TrayApp


logger = logging.getLogger(__name__)


def _configure_logging(log_file: Path) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def _default_log_file() -> Path:
    return get_config_path().parent / "agent.log"


def _needs_registration(config: AppConfig) -> bool:
    return not config.agent.agent_id or not config.agent.api_token


def _prompt_registration(config: AppConfig) -> AppConfig:
    if sys.platform != "win32":
        logger.warning(
            "Registration dialog skipped on non-Windows platform; "
            "populate agent_id/api_token in config.toml manually."
        )
        return config

    try:
        import tkinter as tk
        from tkinter import messagebox, simpledialog
    except ImportError:
        logger.exception("tkinter unavailable — cannot show registration dialog")
        return config

    root = tk.Tk()
    root.withdraw()
    try:
        server_url = simpledialog.askstring(
            "MTGO Match Tracker",
            "Server URL:",
            initialvalue=config.server.url,
            parent=root,
        )
        if not server_url:
            return config
        username = simpledialog.askstring(
            "MTGO Match Tracker", "Username:", parent=root
        )
        if not username:
            return config
        password = simpledialog.askstring(
            "MTGO Match Tracker", "Password:", show="*", parent=root
        )
        if password is None:
            return config
        machine_name = config.agent.machine_name or socket.gethostname()

        config.server.url = server_url
        config.agent.machine_name = machine_name

        async def _register_once() -> tuple[str, str]:
            sender = AgentSender(config)
            try:
                return await sender.register(
                    username, password, machine_name, platform="windows"
                )
            finally:
                await sender.close()

        try:
            agent_id, api_token = asyncio.run(_register_once())
        except Exception as exc:
            logger.exception("Registration failed")
            messagebox.showerror("Registration failed", str(exc), parent=root)
            return config

        config.agent.agent_id = str(agent_id)
        config.agent.api_token = api_token
        save_config(config)
        messagebox.showinfo(
            "MTGO Match Tracker",
            f"Registered as agent {agent_id}",
            parent=root,
        )
        return config
    finally:
        root.destroy()


def main() -> None:
    log_file = _default_log_file()
    _configure_logging(log_file)
    logger.info("Starting MTGO Match Tracker agent")

    config = load_config()
    if _needs_registration(config):
        config = _prompt_registration(config)

    sender = AgentSender(config)
    app = TrayApp(config, sender, log_file=log_file)
    try:
        app.run()
    finally:
        try:
            asyncio.run(sender.close())
        except Exception:
            logger.exception("Error closing sender")


if __name__ == "__main__":
    main()
