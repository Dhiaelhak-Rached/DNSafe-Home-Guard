"""HomeGuard one-click installer wizard for Windows."""

import ctypes
import json
import os
import shutil
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, messagebox

# Add project root to path so we can import shared modules
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.dns_utils import (
    get_active_adapters,
    backup_dns,
    set_dns_to_localhost,
    restore_dns_from_backup,
    reset_dns_to_dhcp,
    flush_dns_cache,
)

# --------------------------------------------------------------------------- #
# Detect frozen (PyInstaller) vs source mode
# --------------------------------------------------------------------------- #
IS_FROZEN = getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None) is not None
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

if IS_FROZEN:
    # When frozen, bundled data lives in sys._MEIPASS
    PROJECT_ROOT = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    # The .exe files (HomeGuard.exe, HomeGuardService.exe) sit next to installer.exe
    EXE_DIR = os.path.dirname(sys.executable)
else:
    PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
    EXE_DIR = PROJECT_ROOT

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


# --------------------------------------------------------------------------- #
# Admin check
# --------------------------------------------------------------------------- #
def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def relaunch_as_admin() -> None:
    if not is_admin():
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, " ".join(sys.argv), None, 1
        )
        sys.exit(0)


# --------------------------------------------------------------------------- #
# DNS helpers (PowerShell) - now using shared dns_utils module
# --------------------------------------------------------------------------- #
def set_dns_to_localhost() -> None:
    """Set DNS to localhost using shared dns_utils module."""
    if not is_admin():
        print("[Installer] ERROR: Not running as Administrator!")
        print("[Installer] DNS changes require admin privileges.")
        return

    print("[Installer] Admin check: PASSED")

    adapters = get_active_adapters()
    if not adapters:
        print("[Installer] Warning: No active network adapters found!")
        return

    print(f"[Installer] Found adapters: {adapters}")

    # Use the shared module's implementation
    from src.dns_utils import set_dns_to_localhost as _set_dns

    _set_dns()

    # Verify DNS settings were applied
    print("\n[Installer] Verifying DNS settings...")
    verification_passed = True
    for adapter in adapters:
        print(f"\n[Installer] Checking adapter: {adapter}")
        result = subprocess.run(
            ["netsh", "interface", "ip", "show", "dns", adapter],
            capture_output=True,
            text=True,
            check=False,
        )
        print(f"[Installer] Full DNS output for {adapter}:")
        print(result.stdout)
        if result.stderr.strip():
            print(f"[Installer] stderr: {result.stderr.strip()}")

        if "127.0.0.1" in result.stdout:
            print(f"[Installer] [OK] {adapter}: DNS successfully set to 127.0.0.1")
        else:
            print(f"[Installer] [FAIL] {adapter}: DNS does not show 127.0.0.1")
            verification_passed = False

    if not verification_passed:
        print(
            "\n[Installer] WARNING: DNS verification failed! HomeGuard may not work correctly."
        )
        print(
            "[Installer] Please manually set your DNS to 127.0.0.1 in Network Settings."
        )
    else:
        print("\n[Installer] SUCCESS: All DNS settings verified!")


# --------------------------------------------------------------------------- #
# Service helpers
# --------------------------------------------------------------------------- #
def _run_cmd(args, cwd=None):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        err = (
            result.stderr.strip()
            or result.stdout.strip()
            or f"Command failed: {' '.join(args)}"
        )
        raise RuntimeError(err)
    return result


def install_service() -> None:
    if IS_FROZEN:
        svc = os.path.join(INSTALL_DIR, "HomeGuardService.exe")
        _run_cmd([svc, "install"], cwd=INSTALL_DIR)
        _run_cmd([svc, "start"], cwd=INSTALL_DIR)
    else:
        svc_script = os.path.join(INSTALL_DIR, "src", "service_wrapper.py")
        _run_cmd([sys.executable, svc_script, "install"], cwd=INSTALL_DIR)
        _run_cmd([sys.executable, svc_script, "start"], cwd=INSTALL_DIR)


def uninstall_service() -> None:
    if IS_FROZEN:
        svc = os.path.join(INSTALL_DIR, "HomeGuardService.exe")
        _run_cmd([svc, "stop"], cwd=INSTALL_DIR)
        _run_cmd([svc, "remove"], cwd=INSTALL_DIR)
    else:
        svc_script = os.path.join(INSTALL_DIR, "src", "service_wrapper.py")
        _run_cmd([sys.executable, svc_script, "stop"], cwd=INSTALL_DIR)
        _run_cmd([sys.executable, svc_script, "remove"], cwd=INSTALL_DIR)


