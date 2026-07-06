from cli.proxy import os, json, socket, Path
from cli.output import out

SOCK_PATH = "/var/run/forcefocus.sock"
KS_HASH_FILE = Path("/etc/forcefocus/ks_hash")
CONFIG_DIR = Path("/etc/forcefocus")

def send_command(cmd: dict) -> dict:
    """Send a JSON command to the daemon over the Unix socket."""
    import sys
    if "forcefocus_cli" in sys.modules:
        ff_cli = sys.modules["forcefocus_cli"]
        if hasattr(ff_cli, "send_command") and ff_cli.send_command is not send_command:
            return ff_cli.send_command(cmd)

    if not os.path.exists(SOCK_PATH):
        out.print_error(
            "Daemon is not running (socket not found).",
            code="DAEMON_NOT_FOUND",
            suggestion="Start it with: sudo launchctl load /Library/LaunchDaemons/com.forcefocus.daemon.plist",
        )

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect(SOCK_PATH)
        sock.sendall(json.dumps(cmd).encode("utf-8"))
        sock.shutdown(socket.SHUT_WR)

        chunks = []
        while True:
            try:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
            except socket.timeout:
                break
        sock.close()

        raw = b"".join(chunks).decode("utf-8")
        if not raw:
            out.print_error("Daemon sent an empty response.", code="EMPTY_RESPONSE")

        return json.loads(raw)
    except ConnectionRefusedError:
        out.print_error(
            "Connection refused. Is the daemon running?", code="CONNECTION_REFUSED"
        )
    except socket.timeout:
        out.print_error("Daemon did not respond in time.", code="TIMEOUT")
    except Exception as exc:
        out.print_error(f"Communication error: {exc}", code="SOCKET_ERROR")

