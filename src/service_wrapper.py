"""Windows Service wrapper for HomeGuard DNS proxy."""

import os
import sys
import threading
import time

# pywin32 imports
import win32service
import win32serviceutil
import win32event
import servicemanager

# Adjust path so we can import our own modules when run as a service
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BASE_DIR not in sys.path:
    sys.path.insert(0, _BASE_DIR)

from src.config import Config
from src.blocklist import Blocklist
from src.alert import AlertEngine
from src.guardian import DNSProxy


class HomeGuardService(win32serviceutil.ServiceFramework):
    """NT Service that runs the DNS proxy in the background."""

    _svc_name_ = "HomeGuardDNS"
    _svc_display_name_ = "HomeGuard DNS Proxy"
    _svc_description_ = (
        "Local DNS resolver for parental control. "
        "Blocks adult/gambling domains and alerts parents via email."
    )

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.proxy: DNSProxy | None = None
        self.proxy_thread: threading.Thread | None = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_event)
        if self.proxy:
            self.proxy.stop()
        if self.proxy_thread and self.proxy_thread.is_alive():
            self.proxy_thread.join(timeout=5)
        self.ReportServiceStatus(win32service.SERVICE_STOPPED)

    def SvcDoRun(self):
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )
        self.ReportServiceStatus(win32service.SERVICE_RUNNING)
        self._run_proxy()
        win32event.WaitForSingleObject(self.stop_event, win32event.INFINITE)

    def _run_proxy(self) -> None:
        try:
            config = Config.from_ini()
            blocklist = Blocklist(
                urls=config.blocklist_urls,
                cache_file=config.cache_file,
                refresh_days=config.refresh_days,
            )
            alert_engine = AlertEngine(
                db_path=os.path.join(_BASE_DIR, "logs", "homeguard.db"),
                smtp_config=config.smtp_config,
                child_name=config.child_name,
                rate_limit_minutes=config.rate_limit_minutes,
            )
            self.proxy = DNSProxy(config, blocklist, alert_engine)
            self.proxy_thread = threading.Thread(
                target=self.proxy.serve_forever, daemon=True
            )
            self.proxy_thread.start()
        except Exception as exc:
            servicemanager.LogErrorMsg(f"HomeGuard failed to start: {exc}")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        # Called by SCM directly
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(HomeGuardService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(HomeGuardService)