# --------------------------------------------------------------------------- #
# Registry / Uninstaller
# --------------------------------------------------------------------------- #
def register_uninstaller() -> None:
    try:
        import winreg

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\HomeGuard"
        with winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "HomeGuard")
            if IS_FROZEN:
                uninstall_cmd = f'"{sys.executable}" --uninstall'
                icon_path = os.path.join(INSTALL_DIR, "HomeGuard.exe")
            else:
                uninstall_cmd = f'"{sys.executable}" "{os.path.join(INSTALL_DIR, "installer", "installer.py")}" --uninstall'
                icon_path = os.path.join(INSTALL_DIR, "src", "tray_gui.py")
            winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, uninstall_cmd)
            winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, icon_path)
            winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, "HomeGuard")
            winreg.SetValueEx(key, "Version", 0, winreg.REG_SZ, "1.0.0")
    except Exception as exc:
        print(f"[Installer] Could not register uninstaller: {exc}")


# --------------------------------------------------------------------------- #
# SMTP test
# --------------------------------------------------------------------------- #
def test_smtp(server, port, user, password, to_email) -> str:
    import smtplib
    from email.mime.text import MIMEText

    try:
        msg = MIMEText(
            "This is a test email from HomeGuard. If you received this, your alerts are configured correctly."
        )
        msg["Subject"] = "HomeGuard Test Email"
        msg["From"] = user
        msg["To"] = to_email
        with smtplib.SMTP(server, int(port), timeout=15) as s:
            s.starttls()
            s.login(user, password)
            s.sendmail(user, [to_email], msg.as_string())
        return "Test email sent successfully!"
    except Exception as exc:
        return f"Test failed: {exc}"


