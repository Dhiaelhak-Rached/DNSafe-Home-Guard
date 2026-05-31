#!/usr/bin/env python
"""HomeGuard dev-mode launcher.

No build. No install. Fast iteration.

Examples
--------
    # Proxy + tray on auto-picked port (53535 if no admin)
    python dev.py

    # Full system interception on port 53 (requires admin, restores DNS on exit)
    python dev.py --admin

    # Headless proxy only
    python dev.py --no-tray

    # Disable email rate-limiting for testing
    python dev.py --rate-limit 0
"""

import argparse
import atexit
import ctypes
import os
import socket
import subprocess
import sys
import threading
import time

# Ensure we run from the project root so relative paths work
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(_PROJECT_ROOT)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.config import Config
from src.guardian import main as guardian_main
from src.logger import ensure_file_logging
from src.dns_utils import (
    get_active_adapters,
    backup_dns,
    set_dns_to_localhost,
    restore_dns_from_backup,
    flush_dns_cache,
)

# --------------------------------------------------------------------------- #
# DNS helpers (now using shared dns_utils module)
# --------------------------------------------------------------------------- #
_DNS_BACKUP: dict = {}


def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def relaunch_as_admin() -> None:
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, " ".join(sys.argv), None, 1
    )
    sys.exit(0)


def dev_backup_dns() -> dict:
    """Backup DNS and store in _DNS_BACKUP for restore on exit."""
    backup = backup_dns("dev_dns_backup.json")
    _DNS_BACKUP.clear()
    _DNS_BACKUP.update(backup)
    return backup


def dev_set_dns_localhost() -> None:
    """Set DNS to localhost using shared module."""
    set_dns_to_localhost()


def dev_restore_dns() -> None:
    """Restore DNS from _DNS_BACKUP."""
    if not _DNS_BACKUP:
        return
    print("[Dev] Restoring original DNS settings...")
    # Create a temporary backup file for the shared module
    import json
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(_DNS_BACKUP, f)
        temp_path = f.name
    try:
        restore_dns_from_backup(temp_path)
    finally:
        os.unlink(temp_path)
    print("[Dev] DNS restored.")


# --------------------------------------------------------------------------- #
# Port & config helpers
# --------------------------------------------------------------------------- #
def pick_port(preferred: int = 53, fallback: int = 53535) -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(("127.0.0.1", preferred))
        sock.close()
        return preferred
    except (PermissionError, OSError) as exc:
        sock.close()
        print(f"[Dev] Port {preferred} unavailable ({exc}). Using {fallback}.")
        return fallback


def patch_config(dev_port: int, dev_rate_limit: int) -> None:
    """Monkey-patch Config.from_ini so every caller sees the dev port."""
    _original_from_ini = Config.from_ini

    def _patched_from_ini(path=None):
        cfg = _original_from_ini(path)
        cfg.listen_port = dev_port
        cfg.rate_limit_minutes = dev_rate_limit
        return cfg

    Config.from_ini = staticmethod(_patched_from_ini)


# --------------------------------------------------------------------------- #
# Run modes
# --------------------------------------------------------------------------- #
def run_headless_mode() -> None:
    """Proxy only — uses guardian.py main()."""
    print("[Dev] Starting headless DNS proxy (Ctrl+C to stop)...\n")
    guardian_main()


def run_tray_mode() -> None:
    """Proxy + system tray. Tray runs in thread so main thread catches Ctrl+C."""
    from src.tray_gui import TrayApp

    app = TrayApp()

    # Wire up a stop signal so Ctrl+C can shut us down cleanly
    stop_event = threading.Event()
    tray_error = None
    original_on_exit = app._on_exit

    def _on_exit_patched(icon):
        stop_event.set()
        original_on_exit(icon)

    app._on_exit = _on_exit_patched

    def _run_tray() -> None:
        nonlocal tray_error
        try:
            app.run()
        except Exception as exc:
            tray_error = exc
            stop_event.set()

    tray_thread = threading.Thread(target=_run_tray, daemon=True)
    tray_thread.start()

    # Give pystray a moment to start up
    time.sleep(1)

    if tray_error:
        print(f"\n[Dev] Tray crashed during startup: {tray_error}")
        raise tray_error

    if not tray_thread.is_alive():
        print("\n[Dev] Tray thread died immediately.")
        return

    print("[Dev] Tray started. Press Ctrl+C to stop.\n")
    try:
        while not stop_event.is_set():
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[Dev] Ctrl+C detected. Shutting down...")
    finally:
        if app.icon:
            app._on_exit(app.icon)
        tray_thread.join(timeout=3)
        print("[Dev] Stopped.")


# --------------------------------------------------------------------------- #
# Banner
# --------------------------------------------------------------------------- #
def print_banner(port: int, admin: bool) -> None:
    print("=" * 60)
    print("  HomeGuard  —  DEV MODE")
    print("=" * 60)
    print(f"  DNS Proxy:    127.0.0.1:{port}")
    print(f"  System DNS:   {'REDIRECTED → localhost' if admin else 'UNCHANGED'}")
    print(
        f"  Mode:         {'Full interception (admin)' if admin else 'Dev port (no admin)'}"
    )
    print("=" * 60)
    if not admin:
        print()
        print("  Quick test commands:")
        print(f"    nslookup -port={port} pornhub.com 127.0.0.1")
        print(f"    nslookup -port={port} google.com 127.0.0.1")
        print()
        print("  To test full OS interception:")
        print("    python dev.py --admin")
    print("=" * 60)
    print()


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def main():
    parser = argparse.ArgumentParser(description="HomeGuard dev launcher")
    parser.add_argument(
        "--admin",
        action="store_true",
        help="Use port 53 and intercept system DNS (requires admin; auto-restores on exit)",
    )
    parser.add_argument(
        "--no-tray",
        action="store_true",
        help="Headless proxy only (no system tray icon)",
    )
    parser.add_argument(
        "--rate-limit",
        type=int,
        default=None,
        metavar="MIN",
        help="Override email rate-limit in minutes (default: use config.ini)",
    )
    args = parser.parse_args()

    # ------------------------------------------------------------------ #
    # Admin elevation
    # ------------------------------------------------------------------ #
    if args.admin and not is_admin():
        print("[Dev] --admin requires Administrator. Requesting elevation...")
        relaunch_as_admin()

    # ------------------------------------------------------------------ #
    # Pick port & patch config
    # ------------------------------------------------------------------ #
    dev_port = 53 if args.admin else pick_port(53, 53535)
    dev_rate = (
        args.rate_limit
        if args.rate_limit is not None
        else Config.from_ini().rate_limit_minutes
    )
    patch_config(dev_port, dev_rate)

    ensure_file_logging(os.path.join(_PROJECT_ROOT, "logs"))

    # ------------------------------------------------------------------ #
    # Optional: redirect system DNS
    # ------------------------------------------------------------------ #
    if args.admin:
        print("[Dev] Backing up current DNS settings...")
        dev_backup_dns()
        print("[Dev] Setting system DNS to 127.0.0.1...")
        dev_set_dns_localhost()
        atexit.register(dev_restore_dns)

    print_banner(dev_port, args.admin)

    # ------------------------------------------------------------------ #
    # Run
    # ------------------------------------------------------------------ #
    if args.no_tray:
        run_headless_mode()
    else:
        run_tray_mode()


if __name__ == "__main__":
    main()
