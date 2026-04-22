"""Agent config load/save round-trip tests.

Uses tmp_path to keep all reads/writes out of the real user config dir.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agent.config import (
    AgentConfig,
    AppConfig,
    ConfigLoadError,
    DEFAULT_LOG_DIR_PLACEHOLDER,
    MtgoConfig,
    ServerConfig,
    UpdatesConfig,
    detect_mtgo_log_dir,
    load_config,
    load_config_or_error,
    log_dir_is_default,
    save_config,
)


def test_load_config_defaults(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.toml"
    cfg = load_config(missing)
    assert isinstance(cfg, AppConfig)
    assert cfg.server.url == "https://mtgo.int.sentania.net"
    assert cfg.server.tls_verify is True
    assert cfg.agent.agent_id == ""
    assert cfg.agent.api_token == ""
    assert cfg.mtgo.log_dir == ""
    assert cfg.updates.check_interval_hours == 1
    assert cfg.updates.include_prereleases is False


def test_save_and_reload(tmp_path: Path) -> None:
    cfg = AppConfig(
        server=ServerConfig(url="https://example.test", tls_verify=False),
        agent=AgentConfig(
            agent_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            api_token="secret-token",
            machine_name="laptop-01",
        ),
        mtgo=MtgoConfig(log_dir=r"C:\Users\scott\mtgo-logs"),
        updates=UpdatesConfig(
            check_interval_hours=6,
            include_prereleases=True,
            github_token="ghp_fake",
        ),
    )
    path = tmp_path / "config.toml"
    save_config(cfg, path)
    assert path.exists()

    reloaded = load_config(path)
    assert reloaded.server.url == cfg.server.url
    assert reloaded.server.tls_verify is False
    assert reloaded.agent.agent_id == cfg.agent.agent_id
    assert reloaded.agent.api_token == cfg.agent.api_token
    assert reloaded.agent.machine_name == cfg.agent.machine_name
    assert reloaded.mtgo.log_dir == cfg.mtgo.log_dir
    assert reloaded.updates.check_interval_hours == 6
    assert reloaded.updates.include_prereleases is True
    assert reloaded.updates.github_token == "ghp_fake"


def test_save_creates_parent_dirs(tmp_path: Path) -> None:
    nested = tmp_path / "nested" / "deeper" / "config.toml"
    save_config(AppConfig(), nested)
    assert nested.exists()


def test_tls_verify_as_path_string(tmp_path: Path) -> None:
    cfg = AppConfig(server=ServerConfig(tls_verify="/etc/ssl/internal-ca.pem"))
    path = tmp_path / "config.toml"
    save_config(cfg, path)
    reloaded = load_config(path)
    assert reloaded.server.tls_verify == "/etc/ssl/internal-ca.pem"


def test_load_config_or_error_returns_error_on_malformed_toml(
    tmp_path: Path,
) -> None:
    # \U is a TOML unicode escape — unterminated here, so it fails to parse.
    bad = tmp_path / "config.toml"
    bad.write_text('[mtgo]\nlog_dir = "C:\\Users\\scott"\n', encoding="utf-8")
    cfg, err = load_config_or_error(bad)
    assert isinstance(cfg, AppConfig)
    # Fields fall back to defaults so the tray can still start.
    assert cfg.mtgo.log_dir == ""
    assert isinstance(err, ConfigLoadError)


def test_load_config_or_error_ok_path(tmp_path: Path) -> None:
    good = tmp_path / "config.toml"
    save_config(AppConfig(agent=AgentConfig(machine_name="test")), good)
    cfg, err = load_config_or_error(good)
    assert err is None
    assert cfg.agent.machine_name == "test"


def test_log_dir_is_default() -> None:
    assert log_dir_is_default("") is True
    assert log_dir_is_default("   ") is True
    assert log_dir_is_default(DEFAULT_LOG_DIR_PLACEHOLDER) is True
    assert log_dir_is_default(r"C:\some\real\dir") is False


def test_detect_mtgo_log_dir_non_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agent.config.sys.platform", "linux")
    assert detect_mtgo_log_dir() is None


def test_detect_mtgo_log_dir_finds_dat_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("agent.config.sys.platform", "win32")
    local = tmp_path / "Local"
    target = local / "Apps" / "2.0" / "abc" / "def" / "mtgo_tld"
    target.mkdir(parents=True)
    (target / "Match_GameLog_1234.dat").write_bytes(b"x")
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    detected = detect_mtgo_log_dir()
    assert detected == target


def test_detect_mtgo_log_dir_missing_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("agent.config.sys.platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "nowhere"))
    assert detect_mtgo_log_dir() is None


def test_detect_mtgo_log_dir_caps_dirs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("agent.config.sys.platform", "win32")
    local = tmp_path / "Local"
    root = local / "Apps" / "2.0"
    root.mkdir(parents=True)
    # Create many siblings with no .dat file — detection should bail via the cap.
    for i in range(20):
        (root / f"d{i}").mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    assert detect_mtgo_log_dir(max_dirs=5) is None
