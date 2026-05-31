"""System tray control panel for HomeGuard."""

import logging
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox

from PIL import Image, ImageDraw
import pystray

# Ensure project root on path
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BASE_DIR not in sys.path:
    sys.path.insert(0, _BASE_DIR)

from src.config import Config
from src.blocklist import Blocklist
from src.alert import AlertEngine
from src.guardian import DNSProxy
from src.logger import ensure_file_logging

logger = logging.getLogger("HomeGuard.Tray")


class TrayApp:
    def __init__(self):
        self.icon: pystray.Icon | None = None
        self.proxy: DNSProxy | None = None
        self.proxy_thread: threading.Thread | None = None
        self.paused = False
        self._stop_event = threading.Event()
        self._create_icon_images()
        self._start_proxy()

    # ------------------------------------------------------------------ #
    # Icon generation
    # ------------------------------------------------------------------ #
    def _create_icon_images(self):
        size = 64
        # Green shield (running)
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.polygon([(size // 2, 4), (size - 4, 12), (size - 8, size - 12), (size // 2, size - 4), (8, size - 12), (4, 12)], fill=(46, 204, 113))
        self.img_running = img

        # Orange shield (paused)
        img2 = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw2 = ImageDraw.Draw(img2)
        draw2.polygon([(size // 2, 4), (size - 4, 12), (size - 8, size - 12), (size // 2, size - 4), (8, size - 12), (4, 12)], fill=(241, 196, 15))
        self.img_paused = img2

    # ------------------------------------------------------------------ #
    # Proxy lifecycle
    # ------------------------------------------------------------------ #
    def _start_proxy(self):
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
            self.proxy_thread = threading.Thread(target=self.proxy.serve_forever, daemon=True)
            self.proxy_thread.start()
            logger.info("Tray proxy started")
        except Exception as exc:
            logger.exception("Failed to start DNS proxy")
            messagebox.showerror("HomeGuard Error", f"Failed to start DNS proxy:\n{exc}")
            sys.exit(1)

    def _toggle_pause(self, icon: pystray.Icon):
        self.paused = not self.paused
        if self.proxy:
            self.proxy.paused = self.paused
        icon.icon = self.img_paused if self.paused else self.img_running
        icon.title = f"HomeGuard — {'PAUSED' if self.paused else 'Running'}"
        icon.update_menu()
        logger.info("Blocking %s", "paused" if self.paused else "resumed")

    # ------------------------------------------------------------------ #
    # Menu actions
    # ------------------------------------------------------------------ #
    def _open_logs(self):
        log_dir = os.path.join(_BASE_DIR, "logs")
        os.makedirs(log_dir, exist_ok=True)
        subprocess.run(["explorer", log_dir])

    def _edit_config(self):
        cfg_path = os.path.join(_BASE_DIR, "config.ini")
        if os.path.exists(cfg_path):
            subprocess.run(["notepad", cfg_path])
        else:
            messagebox.showwarning("HomeGuard", "config.ini not found.")

    def _on_exit(self, icon: pystray.Icon):
        icon.stop()
        if self.proxy:
            self.proxy.stop()
        self._stop_event.set()
        logger.info("Tray exited")

    def _build_menu(self):
        return pystray.Menu(
            pystray.MenuItem(
                lambda text: f"Status: {'PAUSED' if self.paused else 'Running'}",
                lambda icon, item: None,
                enabled=False,
            ),
            pystray.MenuItem(
                lambda text: "Resume" if self.paused else "Pause",
                self._toggle_pause,
            ),
            pystray.MenuItem("Open Log Folder", lambda icon, item: self._open_logs()),
            pystray.MenuItem("Edit Config", lambda icon, item: self._edit_config()),
            pystray.MenuItem("Exit", self._on_exit),
        )

    def run(self):
        self.icon = pystray.Icon(
            "HomeGuard",
            self.img_running,
            "HomeGuard — Running",
            self._build_menu(),
        )
        self.icon.run()


def main():
    ensure_file_logging(os.path.join(_BASE_DIR, "logs"))
    logger.info("HomeGuard tray starting")
    app = TrayApp()
    app.run()


if __name__ == "__main__":
    main()
