"""Agent entry point.

Loads config, prompts for registration on first run (Windows only —
tkinter dialog), wires up the sender and tray, and hands control to
pystray's event loop.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import socket
import ssl
import sys
from pathlib import Path

import httpx

from agent.config import AppConfig, get_config_path, load_config, save_config
from agent.instance_lock import InstanceLock
from agent.raw_shipper import RawShipper
from agent.sender import AgentSender
from agent.tray import TrayApp


logger = logging.getLogger(__name__)


DEFAULT_SERVER_HOSTNAME = "manalog.sentania.net"


def _strip_scheme(url: str) -> str:
    for prefix in ("https://", "http://"):
        if url.startswith(prefix):
            return url[len(prefix):]
    return url


def _normalize_server_url(value: str) -> str:
    value = value.strip()
    if not value:
        return value
    if value.startswith(("http://", "https://")):
        return value
    return f"https://{value}"


def _is_ssl_error(exc: BaseException) -> bool:
    cur: BaseException | None = exc
    seen: set[int] = set()
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, ssl.SSLError):
            return True
        cur = cur.__cause__ or cur.__context__
    return False


def _friendly_registration_error(exc: BaseException) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 401:
            return "Invalid username or password."
        if code == 403:
            return "Account not authorized. Contact the server administrator."
        if code == 404:
            return "Registration endpoint not found. Check the server URL."
        if 500 <= code < 600:
            return f"Server error (HTTP {code}). Try again later."
        return f"Registration failed: HTTP {code}."
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        if _is_ssl_error(exc):
            return (
                "TLS/SSL error connecting to server. "
                "If using a self-signed cert, ask your administrator."
            )
        return (
            "Cannot reach server. "
            "Check the hostname and your network connection."
        )
    if _is_ssl_error(exc):
        return (
            "TLS/SSL error connecting to server. "
            "If using a self-signed cert, ask your administrator."
        )
    detail = str(exc).splitlines()[0].strip() if str(exc) else ""
    short = f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__
    return f"Registration failed: {short}."


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
        initial_host = _strip_scheme(config.server.url).strip()
        if not initial_host or initial_host == "mtgo.int.sentania.net":
            initial_host = DEFAULT_SERVER_HOSTNAME
        server_host = simpledialog.askstring(
            "Manalog",
            "Server hostname:",
            initialvalue=initial_host,
            parent=root,
        )
        if not server_host:
            return config
        server_url = _normalize_server_url(server_host)
        if not server_url:
            return config
        username = simpledialog.askstring(
            "Manalog", "Username:", parent=root
        )
        if not username:
            return config
        password = simpledialog.askstring(
            "Manalog", "Password:", show="*", parent=root
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
            messagebox.showerror(
                "Registration failed",
                _friendly_registration_error(exc),
                parent=root,
            )
            return config

        config.agent.agent_id = str(agent_id)
        config.agent.api_token = api_token
        save_config(config)
        messagebox.showinfo(
            "Manalog",
            f"Registered as agent {agent_id}",
            parent=root,
        )
        return config
    finally:
        root.destroy()


def main() -> None:
    parser = argparse.ArgumentParser(description="Manalog agent")
    parser.add_argument(
        "--service",
        action="store_true",
        help="Run as Windows service (headless)",
    )
    args, _ = parser.parse_known_args()

    if args.service:
        from agent.service import run_service
        run_service()
        return

    log_file = _default_log_file()
    _configure_logging(log_file)
    logger.info("Starting Manalog agent")

    instance_lock = InstanceLock()
    if not instance_lock.acquire():
        logger.info("Another Manalog instance is already running — exiting.")
        sys.exit(0)

    config = load_config()
    if _needs_registration(config):
        config = _prompt_registration(config)

    sender = AgentSender(config)
    watched_dir = Path(config.mtgo.log_dir) if config.mtgo.log_dir else None
    raw_shipper = RawShipper(config, watched_dir=watched_dir)
    raw_shipper.start()
    app = TrayApp(config, sender, log_file=log_file)
    try:
        app.run()
    finally:
        try:
            raw_shipper.stop()
        except Exception:
            logger.exception("Error stopping raw_shipper")
        try:
            asyncio.run(sender.close())
        except Exception:
            logger.exception("Error closing sender")
        instance_lock.release()


if __name__ == "__main__":
    main()
