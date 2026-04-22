"""Smoke tests for agent/service.py — pywin32 stubbed for CI."""
import sys
import types


def _stub_win32(monkeypatch):
    """Inject minimal pywin32 stubs so service.py can be imported on non-Windows."""
    if sys.platform == "win32":
        return

    for mod_name in ("win32serviceutil", "win32service", "win32event", "servicemanager"):
        stub = types.ModuleType(mod_name)
        if mod_name == "win32serviceutil":
            class _ServiceFramework:
                def __init__(self, args): pass
                def ReportServiceStatus(self, code): pass
                @staticmethod
                def HandleCommandLine(cls): pass
            stub.ServiceFramework = _ServiceFramework
            stub.HandleCommandLine = _ServiceFramework.HandleCommandLine
        if mod_name == "win32service":
            stub.SERVICE_STOP_PENDING = 3
        if mod_name == "win32event":
            stub.CreateEvent = lambda *a: None
            stub.SetEvent = lambda e: None
            stub.WaitForSingleObject = lambda e, t: 258  # WAIT_TIMEOUT
        if mod_name == "servicemanager":
            stub.EVENTLOG_INFORMATION_TYPE = 4
            stub.PYS_SERVICE_STARTED = 0
            stub.LogMsg = lambda *a: None
        monkeypatch.setitem(sys.modules, mod_name, stub)


def test_import(monkeypatch):
    """service.py is importable and exports expected names."""
    _stub_win32(monkeypatch)
    sys.modules.pop("agent.service", None)
    from agent.service import ManalogAgentService, run_service
    assert ManalogAgentService._svc_name_ == "ManalogAgent"
    assert ManalogAgentService._svc_display_name_ == "Manalog Agent"
    assert callable(run_service)


def test_service_class_instantiation(monkeypatch):
    """ManalogAgentService can be instantiated with stub args."""
    _stub_win32(monkeypatch)
    sys.modules.pop("agent.service", None)
    from agent.service import ManalogAgentService
    svc = ManalogAgentService.__new__(ManalogAgentService)
    ManalogAgentService.__init__(svc, [])
    assert hasattr(svc, "_running")


def test_svc_stop_sets_running_false(monkeypatch):
    """SvcStop sets _running=False."""
    _stub_win32(monkeypatch)
    sys.modules.pop("agent.service", None)
    from agent.service import ManalogAgentService
    svc = ManalogAgentService.__new__(ManalogAgentService)
    ManalogAgentService.__init__(svc, [])
    svc._running = True
    svc.SvcStop()
    assert svc._running is False
