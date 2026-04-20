"""Windows Service wrapper for the Manalog agent.

Runs the watchdog + sender loop headlessly (no pystray, no tkinter) under
the Windows Service Control Manager, so the agent can auto-start at boot
without requiring an interactive login session.

The pywin32 imports are guarded so this module stays importable on
non-Windows (for CI/testing). Invoking the service runtime on a
non-Windows host raises RuntimeError.
"""
from __future__ import annotations

import sys


if sys.platform == "win32":
    import win32serviceutil
    import win32service
    import win32event
    import servicemanager
    HAS_WIN32 = True
else:
    win32serviceutil = None  # type: ignore[assignment]
    HAS_WIN32 = False


class ManalogAgentService(win32serviceutil.ServiceFramework if HAS_WIN32 else object):
    _svc_name_ = "ManalogAgent"
    _svc_display_name_ = "Manalog Agent"
    _svc_description_ = "Manalog MTGO match tracker agent (headless, no tray)"

    def __init__(self, args):
        if HAS_WIN32:
            win32serviceutil.ServiceFramework.__init__(self, args)
            self._stop_event = win32event.CreateEvent(None, 0, 0, None)
        self._running = False

    def SvcStop(self):
        if HAS_WIN32:
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            win32event.SetEvent(self._stop_event)
        self._running = False

    def SvcDoRun(self):
        if HAS_WIN32:
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, ""),
            )
        self._running = True
        self._run_headless()

    def _run_headless(self):
        """Run the watchdog + sender loop without tray/GUI."""
        import asyncio
        from agent.config import load_config
        from agent.sender import AgentSender
        from agent.watcher import MTGOWatcher

        config = load_config()
        client = AgentSender(config)

        def on_match(match):
            asyncio.run(client.upload(match))

        log_dir = None
        if config.mtgo.log_dir:
            from pathlib import Path
            log_dir = Path(config.mtgo.log_dir)

        if log_dir and log_dir.exists():
            watcher = MTGOWatcher(log_dir, on_match)
            watcher.start()
            try:
                while self._running:
                    if HAS_WIN32:
                        import win32event as _we
                        result = _we.WaitForSingleObject(self._stop_event, 5000)
                        if result == 0:  # WAIT_OBJECT_0
                            break
                    else:
                        import time
                        time.sleep(5)
                        if not self._running:
                            break
            finally:
                watcher.stop()
        else:
            import logging
            logging.getLogger(__name__).warning(
                "ManalogAgent service: no MTGO log_dir configured or dir missing; watcher idle"
            )
            while self._running:
                if HAS_WIN32:
                    import win32event as _we
                    result = _we.WaitForSingleObject(self._stop_event, 30000)
                    if result == 0:
                        break
                else:
                    import time
                    time.sleep(30)


def run_service():
    """Entry point when invoked as a Windows service."""
    if not HAS_WIN32:
        raise RuntimeError("Windows service mode requires pywin32 (Windows only)")
    win32serviceutil.HandleCommandLine(ManalogAgentService)


__all__ = ["ManalogAgentService", "HAS_WIN32", "run_service"]
