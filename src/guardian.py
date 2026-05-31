"""HomeGuard DNS proxy core."""

import logging
import os
import socket
import socketserver
from typing import Optional

from dnslib import DNSRecord, RCODE

from .blocklist import Blocklist
from .alert import AlertEngine
from .config import Config
from .logger import ensure_file_logging


UPSTREAM_TIMEOUT = 5.0
logger = logging.getLogger("HomeGuard.DNS")


class DNSUDPHandler(socketserver.BaseRequestHandler):
    """Handles a single DNS query."""

    def handle(self) -> None:
        data, sock = self.request
        server: DNSProxy = self.server  # type: ignore
        try:
            request = DNSRecord.parse(data)
        except Exception:
            return

        qname = str(request.q.qname).lower().rstrip(".")
        qtype = request.q.qtype

        blocked, category = server.blocklist.is_blocked(qname)

        if blocked and not server.paused:
            reply = request.reply()
            reply.header.rcode = RCODE.NXDOMAIN
            response_packet = reply.pack()
            sock.sendto(response_packet, self.client_address)
            server.alert_engine.log_and_alert(qname, category)
            logger.info("BLOCK %s (%s)", qname, category)
            return

        # Forward to upstream
        try:
            upstream_resp = server.forward_to_upstream(data)
            if upstream_resp:
                sock.sendto(upstream_resp, self.client_address)
            else:
                self._servfail(sock, request, self.client_address)
        except Exception as exc:
            logger.error("Upstream error for %s: %s", qname, exc)
            self._servfail(sock, request, self.client_address)

    @staticmethod
    def _servfail(sock, request, client_address) -> None:
        reply = request.reply()
        reply.header.rcode = RCODE.SERVFAIL
        sock.sendto(reply.pack(), client_address)


class DNSProxy(socketserver.ThreadingUDPServer):
    """UDP DNS server that blocks or forwards queries."""

    allow_reuse_address = True

    def __init__(
        self,
        config: Config,
        blocklist: Blocklist,
        alert_engine: AlertEngine,
    ):
        self.config = config
        self.blocklist = blocklist
        self.alert_engine = alert_engine
        self.paused = False
        super().__init__((config.listen_address, config.listen_port), DNSUDPHandler)

    def forward_to_upstream(self, data: bytes) -> Optional[bytes]:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(UPSTREAM_TIMEOUT)
            sock.sendto(data, (self.config.upstream, self.config.upstream_port))
            try:
                resp, _ = sock.recvfrom(65535)
                return resp
            except socket.timeout:
                return None

    def stop(self) -> None:
        self.shutdown()


def main() -> None:
    config = Config.from_ini()
    ensure_file_logging(os.path.join(os.path.dirname(__file__), "..", "logs"))
    blocklist = Blocklist(
        urls=config.blocklist_urls,
        cache_file=config.cache_file,
        refresh_days=config.refresh_days,
    )
    alert_engine = AlertEngine(
        db_path="logs/homeguard.db",
        smtp_config=config.smtp_config,
        child_name=config.child_name,
        rate_limit_minutes=config.rate_limit_minutes,
    )
    proxy = DNSProxy(config, blocklist, alert_engine)
    try:
        proxy.serve_forever()
    except KeyboardInterrupt:
        logger.info("Interrupted.")
    finally:
        proxy.stop()
        alert_engine.flush()


if __name__ == "__main__":
    main()
