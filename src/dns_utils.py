"""Shared DNS utilities for HomeGuard.

Provides functions to backup, restore, and modify Windows DNS settings.
Used by installer, uninstaller, and dev launcher.
"""

import json
import os
import subprocess
from typing import Dict, List


def get_active_adapters() -> List[str]:
    """Return list of active network adapter names."""
    ps = (
        "Get-NetAdapter | Where-Object { $_.Status -eq 'Up' } | "
        "Select-Object -ExpandProperty InterfaceAlias"
    )
    result = subprocess.run(
        ["powershell", "-Command", ps],
        capture_output=True,
        text=True,
        check=False,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def backup_dns(backup_path: str) -> Dict[str, List[str]]:
    """Backup current DNS settings to a JSON file."""
    adapters = get_active_adapters()
    backup: Dict[str, List[str]] = {}
    for adapter in adapters:
        ps = (
            f"Get-DnsClientServerAddress -InterfaceAlias '{adapter}' -AddressFamily IPv4 | "
            "Select-Object -ExpandProperty ServerAddresses"
        )
        result = subprocess.run(
            ["powershell", "-Command", ps],
            capture_output=True,
            text=True,
            check=False,
        )
        servers = [s.strip() for s in result.stdout.splitlines() if s.strip()]
        if servers:
            backup[adapter] = servers

    os.makedirs(os.path.dirname(backup_path) or ".", exist_ok=True)
    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(backup, f, indent=2)
    return backup


def restore_dns_from_backup(backup_path: str) -> bool:
    """Restore DNS settings from a JSON backup file."""
    if not os.path.exists(backup_path):
        return False

    with open(backup_path, encoding="utf-8") as f:
        backup = json.load(f)

    for adapter, servers in backup.items():
        if not servers:
            continue
        subprocess.run(
            ["netsh", "interface", "ip", "set", "dns", adapter, "static", servers[0]],
            capture_output=True,
            check=False,
        )
        for s in servers[1:]:
            subprocess.run(
                [
                    "netsh",
                    "interface",
                    "ip",
                    "add",
                    "dns",
                    adapter,
                    s,
                    "index=2",
                ],
                capture_output=True,
                check=False,
            )
    return True


def reset_dns_to_dhcp() -> None:
    """Reset all active adapters to DHCP for DNS."""
    for adapter in get_active_adapters():
        subprocess.run(
            ["netsh", "interface", "ip", "set", "dns", adapter, "dhcp"],
            capture_output=True,
            check=False,
        )
        subprocess.run(
            ["netsh", "interface", "ipv6", "set", "dns", adapter, "dhcp"],
            capture_output=True,
            check=False,
        )


def set_dns_to_localhost() -> None:
    """Set all active adapters to use 127.0.0.1 (and ::1 for IPv6) as DNS."""
    adapters = get_active_adapters()
    for adapter in adapters:
        # Remove existing DNS servers
        subprocess.run(
            ["netsh", "interface", "ip", "delete", "dns", adapter, "all"],
            capture_output=True,
            check=False,
        )
        # Set primary DNS to 127.0.0.1
        subprocess.run(
            ["netsh", "interface", "ip", "set", "dns", adapter, "static", "127.0.0.1"],
            capture_output=True,
            check=False,
        )
        # Set IPv6 DNS to ::1
        subprocess.run(
            ["netsh", "interface", "ipv6", "set", "dns", adapter, "static", "::1"],
            capture_output=True,
            check=False,
        )
    # Flush DNS cache
    subprocess.run(["ipconfig", "/flushdns"], capture_output=True, check=False)


def flush_dns_cache() -> None:
    """Flush the Windows DNS resolver cache."""
    subprocess.run(["ipconfig", "/flushdns"], capture_output=True, check=False)
