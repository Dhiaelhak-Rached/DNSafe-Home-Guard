"""
HomeGuard Complete Uninstall / Cleanup
Run as Administrator:  python uninstall_clean.py
"""

import ctypes
import os
import shutil
import subprocess
import sys
import time

# Add project root to path so we can import shared modules
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.dns_utils import (
    get_active_adapters,
    restore_dns_from_backup,
    reset_dns_to_dhcp,
    flush_dns_cache,
)


# --------------------------------------------------------------------------- #
# Admin check / auto-elevate
# --------------------------------------------------------------------------- #
def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def relaunch_as_admin() -> None:
    if not is_admin():
        print("[Clean] Requesting Administrator privileges...")
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, " ".join(sys.argv), None, 1
        )
        sys.exit(0)


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
INSTALL_DIR = os.path.join(
    os.environ.get("PROGRAMFILES", "C:\\Program Files"), "HomeGuard"
)
STARTUP_FOLDER = os.path.join(
    os.environ.get("APPDATA", ""),
    "Microsoft",
    "Windows",
    "Start Menu",
    "Programs",
    "Startup",
)
SERVICE_NAME = "HomeGuardDNS"
SHORTCUT_NAME = "HomeGuard Tray.lnk"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def run_cmd(args, capture=True):
    result = subprocess.run(args, capture_output=capture, text=True, check=False)
    return result


def stop_service():
    print(f"[Clean] Stopping service '{SERVICE_NAME}'...")
    r = run_cmd(["sc", "stop", SERVICE_NAME])
    if r.returncode == 0 or "FAILED 1062" in r.stdout or "1062" in r.stderr:
        # 1062 = service not started
        print(f"[Clean] Service stopped or was not running.")
    else:
        print(f"[Clean] sc stop returned: {r.stdout or r.stderr}")
    # Give SCM a moment
    time.sleep(1)


def delete_service():
    print(f"[Clean] Deleting service '{SERVICE_NAME}'...")
    r = run_cmd(["sc", "delete", SERVICE_NAME])
    if r.returncode == 0 or "FAILED 1072" in r.stdout or "1072" in r.stderr:
        # 1072 = service marked for deletion (already in progress)
        print(f"[Clean] Service deleted.")
    else:
        print(f"[Clean] sc delete returned: {r.stdout or r.stderr}")
    time.sleep(1)


def kill_processes():
    print("[Clean] Killing any running HomeGuard processes...")
    for proc in ["HomeGuard.exe", "HomeGuardService.exe"]:
        try:
            run_cmd(["taskkill", "/f", "/im", proc], capture=False)
        except FileNotFoundError:
            pass
    time.sleep(0.5)


def restore_dns():
    backup_path = os.path.join(INSTALL_DIR, "dns_backup.json")
    if not os.path.exists(backup_path):
        print("[Clean] No DNS backup found. Resetting to DHCP...")
        reset_dns_to_dhcp()
        print("[Clean] DNS reset to DHCP.")
        return

    print("[Clean] Restoring original DNS settings...")
    if restore_dns_from_backup(backup_path):
        print("[Clean] DNS restored from backup.")
    else:
        print("[Clean] Failed to restore from backup, resetting to DHCP...")
        reset_dns_to_dhcp()


def remove_startup_shortcut():
    shortcut = os.path.join(STARTUP_FOLDER, SHORTCUT_NAME)
    if os.path.exists(shortcut):
        os.remove(shortcut)
        print(f"[Clean] Removed startup shortcut.")
    else:
        print("[Clean] No startup shortcut found.")


def remove_registry():
    print("[Clean] Removing registry uninstall entry...")
    try:
        import winreg

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\HomeGuard"
        winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, key_path)
        print("[Clean] Registry entry removed.")
    except FileNotFoundError:
        print("[Clean] Registry entry already gone.")
    except Exception as exc:
        print(f"[Clean] Could not remove registry entry: {exc}")


def delete_install_dir():
    if os.path.exists(INSTALL_DIR):
        print(f"[Clean] Deleting {INSTALL_DIR}...")
        # Try a few times in case a file is locked
        for attempt in range(3):
            try:
                shutil.rmtree(INSTALL_DIR)
                print("[Clean] Install directory deleted.")
                return
            except Exception as exc:
                print(f"[Clean] Delete attempt {attempt + 1} failed: {exc}")
                time.sleep(1)
        print("[Clean] WARNING: Could not fully delete install directory.")
    else:
        print("[Clean] Install directory already gone.")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    relaunch_as_admin()
    print("=" * 60)
    print("HomeGuard Complete Cleanup")
    print("=" * 60)

    kill_processes()
    stop_service()
    delete_service()
    restore_dns()
    remove_startup_shortcut()
    remove_registry()
    delete_install_dir()
    flush_dns_cache()

    print("=" * 60)
    print("Done. HomeGuard has been fully removed.")
    print("=" * 60)
    input("Press Enter to exit...")


if __name__ == "__main__":
    main()
