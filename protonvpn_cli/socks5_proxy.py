# Standard Libraries
import os
import sys
import socket
import select
import struct
import logging
import signal
import time
import socketserver

# macOS socket option to bind socket to network interface by index
IP_BOUND_IF = 25


class ThreadingSocks5Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, RequestHandlerClass, iface_index, dns_server=None, logger=None):
        super().__init__(server_address, RequestHandlerClass)
        self.iface_index = iface_index
        self.dns_server = dns_server
        self.logger = logger or logging.getLogger("protonvpn-proxy")


class Socks5Handler(socketserver.BaseRequestHandler):
    """Handles SOCKS5 connections and forwards traffic via bound interface."""

    def resolve_domain(self, domain):
        """Resolve a domain name, preferring the VPN DNS server through the bound interface."""
        dns_server = self.server.dns_server
        iface_idx = self.server.iface_index

        if dns_server:
            try:
                tx_id = 0x5a5a
                header = struct.pack("!HHHHHH", tx_id, 0x0100, 1, 0, 0, 0)
                qname = b"".join(bytes([len(p)]) + p.encode("ascii") for p in domain.split(".")) + b"\x00"
                question = qname + struct.pack("!HH", 1, 1)  # Type A, Class IN
                packet = header + question

                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.settimeout(2.5)
                if iface_idx:
                    sock.setsockopt(socket.IPPROTO_IP, IP_BOUND_IF, iface_idx)
                sock.sendto(packet, (dns_server, 53))
                resp, _ = sock.recvfrom(1024)
                sock.close()

                if len(resp) >= 12:
                    ancount = struct.unpack("!H", resp[6:8])[0]
                    offset = 12 + len(qname) + 4
                    for _ in range(ancount):
                        if offset >= len(resp):
                            break
                        if (resp[offset] & 0xC0) == 0xC0:
                            offset += 2
                        else:
                            while offset < len(resp) and resp[offset] != 0:
                                offset += 1 + resp[offset]
                            offset += 1
                        if offset + 10 > len(resp):
                            break
                        rtype, rclass, ttl, rdlen = struct.unpack("!HHIH", resp[offset:offset + 10])
                        offset += 10
                        if rtype == 1 and rdlen == 4:
                            return socket.inet_ntoa(resp[offset:offset + 4])
                        offset += rdlen
            except Exception:
                pass

        # Fallback to standard resolution
        try:
            return socket.gethostbyname(domain)
        except Exception:
            return None

    def handle(self):
        client = self.request
        logger = self.server.logger

        # SOCKS5 Handshake
        try:
            client.settimeout(15.0)
            data = client.recv(260)
            if not data or data[0] != 0x05:
                client.close()
                return

            # Reply: VER=5, METHOD=0 (No Authentication)
            client.sendall(b"\x05\x00")

            # SOCKS5 Request
            req = client.recv(260)
            if len(req) < 4 or req[0] != 0x05:
                client.close()
                return

            cmd = req[1]
            atyp = req[3]

            # Only CONNECT command supported
            if cmd != 0x01:
                client.sendall(b"\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00")
                client.close()
                return

            offset = 4
            target_ip = None

            if atyp == 0x01:  # IPv4
                target_ip = socket.inet_ntoa(req[offset:offset + 4])
                offset += 4
            elif atyp == 0x03:  # Domain Name
                dlen = req[offset]
                offset += 1
                domain = req[offset:offset + dlen].decode("ascii", errors="replace")
                offset += dlen
                target_ip = self.resolve_domain(domain)
            elif atyp == 0x04:  # IPv6
                target_ip = socket.inet_ntop(socket.AF_INET6, req[offset:offset + 16])
                offset += 16
            else:
                client.sendall(b"\x05\x08\x00\x01\x00\x00\x00\x00\x00\x00")
                client.close()
                return

            target_port = struct.unpack("!H", req[offset:offset + 2])[0]

            if not target_ip:
                # Host unreachable
                client.sendall(b"\x05\x04\x00\x01\x00\x00\x00\x00\x00\x00")
                client.close()
                return

            # Connect to remote target via bound interface
            remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            remote.settimeout(10.0)

            if self.server.iface_index:
                try:
                    remote.setsockopt(socket.IPPROTO_IP, IP_BOUND_IF, self.server.iface_index)
                except Exception as e:
                    logger.debug("Failed to set IP_BOUND_IF: {0}".format(e))

            try:
                remote.connect((target_ip, target_port))
            except Exception as e:
                logger.debug("Proxy connection to {0}:{1} failed: {2}".format(target_ip, target_port, e))
                client.sendall(b"\x05\x05\x00\x01\x00\x00\x00\x00\x00\x00")
                client.close()
                remote.close()
                return

            # Reply Success
            client.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")

            # Bidirectional Relay
            client.settimeout(None)
            remote.settimeout(None)

            sockets = [client, remote]
            while True:
                r, _, w_err = select.select(sockets, [], sockets, 60)
                if w_err or not r:
                    break
                for s in r:
                    other = remote if s is client else client
                    try:
                        buf = s.recv(32768)
                        if not buf:
                            return
                        other.sendall(buf)
                    except Exception:
                        return
        except Exception as e:
            logger.debug("Socks5Handler exception: {0}".format(e))
        finally:
            try:
                client.close()
            except Exception:
                pass


def run_proxy_server(iface_name, host="127.0.0.1", port=1080, dns_server=None, log_file=None):
    """Runs the proxy server main loop."""
    logger = logging.getLogger("protonvpn-proxy")
    logger.setLevel(logging.DEBUG)

    if log_file:
        fh = logging.FileHandler(log_file)
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(fh)

    try:
        iface_index = socket.if_nametoindex(iface_name)
    except Exception as e:
        logger.error("Could not find interface {0}: {1}".format(iface_name, e))
        sys.exit(1)

    logger.info("Starting SOCKS5 proxy on {0}:{1} bound to interface {2} (idx {3})".format(
        host, port, iface_name, iface_index
    ))

    server = ThreadingSocks5Server((host, port), Socks5Handler, iface_index, dns_server, logger)

    def sig_handler(sig, frame):
        logger.info("Stopping proxy server...")
        server.shutdown()
        server.server_close()
        sys.exit(0)

    signal.signal(signal.SIGTERM, sig_handler)
    signal.signal(signal.SIGINT, sig_handler)

    try:
        server.serve_forever()
    except Exception as e:
        logger.error("Server loop exited with error: {0}".format(e))
    finally:
        server.server_close()


if __name__ == "__main__":
    # Helper for running in standalone daemon mode
    # Usage: python -m protonvpn_cli.socks5_proxy <iface_name> <dns_server> <port> <log_file>
    if len(sys.argv) > 1:
        iface = sys.argv[1]
        dns = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] != "None" else None
        p = int(sys.argv[3]) if len(sys.argv) > 3 else 1080
        lf = sys.argv[4] if len(sys.argv) > 4 else None
        run_proxy_server(iface, host="127.0.0.1", port=p, dns_server=dns, log_file=lf)

