"""Configuration loader and validator for HomeGuard."""

import configparser
import os
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Config:
    listen_address: str
    listen_port: int
    upstream: str
    upstream_port: int

    parent_email: str
    smtp_server: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    child_name: str
    rate_limit_minutes: int

    blocklist_urls: List[str]
    cache_file: str
    refresh_days: int

    @classmethod
    def from_ini(cls, path=None):
        if path is None:
            # Look next to this file, then cwd
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            path = os.path.join(base, "config.ini")
            if not os.path.exists(path):
                path = "config.ini"

        parser = configparser.ConfigParser()
        parser.read(path, encoding="utf-8")

        def get(section, key, fallback=None):
            try:
                return parser.get(section, key)
            except (configparser.NoSectionError, configparser.NoOptionError):
                if fallback is not None:
                    return fallback
                raise ValueError(f"Missing config: [{section}] {key}")

        def getint(section, key, fallback=None):
            try:
                return parser.getint(section, key)
            except (configparser.NoSectionError, configparser.NoOptionError):
                if fallback is not None:
                    return fallback
                raise ValueError(f"Missing config: [{section}] {key}")

        urls = [u.strip() for u in get("blocklist", "urls").split(",") if u.strip()]

        return cls(
            listen_address=get("dns", "listen_address", "127.0.0.1"),
            listen_port=getint("dns", "listen_port", 53),
            upstream=get("dns", "upstream", "1.1.1.1"),
            upstream_port=getint("dns", "upstream_port", 53),
            parent_email=get("alert", "parent_email"),
            smtp_server=get("alert", "smtp_server"),
            smtp_port=getint("alert", "smtp_port", 587),
            smtp_user=get("alert", "smtp_user"),
            smtp_password=get("alert", "smtp_password"),
            child_name=get("alert", "child_name", "Child"),
            rate_limit_minutes=getint("alert", "rate_limit_minutes", 15),
            blocklist_urls=urls,
            cache_file=get("blocklist", "cache_file", "blocklist_cache.json.gz"),
            refresh_days=getint("blocklist", "refresh_days", 7),
        )

    @property
    def smtp_config(self) -> dict:
        return {
            "server": self.smtp_server,
            "port": self.smtp_port,
            "user": self.smtp_user,
            "password": self.smtp_password,
            "to": self.parent_email,
        }
