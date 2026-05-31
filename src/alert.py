"""Alert engine: SQLite logging + SMTP email alerts with retry & file logging."""

import logging
import os
import sqlite3
import smtplib
import socket
import threading
import time
from datetime import datetime
from email.mime.text import MIMEText
from queue import Queue
from typing import Dict, Optional

from .logger import ensure_file_logging


class AlertEngine:
    """Logs blocked attempts to SQLite and emails parents via SMTP."""

    def __init__(
        self,
        db_path: str,
        smtp_config: Dict[str, str],
        child_name: str,
        rate_limit_minutes: int = 15,
        log_dir: Optional[str] = None,
    ):
        self.db_path = db_path
        self.smtp_config = smtp_config
        self.child_name = child_name
        self.rate_limit_seconds = rate_limit_minutes * 60
        self._queue: Queue = Queue()
        self._worker = threading.Thread(target=self._run_worker, daemon=True)
        self._last_alert: Dict[str, float] = {}
        self._lock = threading.Lock()

        if log_dir is None:
            log_dir = os.path.dirname(db_path) or "logs"
        ensure_file_logging(log_dir)
        self.logger = logging.getLogger("HomeGuard.Alert")

        self._ensure_schema()
        self._worker.start()
        self.logger.info("AlertEngine started (rate_limit=%dm)", rate_limit_minutes)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def log_and_alert(self, domain: str, category: Optional[str]) -> None:
        """Enqueue a blocked attempt for logging + optional email."""
        qsize = self._queue.qsize()
        if qsize > 100:
            self.logger.warning("Alert queue backing up (%d items)", qsize)
        self._queue.put((domain, category or "Blocked"))

    def flush(self) -> None:
        """Wait until the queue is empty."""
        self._queue.join()

    # ------------------------------------------------------------------ #
    # SQLite
    # ------------------------------------------------------------------ #
    def _ensure_schema(self) -> None:
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS blocked_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    child_name TEXT,
                    domain TEXT,
                    category TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS failed_emails (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    child_name TEXT,
                    domain TEXT,
                    category TEXT,
                    error TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def _log(self, domain: str, category: str) -> None:
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT INTO blocked_attempts (child_name, domain, category) VALUES (?, ?, ?)",
                    (self.child_name, domain, category),
                )
                conn.commit()
        except Exception as exc:
            self.logger.error("SQLite insert failed: %s", exc)

    def _log_failed_email(self, domain: str, category: str, error: str) -> None:
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT INTO failed_emails (child_name, domain, category, error) VALUES (?, ?, ?, ?)",
                    (self.child_name, domain, category, error),
                )
                conn.commit()
        except Exception as exc:
            self.logger.error("Failed to persist failed email: %s", exc)

    # ------------------------------------------------------------------ #
    # SMTP helpers
    # ------------------------------------------------------------------ #
    def _should_email(self, domain: str) -> bool:
        with self._lock:
            now = time.time()
            last = self._last_alert.get(domain, 0)
            if now - last < self.rate_limit_seconds:
                self.logger.info(
                    "Rate limit: skipping email for %s (last alert %.0fs ago)",
                    domain,
                    now - last,
                )
                return False
            self._last_alert[domain] = now
            return True

    @staticmethod
    def _is_transient_error(exc: Exception) -> bool:
        """Return True if the error looks temporary (network, timeout, server busy)."""
        if isinstance(exc, (socket.timeout, socket.gaierror, ConnectionError, OSError)):
            return True
        msg = str(exc).lower()
        transient_keywords = (
            "temporary failure",
            "try again",
            "busy",
            "timeout",
            "connection",
            "unreachable",
            "refused",
            "reset",
            "104",
            "110",
            "111",
        )
        return any(k in msg for k in transient_keywords)

    def _send_email(self, domain: str, category: str) -> None:
        cfg = self.smtp_config
        subject = "🚨 HomeGuard Alert — Blocked Access Attempt"
        body = (
            f"Child: {self.child_name}\n"
            f"Attempted site: {domain}\n"
            f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"Category: {category}\n"
            f"Action: Blocked (NXDOMAIN returned)\n"
        )
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = cfg["user"]
        msg["To"] = cfg["to"]

        last_error = ""
        attempt = 0
        for attempt in range(1, 4):
            try:
                self.logger.debug("SMTP attempt %d/%d for %s", attempt, 3, domain)
                with smtplib.SMTP(
                    cfg["server"], int(cfg["port"]), timeout=15
                ) as server:
                    server.starttls()
                    server.login(cfg["user"], cfg["password"])
                    server.sendmail(cfg["user"], [cfg["to"]], msg.as_string())
                self.logger.info("Email sent for %s", domain)
                return
            except smtplib.SMTPAuthenticationError as exc:
                last_error = f"Auth error: {exc}"
                self.logger.error("SMTP auth failed for %s: %s", domain, exc)
                break  # Authentication errors are permanent; do not retry
            except Exception as exc:
                last_error = str(exc)
                self.logger.warning(
                    "Email attempt %d failed for %s: %s", attempt, domain, exc
                )
                if attempt < 3 and self._is_transient_error(exc):
                    wait = 5 * attempt
                    self.logger.info("Retrying %s in %ds...", domain, wait)
                    time.sleep(wait)
                else:
                    break

        self.logger.error(
            "Email permanently failed for %s after %d attempts", domain, attempt
        )
        self._log_failed_email(domain, category, last_error)

    # ------------------------------------------------------------------ #
    # Background worker
    # ------------------------------------------------------------------ #
    def _run_worker(self) -> None:
        while True:
            domain, category = self._queue.get()
            try:
                self._log(domain, category)
                if self._should_email(domain):
                    self._send_email(domain, category)
            except Exception as exc:
                self.logger.exception("Unexpected error in alert worker: %s", exc)
            finally:
                self._queue.task_done()
