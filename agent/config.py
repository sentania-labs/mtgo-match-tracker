"""Agent config — load/save to a platform-appropriate location.

On Windows: %APPDATA%\\Manalog\\config.toml
On other platforms (dev/CI): ~/.config/manalog/config.toml

Writes are atomic (.tmp then rename). Never store user passwords — only
the api_token issued by the server at registration time.
"""
from __future__ import annotations

import fnmatch
import logging
import os
import sys
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path


logger = logging.getLogger(__name__)

CONFIG_FILENAME = "config.toml"
APP_DIR_NAME_WIN = "Manalog"
APP_DIR_NAME_POSIX = "manalog"

DEFAULT_LOG_DIR_PLACEHOLDER = (
    "C:\\Users\\<user>\\AppData\\Local\\Apps\\2.0\\<mtgo>\\GamingAudioInterop"
)

MTGO_DETECT_MAX_DEPTH = 8
MTGO_DETECT_MAX_DIRS = 500
MTGO_LOG_PATTERN = "Match_GameLog_*.dat"


@dataclass
class ServerConfig:
    url: str = "https://mtgo.int.sentania.net"
    tls_verify: bool | str = True


@dataclass
class AgentConfig:
    agent_id: str = ""
    api_token: str = ""
    machine_name: str = ""


@dataclass
class MtgoConfig:
    log_dir: str = ""


@dataclass
class UpdatesConfig:
    check_interval_hours: int = 1
    include_prereleases: bool = False
    github_token: str = ""


@dataclass
class HeartbeatConfig:
    interval_seconds: int = 60