# --------------------------------------------------------------------------- #
# Wizard GUI
# --------------------------------------------------------------------------- #
class InstallerWizard:
    PRESETS = {
        "Gmail": ("smtp.gmail.com", 587),
        "Outlook": ("smtp-mail.outlook.com", 587),
        "Yahoo": ("smtp.mail.yahoo.com", 587),
        "Custom": ("", ""),
    }

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("HomeGuard Installer")
        self.root.geometry("520x420")
        self.root.resizable(False, False)
        self._center_window()
        self.step = 0
        self.data = {}
        self._build_ui()

    def _center_window(self):
        self.root.update_idletasks()
        w, h = 520, 420
        x = (self.root.winfo_screenwidth() // 2) - (w // 2)
        y = (self.root.winfo_screenheight() // 2) - (h // 2)
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _build_ui(self):
        for widget in self.root.winfo_children():
            widget.destroy()

        if self.step == 0:
            self._welcome_screen()
        elif self.step == 1:
            self._config_screen()
        elif self.step == 2:
            self._test_screen()
        elif self.step == 3:
            self._install_screen()

    def _welcome_screen(self):
        tk.Label(
            self.root, text="Welcome to HomeGuard", font=("Segoe UI", 18, "bold")
        ).pack(pady=20)
        tk.Label(
            self.root,
            text=(
                "HomeGuard becomes your computer's local DNS resolver.\n"
                "It blocks adult and gambling sites, then emails you instantly.\n\n"
                "You must run this installer as Administrator.\n"
                "Click Next to begin setup."
            ),
            justify="center",
            wraplength=460,
        ).pack(pady=10)
        ttk.Button(self.root, text="Next", command=self._next).pack(pady=30)

    def _config_screen(self):
        tk.Label(self.root, text="Parent Settings", font=("Segoe UI", 16, "bold")).pack(
            pady=10
        )

        frame = ttk.Frame(self.root)
        frame.pack(pady=5, padx=20, fill="x")

        ttk.Label(frame, text="Email Provider:").grid(
            row=0, column=0, sticky="w", pady=4
        )
        self.provider_var = tk.StringVar(value="Gmail")
        provider_cb = ttk.Combobox(
            frame,
            textvariable=self.provider_var,
            values=list(self.PRESETS.keys()),
            state="readonly",
            width=18,
        )
        provider_cb.grid(row=0, column=1, sticky="w", pady=4)
        provider_cb.bind("<<ComboboxSelected>>", self._on_provider_change)

        ttk.Label(frame, text="SMTP Server:").grid(row=1, column=0, sticky="w", pady=4)
        self.smtp_server_var = tk.StringVar(value="smtp.gmail.com")
        ttk.Entry(frame, textvariable=self.smtp_server_var, width=30).grid(
            row=1, column=1, sticky="w", pady=4
        )

        ttk.Label(frame, text="SMTP Port:").grid(row=2, column=0, sticky="w", pady=4)
        self.smtp_port_var = tk.StringVar(value="587")
        ttk.Entry(frame, textvariable=self.smtp_port_var, width=10).grid(
            row=2, column=1, sticky="w", pady=4
        )

        ttk.Label(frame, text="Your Email:").grid(row=3, column=0, sticky="w", pady=4)
        self.email_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.email_var, width=30).grid(
            row=3, column=1, sticky="w", pady=4
        )

        ttk.Label(frame, text="App Password:").grid(row=4, column=0, sticky="w", pady=4)
        self.password_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.password_var, show="*", width=30).grid(
            row=4, column=1, sticky="w", pady=4
        )

        ttk.Label(frame, text="Child's Name:").grid(row=5, column=0, sticky="w", pady=4)
        self.child_var = tk.StringVar(value="Child")
        ttk.Entry(frame, textvariable=self.child_var, width=20).grid(
            row=5, column=1, sticky="w", pady=4
        )

        ttk.Button(self.root, text="Next", command=self._validate_config).pack(pady=20)

    def _on_provider_change(self, event=None):
        preset = self.PRESETS.get(self.provider_var.get(), ("", ""))
        self.smtp_server_var.set(preset[0])
        self.smtp_port_var.set(str(preset[1]) if preset[1] else "")

    def _validate_config(self):
        email = self.email_var.get().strip()
        pw = self.password_var.get().strip()
        server = self.smtp_server_var.get().strip()
        port = self.smtp_port_var.get().strip()
        child = self.child_var.get().strip()

        if not all([email, pw, server, port, child]):
            messagebox.showerror("Missing Info", "Please fill in all fields.")
            return

        self.data = {
            "email": email,
            "password": pw,
            "server": server,
            "port": port,
            "child": child,
        }
        self.step = 2
        self._build_ui()

    def _test_screen(self):
        tk.Label(self.root, text="Test Email", font=("Segoe UI", 16, "bold")).pack(
            pady=10
        )
        tk.Label(
            self.root, text="Click the button to send a test alert to your email."
        ).pack(pady=5)
        self.test_result = tk.Label(self.root, text="", wraplength=460)
        self.test_result.pack(pady=10)

        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(pady=10)
        ttk.Button(btn_frame, text="Send Test Email", command=self._do_test).grid(
            row=0, column=0, padx=5
        )
        ttk.Button(btn_frame, text="Skip", command=self._next).grid(
            row=0, column=1, padx=5
        )

    def _do_test(self):
        d = self.data
        result = test_smtp(
            d["server"], d["port"], d["email"], d["password"], d["email"]
        )
        self.test_result.config(text=result)

    def _install_screen(self):
        tk.Label(
            self.root, text="Installing HomeGuard...", font=("Segoe UI", 16, "bold")
        ).pack(pady=10)
        self.status_label = tk.Label(self.root, text="Please wait...", wraplength=460)
        self.status_label.pack(pady=10)
        self.progress = ttk.Progressbar(self.root, mode="indeterminate", length=400)
        self.progress.pack(pady=10)
        self.progress.start()
        self.root.after(100, self._run_install)

    def _run_install(self):
        try:
            self.status_label.config(text="Creating installation directory...")
            os.makedirs(INSTALL_DIR, exist_ok=True)

            self.status_label.config(text="Copying files...")
            if IS_FROZEN:
                # Production mode: copy the .exe files from the same folder as installer.exe
                files_to_copy = [
                    ("HomeGuard.exe", "HomeGuard.exe"),
                    ("HomeGuardService.exe", "HomeGuardService.exe"),
                ]
                for src_name, dst_name in files_to_copy:
                    src = os.path.join(EXE_DIR, src_name)
                    dst = os.path.join(INSTALL_DIR, dst_name)
                    if not os.path.exists(src):
                        raise FileNotFoundError(
                            f"Cannot find {src_name}. Make sure it is in the same folder as installer.exe."
                        )
                    shutil.copy2(src, dst)
            else:
                # Development mode: copy source files
                src_items = ["src", "requirements.txt", "README.md"]
                for item in src_items:
                    src = os.path.join(PROJECT_ROOT, item)
                    dst = os.path.join(INSTALL_DIR, item)
                    if os.path.isdir(src):
                        if os.path.exists(dst):
                            shutil.rmtree(dst)
                        shutil.copytree(src, dst)
                    else:
                        shutil.copy2(src, dst)

            self.status_label.config(text="Writing configuration...")
            self._write_config()

            self.status_label.config(text="Backing up DNS settings...")
            backup_path = os.path.join(INSTALL_DIR, "dns_backup.json")
            backup_dns(backup_path)

            self.status_label.config(text="Setting system DNS to 127.0.0.1...")
            set_dns_to_localhost()
            flush_dns_cache()

            self.status_label.config(text="Installing Windows Service...")
            install_service()

            self.status_label.config(text="Creating startup shortcut...")
            self._create_startup_shortcut()

            self.status_label.config(text="Registering uninstaller...")
            register_uninstaller()

            self.progress.stop()
            self.status_label.config(
                text="Installation complete! HomeGuard is now protecting this PC."
            )
            ttk.Button(self.root, text="Finish", command=self.root.destroy).pack(
                pady=20
            )
        except Exception as exc:
            self.progress.stop()
            messagebox.showerror("Installation Failed", str(exc))
            self.status_label.config(text=f"Failed: {exc}")

    def _write_config(self):
        d = self.data
        cfg = f"""[dns]
listen_address = 127.0.0.1
listen_port = 53
upstream = 1.1.1.1
upstream_port = 53

[alert]
parent_email = {d["email"]}
smtp_server = {d["server"]}
smtp_port = {d["port"]}
smtp_user = {d["email"]}
smtp_password = {d["password"]}
child_name = {d["child"]}
rate_limit_minutes = 15

[blocklist]
urls = https://raw.githubusercontent.com/StevenBlack/hosts/master/alternates/porn-only/hosts,https://raw.githubusercontent.com/StevenBlack/hosts/master/alternates/gambling-only/hosts
cache_file = blocklist_cache.json.gz
refresh_days = 7
"""
        with open(os.path.join(INSTALL_DIR, "config.ini"), "w", encoding="utf-8") as f:
            f.write(cfg)

    def _create_startup_shortcut(self):
        try:
            from win32com.client import Dispatch

            shortcut_path = os.path.join(STARTUP_FOLDER, "HomeGuard Tray.lnk")
            if IS_FROZEN:
                target = os.path.join(INSTALL_DIR, "HomeGuard.exe")
                arguments = ""
            else:
                target = sys.executable
                arguments = f'"{os.path.join(INSTALL_DIR, "src", "tray_gui.py")}"'
            shell = Dispatch("WScript.Shell")
            shortcut = shell.CreateShortCut(shortcut_path)
            shortcut.Targetpath = target
            shortcut.Arguments = arguments
            shortcut.WorkingDirectory = INSTALL_DIR
            shortcut.IconLocation = target
            shortcut.save()
        except Exception:
            pass

    def _next(self):
        self.step += 1
        self._build_ui()

    def run(self):
        self.root.mainloop()


