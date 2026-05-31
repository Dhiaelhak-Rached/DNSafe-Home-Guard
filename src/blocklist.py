"""Blocklist management: download, cache, and match domains."""

import gzip
import json
import os
import re
import time
from typing import Dict, Optional, Set, Tuple
from urllib.request import urlopen
from urllib.error import URLError


class Blocklist:
    """Manages downloaded host blocklists and provides O(1) lookup."""

    def __init__(self, urls: list, cache_file: str, refresh_days: int):
        self.urls = urls
        self.cache_file = cache_file
        self.refresh_days = refresh_days
        self._blocked: Set[str] = set()
        self._category: Dict[str, str] = {}
        self._load()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def is_blocked(self, domain: str) -> Tuple[bool, Optional[str]]:
        """Return (blocked, category_or_none)."""
        d = domain.lower().strip().rstrip(".")
        if d in self._blocked:
            return True, self._category.get(d)
        # Strip one subdomain level at a time for wildcard-ish matching
        parts = d.split(".")
        for i in range(1, len(parts) - 1):
            parent = ".".join(parts[i:])
            if parent in self._blocked:
                return True, self._category.get(parent)
        return False, None

    def reload(self) -> None:
        """Force re-download and cache refresh."""
        self._fetch_all()
        self._save_cache()

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _load(self) -> None:
        """Load from cache if fresh, otherwise fetch."""
        if self._cache_fresh():
            self._load_cache()
        else:
            self._fetch_all()
            self._save_cache()

    def _cache_fresh(self) -> bool:
        if not os.path.exists(self.cache_file):
            return False
        age_days = (time.time() - os.path.getmtime(self.cache_file)) / 86400
        return age_days < self.refresh_days

    def _fetch_all(self) -> None:
        self._blocked.clear()
        self._category.clear()
        for url in self.urls:
            category = self._derive_category(url)
            try:
                self._fetch_one(url, category)
            except URLError as exc:
                print(f"[Blocklist] Failed to fetch {url}: {exc}")

    def _fetch_one(self, url: str, category: str) -> None:
        print(f"[Blocklist] Fetching {url} ...")
        with urlopen(url, timeout=60) as resp:
            text = resp.read().decode("utf-8", errors="ignore")
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Match "0.0.0.0 domain.com" or "127.0.0.1 domain.com"
            m = re.match(r"^0\.0\.0\.0\s+(\S+)", line)
            if not m:
                m = re.match(r"^127\.0\.0\.1\s+(\S+)", line)
            if m:
                domain = m.group(1).lower()
                # Skip localhost entries
                if domain in ("localhost", "localhost.localdomain"):
                    continue
                self._blocked.add(domain)
                self._category[domain] = category
        print(f"[Blocklist] Loaded {len(self._blocked)} domains from {url}")

    def _derive_category(self, url: str) -> str:
        url_l = url.lower()
        if "porn" in url_l:
            return "Pornography"
        if "gambling" in url_l:
            return "Gambling"
        if "social" in url_l:
            return "Social Media"
        if "adware" in url_l or "malware" in url_l:
            return "Malware/Adware"
        return "Blocked"

    def _save_cache(self) -> None:
        data = {"blocked": list(self._blocked), "category": self._category}
        os.makedirs(os.path.dirname(self.cache_file) or ".", exist_ok=True)
        with gzip.open(self.cache_file, "wt", encoding="utf-8") as fh:
            json.dump(data, fh)
        print(f"[Blocklist] Cache saved to {self.cache_file}")

    def _load_cache(self) -> None:
        print(f"[Blocklist] Loading cache {self.cache_file} ...")
        with gzip.open(self.cache_file, "rt", encoding="utf-8") as fh:
            data = json.load(fh)
        self._blocked = set(data.get("blocked", []))
        self._category = data.get("category", {})
        print(f"[Blocklist] Restored {len(self._blocked)} domains from cache")
