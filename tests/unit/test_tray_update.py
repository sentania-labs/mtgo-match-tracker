"""TrayApp self-update wiring tests.

Mocks out check_for_update, download_and_verify, and apply_update so no
network or subprocess calls run. Tests focus on the staged-update state
machine and menu/notification side effects.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from agent.config import AppConfig
from agent.tray import TrayApp


async def _none() -> None:
    return None


def _tray() -> TrayApp:
    sender = MagicMock()
    app = TrayApp(config=AppConfig(), sender=sender)
    app._icon = MagicMock()
    return app


def test_check_updates_stages_after_successful_download(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = _tray()
    staged_exe = tmp_path / "MTGOMatchTracker_update.exe"
    staged_exe.write_bytes(b"new")

    async def _check(cfg: AppConfig) -> tuple[str, str]:
        return ("v1.2.3", "https://example/exe")

    async def _download(url: str, token: str | None) -> Path:
        return staged_exe

    monkeypatch.setattr("agent.tray.check_for_update", _check)
    monkeypatch.setattr("agent.tray.download_and_verify", _download)

    app._check_updates_once()

    assert app._staged_update == staged_exe
    assert app._staged_update_tag == "v1.2.3"
    assert app._has_staged_update() is True
    app._icon.update_menu.assert_called()
    # Notify fires via icon.notify (the _notify helper path).
    app._icon.notify.assert_called()
    msg = app._icon.notify.call_args[0][0]
    assert "downloaded" in msg
    assert "v1.2.3" in msg


def test_check_updates_no_release_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _tray()

    async def _check(cfg: AppConfig) -> None:
        return None

    called = {"download": 0}

    async def _download(url: str, token: str | None) -> Path | None:
        called["download"] += 1
        return None

    monkeypatch.setattr("agent.tray.check_for_update", _check)
    monkeypatch.setattr("agent.tray.download_and_verify", _download)

    app._check_updates_once()

    assert app._staged_update is None
    assert app._staged_update_tag is None
    assert called["download"] == 0
    app._icon.notify.assert_not_called()


def test_check_updates_download_failure_notifies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _tray()

    async def _check(cfg: AppConfig) -> tuple[str, str]:
        return ("v2.0.0", "https://example/exe")

    async def _download(url: str, token: str | None) -> None:
        return None  # simulates network error OR checksum mismatch

    monkeypatch.setattr("agent.tray.check_for_update", _check)
    monkeypatch.setattr("agent.tray.download_and_verify", _download)

    app._check_updates_once()

    assert app._staged_update is None
    assert app._staged_update_tag is None
    app._icon.notify.assert_called_once()
    msg = app._icon.notify.call_args[0][0]
    assert "download failed" in msg
    assert "v2.0.0" in msg


def test_check_updates_download_exception_notifies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _tray()

    async def _check(cfg: AppConfig) -> tuple[str, str]:
        return ("v2.0.1", "https://example/exe")

    async def _download(url: str, token: str | None) -> Path:
        raise RuntimeError("boom")

    monkeypatch.setattr("agent.tray.check_for_update", _check)
    monkeypatch.setattr("agent.tray.download_and_verify", _download)

    app._check_updates_once()

    assert app._staged_update is None
    app._icon.notify.assert_called_once()
    assert "download failed" in app._icon.notify.call_args[0][0]


def test_check_updates_skips_redownload_for_same_tag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = _tray()
    staged_exe = tmp_path / "staged.exe"
    staged_exe.write_bytes(b"x")
    app._staged_update = staged_exe
    app._staged_update_tag = "v3.0.0"

    async def _check(cfg: AppConfig) -> tuple[str, str]:
        return ("v3.0.0", "https://example/exe")

    download_calls = {"n": 0}

    async def _download(url: str, token: str | None) -> Path:
        download_calls["n"] += 1
        return staged_exe

    monkeypatch.setattr("agent.tray.check_for_update", _check)
    monkeypatch.setattr("agent.tray.download_and_verify", _download)

    app._check_updates_once()

    assert download_calls["n"] == 0
    app._icon.notify.assert_not_called()


def test_on_restart_to_update_applies_and_clears(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = _tray()
    staged = tmp_path / "update.exe"
    staged.write_bytes(b"z")
    app._staged_update = staged
    app._staged_update_tag = "v1.1.1"

    called: dict[str, Any] = {}

    def _apply(path: Path) -> None:
        called["path"] = path

    monkeypatch.setattr("agent.tray.apply_update", _apply)

    app._on_restart_to_update(icon=MagicMock(), item=MagicMock())

    assert called["path"] == staged
    assert app._staged_update is None
    assert app._staged_update_tag is None


def test_on_restart_to_update_noop_without_staged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _tray()
    called = {"n": 0}

    def _apply(path: Path) -> None:
        called["n"] += 1

    monkeypatch.setattr("agent.tray.apply_update", _apply)

    app._on_restart_to_update(icon=MagicMock(), item=MagicMock())

    assert called["n"] == 0
    assert app._staged_update is None


def test_on_restart_propagates_systemexit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = _tray()
    staged = tmp_path / "update.exe"
    staged.write_bytes(b"z")
    app._staged_update = staged
    app._staged_update_tag = "v9.9.9"

    def _apply(path: Path) -> None:
        raise SystemExit(0)

    monkeypatch.setattr("agent.tray.apply_update", _apply)

    with pytest.raises(SystemExit):
        app._on_restart_to_update(icon=MagicMock(), item=MagicMock())

    # Staged state not cleared when apply_update takes over the process.
    assert app._staged_update == staged


def test_manual_check_for_updates_runs_in_background(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _tray()
    invocations = {"n": 0}

    def _fake_check_once() -> None:
        invocations["n"] += 1

    monkeypatch.setattr(app, "_check_updates_once", _fake_check_once)

    app._on_check_updates(icon=MagicMock(), item=MagicMock())

    # _on_check_updates spawns a thread — wait for it.
    # Find it by name pattern — it's the most recently started daemon
    # since test start; a small join covers it.
    import threading as _threading
    for t in _threading.enumerate():
        if t is _threading.main_thread() or not t.is_alive():
            continue
        if t.daemon:
            t.join(timeout=1.0)

    assert invocations["n"] >= 1


def test_restart_menu_item_visible_only_when_staged(
    tmp_path: Path,
) -> None:
    app = _tray()
    assert app._has_staged_update() is False
    app._staged_update = tmp_path / "update.exe"
    assert app._has_staged_update() is True