# --------------------------------------------------------------------------- #
# Uninstall flow
# --------------------------------------------------------------------------- #
def do_uninstall() -> None:
    answer = messagebox.askyesno(
        "HomeGuard Uninstaller", "Remove HomeGuard and restore original DNS settings?"
    )
    if not answer:
        return
    try:
        uninstall_service()
    except Exception:
        pass

    backup_path = os.path.join(INSTALL_DIR, "dns_backup.json")
    if os.path.exists(backup_path):
        restore_dns_from_backup(backup_path)
    else:
        reset_dns_to_dhcp()
    flush_dns_cache()

    shortcut = os.path.join(STARTUP_FOLDER, "HomeGuard Tray.lnk")
    if os.path.exists(shortcut):
        os.remove(shortcut)

    if os.path.exists(INSTALL_DIR):
        shutil.rmtree(INSTALL_DIR)

    try:
        import winreg

        winreg.DeleteKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"Software\Microsoft\Windows\CurrentVersion\Uninstall\HomeGuard",
        )
    except Exception:
        pass

    messagebox.showinfo(
        "Uninstalled", "HomeGuard has been removed and DNS settings restored."
    )


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def main():
    if "--uninstall" in sys.argv:
        do_uninstall()
        return

    relaunch_as_admin()
    wizard = InstallerWizard()
    wizard.run()


if __name__ == "__main__":
    main()