@dataclass
class AppConfig:
    server: ServerConfig = field(default_factory=ServerConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    mtgo: MtgoConfig = field(default_factory=MtgoConfig)
    updates: UpdatesConfig = field(default_factory=UpdatesConfig)
    heartbeat: HeartbeatConfig = field(default_factory=HeartbeatConfig)


def _config_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / APP_DIR_NAME_WIN
        return Path.home() / "AppData" / "Roaming" / APP_DIR_NAME_WIN
    override = os.environ.get("MTGO_AGENT_CONFIG_DIR")
    if override:
        return Path(override)
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / APP_DIR_NAME_POSIX


def get_config_path() -> Path:
    return _config_dir() / CONFIG_FILENAME


def get_log_dir() -> Path:
    cfg = load_config()
    if cfg.mtgo.log_dir:
        return Path(cfg.mtgo.log_dir)
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", "")) / "Apps" / "2.0"
    return _config_dir() / "mtgo-logs"


def detect_mtgo_log_dir(
    *,
    max_depth: int = MTGO_DETECT_MAX_DEPTH,
    max_dirs: int = MTGO_DETECT_MAX_DIRS,
) -> Path | None:
    """Find the MTGO log directory under %LOCALAPPDATA%\\Apps\\2.0.

    Walks the tree looking for ``Match_GameLog_*.dat`` and returns the
    parent directory of the first match. Windows-only; returns None on
    other platforms or if no match is found. Caps depth and total
    directories scanned to avoid hanging on large AppData trees, and
    skips any directory it can't read.
    """
    if sys.platform != "win32":
        return None
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if not local_appdata:
        return None
    root = Path(local_appdata) / "Apps" / "2.0"
    if not root.exists():
        return None

    dirs_scanned = 0
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        current, depth = stack.pop()
        if depth > max_depth:
            continue
        dirs_scanned += 1
        if dirs_scanned > max_dirs:
            return None
        try:
            entries = list(current.iterdir())
        except (PermissionError, OSError):
            continue
        subdirs: list[Path] = []
        for entry in entries:
            try:
                if entry.is_file():
                    if fnmatch.fnmatch(entry.name, MTGO_LOG_PATTERN):
                        return current
                elif entry.is_dir():
                    subdirs.append(entry)
            except OSError:
                continue
        for sub in reversed(subdirs):
            stack.append((sub, depth + 1))
    return None


def log_dir_is_default(log_dir: str) -> bool:
    """True if the configured log_dir is empty or the placeholder value."""
    stripped = log_dir.strip()
    return not stripped or stripped == DEFAULT_LOG_DIR_PLACEHOLDER


def _parse_toml(path: Path) -> AppConfig:
    with path.open("rb") as fh:
        data = tomllib.load(fh)

    server_raw = data.get("server", {}) or {}
    tls_verify_raw = server_raw.get("tls_verify", True)
    if isinstance(tls_verify_raw, str) and tls_verify_raw.lower() in {"true", "false"}:
        tls_verify: bool | str = tls_verify_raw.lower() == "true"
    else:
        tls_verify = tls_verify_raw

    agent_raw = data.get("agent", {}) or {}
    mtgo_raw = data.get("mtgo", {}) or {}
    updates_raw = data.get("updates", {}) or {}
    heartbeat_raw = data.get("heartbeat", {}) or {}

    return AppConfig(
        server=ServerConfig(
            url=server_raw.get("url", ServerConfig.url),
            tls_verify=tls_verify,
        ),
        agent=AgentConfig(
            agent_id=agent_raw.get("agent_id", ""),
            api_token=agent_raw.get("api_token", ""),
            machine_name=agent_raw.get("machine_name", ""),
        ),
        mtgo=MtgoConfig(log_dir=mtgo_raw.get("log_dir", "")),
        updates=UpdatesConfig(
            check_interval_hours=int(updates_raw.get("check_interval_hours", 1)),
            include_prereleases=bool(updates_raw.get("include_prereleases", False)),
            github_token=updates_raw.get("github_token", ""),
        ),
        heartbeat=HeartbeatConfig(
            interval_seconds=int(heartbeat_raw.get("interval_seconds", 60)),
        ),
    )


def load_config(path: Path | None = None) -> AppConfig:
    cfg_path = path or get_config_path()
    if not cfg_path.exists():
        return AppConfig()
    return _parse_toml(cfg_path)


class ConfigLoadError(Exception):
    """Raised when config.toml exists but cannot be parsed."""

    def __init__(self, message: str, line: int | None = None) -> None:
        super().__init__(message)
        self.line = line


def load_config_or_error(
    path: Path | None = None,
) -> tuple[AppConfig, ConfigLoadError | None]:
    """Load config, returning defaults + an error on parse failure.

    Lets the caller continue with a usable default config while
    surfacing the underlying TOML/IO problem for display to the user.
    """
    cfg_path = path or get_config_path()
    if not cfg_path.exists():
        return AppConfig(), None
    try:
        return _parse_toml(cfg_path), None
    except tomllib.TOMLDecodeError as exc:
        line = getattr(exc, "lineno", None)
        msg = str(exc)
        logger.error("config: failed to parse %s: %s", cfg_path, msg)
        return AppConfig(), ConfigLoadError(msg, line=line)
    except OSError as exc:
        logger.error("config: failed to read %s: %s", cfg_path, exc)
        return AppConfig(), ConfigLoadError(str(exc))
    except Exception as exc:
        logger.exception("config: unexpected error parsing %s", cfg_path)
        return AppConfig(), ConfigLoadError(str(exc))


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _serialize(config: AppConfig) -> str:
    tls_verify = config.server.tls_verify
    if isinstance(tls_verify, bool):
        tls_verify_str = "true" if tls_verify else "false"
    else:
        tls_verify_str = f'"{_toml_escape(str(tls_verify))}"'

    lines = [
        "[server]",
        f'url = "{_toml_escape(config.server.url)}"',
        f"tls_verify = {tls_verify_str}",
        "",
        "[agent]",
        f'agent_id = "{_toml_escape(config.agent.agent_id)}"',
        f'api_token = "{_toml_escape(config.agent.api_token)}"',
        f'machine_name = "{_toml_escape(config.agent.machine_name)}"',
        "",
        "[mtgo]",
        "# Windows paths: use single quotes or double backslashes to avoid TOML escape errors",
        "# Good:  log_dir = 'C:\\Users\\YourName\\AppData\\Local\\Apps\\2.0\\mtgo...'",
        '# Good:  log_dir = "C:\\\\Users\\\\YourName\\\\AppData\\\\Local\\\\Apps\\\\2.0\\\\mtgo..."',
        '# Bad:   log_dir = "C:\\Users\\..."  # \\U is a TOML unicode escape!',
        f'log_dir = "{_toml_escape(config.mtgo.log_dir)}"',
        "",
        "[updates]",
        f"check_interval_hours = {int(config.updates.check_interval_hours)}",
        f"include_prereleases = {'true' if config.updates.include_prereleases else 'false'}",
        f'github_token = "{_toml_escape(config.updates.github_token)}"',
        "",
        "[heartbeat]",
        f"interval_seconds = {int(config.heartbeat.interval_seconds)}",
        "",
    ]
    return "\n".join(lines)


def save_config(config: AppConfig, path: Path | None = None) -> None:
    cfg_path = path or get_config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = cfg_path.with_suffix(cfg_path.suffix + ".tmp")
    tmp_path.write_text(_serialize(config), encoding="utf-8")
    os.replace(tmp_path, cfg_path)


def config_as_dict(config: AppConfig) -> dict:
    return asdict(config)
