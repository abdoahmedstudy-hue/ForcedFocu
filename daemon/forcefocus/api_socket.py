import os
import json
import time
import socket
import logging
from pathlib import Path
from forcefocus.constants import SOCK_PATH, SOCKET_TIMEOUT

class SocketAPIManager:
    def __init__(self, daemon):
        self.daemon = daemon

    def socket_server(self):
        if os.path.exists(SOCK_PATH):
            os.unlink(SOCK_PATH)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(SOCK_PATH)
        os.chmod(SOCK_PATH, 0o600)

        user_file = Path("/etc/forcefocus/user")
        if user_file.exists():
            try:
                import pwd
                username = user_file.read_text().strip()
                uid = pwd.getpwnam(username).pw_uid
                os.chown(SOCK_PATH, uid, -1)
            except Exception as exc:
                logging.error("Failed to chown socket: %s", exc)

        sock.listen(5)
        sock.settimeout(SOCKET_TIMEOUT)
        logging.info("Command socket listening at %s.", SOCK_PATH)

        while True:
            try:
                conn, _ = sock.accept()
            except socket.timeout:
                continue
            except OSError as exc:
                logging.error("Socket accept error: %s", exc)
                time.sleep(1)
                continue
            try:
                conn.settimeout(5.0)
                MAX_MSG_SIZE = 1 * 1024 * 1024  # 1MB
                chunks = []
                total_size = 0
                while True:
                    chunk = conn.recv(8192)
                    if not chunk:
                        break
                    total_size += len(chunk)
                    if total_size > MAX_MSG_SIZE:
                        logging.warning("Socket message exceeded %d bytes.", MAX_MSG_SIZE)
                        conn.sendall(json.dumps({"status": "error", "message": "Message too large."}).encode("utf-8"))
                        chunks = []
                        break
                    chunks.append(chunk)
                raw = b"".join(chunks).decode("utf-8").strip()
                if not raw:
                    continue
                response = self.dispatch_command(raw)
                conn.sendall(json.dumps(response).encode("utf-8"))
            except Exception as exc:
                logging.error("Socket handler error: %s", exc)
                try:
                    conn.sendall(json.dumps({"status": "error", "message": str(exc)}).encode("utf-8"))
                except Exception:
                    pass
            finally:
                conn.close()

    def dispatch_command(self, raw: str) -> dict:
        try:
            cmd = json.loads(raw)
        except json.JSONDecodeError:
            return {"status": "error", "message": "Malformed JSON."}

        action = cmd.get("action", "")

        # Use daemon proxies for now to preserve compatibility, 
        # until all methods are successfully extracted and proxy methods are removed.
        if action == "start":
            return self.daemon.session_manager._start_session(cmd)
        elif action == "stop":
            return self.daemon.session_manager._request_stop(cmd.get("key", ""))
        elif action == "cancel_stop":
            return self.daemon.session_manager._cancel_stop()
        elif action == "status":
            return self.daemon.session_manager.cmd_get_status()
        elif action == "get_lists":
            return self.daemon.domains_manager.cmd_get_lists()
        elif action == "add_domain":
            return self.daemon.domains_manager.cmd_add_domain(cmd)
        elif action == "add_domains":
            return self.daemon.domains_manager.cmd_add_domains(cmd)
        elif action == "remove_domain":
            return self.daemon.domains_manager.cmd_remove_domain(cmd)
        elif action == "get_groups":
            return self.daemon.domains_manager.cmd_get_groups()
        elif action == "add_group":
            return self.daemon.domains_manager.cmd_add_group(cmd)
        elif action == "remove_group":
            return self.daemon.domains_manager.cmd_remove_group(cmd)
        elif action == "get_perma_blocklist":
            return self.daemon.domains_manager.cmd_get_perma_blocklist()
        elif action == "add_perma_block":
            return self.daemon.domains_manager.cmd_add_perma_block(cmd)
        elif action == "request_perma_unblock":
            return self.daemon.domains_manager.cmd_request_perma_unblock(cmd)
        elif action == "cancel_perma_unblock":
            return self.daemon.domains_manager.cmd_cancel_perma_unblock(cmd)
        elif action == "get_recurring_schedules":
            return self.daemon.schedules_manager.cmd_get_recurring_schedules()
        elif action == "add_recurring_schedule":
            return self.daemon.schedules_manager.cmd_add_recurring_schedule(cmd)
        elif action == "update_recurring_schedule":
            return self.daemon.schedules_manager.cmd_update_recurring_schedule(cmd)
        elif action == "pause_recurring_schedule":
            return self.daemon.schedules_manager.cmd_toggle_recurring_schedule(cmd, False)
        elif action == "resume_recurring_schedule":
            return self.daemon.schedules_manager.cmd_toggle_recurring_schedule(cmd, True)
        elif action == "duplicate_recurring_schedule":
            return self.daemon.schedules_manager.cmd_duplicate_recurring_schedule(cmd)
        elif action == "remove_recurring_schedule":
            return self.daemon.schedules_manager.cmd_remove_recurring_schedule(cmd)
        elif action == "get_templates":
            return self.daemon.schedules_manager.cmd_get_templates()
        elif action == "add_template":
            return self.daemon.schedules_manager.cmd_add_template(cmd)
        elif action == "update_template":
            return self.daemon.schedules_manager.cmd_update_template(cmd)
        elif action == "remove_template":
            return self.daemon.schedules_manager.cmd_remove_template(cmd)
        elif action == "duplicate_template":
            return self.daemon.schedules_manager.cmd_duplicate_template(cmd)
        elif action == "start_template":
            return self.daemon.schedules_manager.cmd_start_template(cmd)
        elif action == "get_settings":
            return self.daemon.settings_manager.cmd_get_settings()
        elif action == "save_settings":
            return self.daemon.settings_manager.cmd_save_settings(cmd)
        elif action == "get_sounds":
            return self.daemon.notifications_manager.cmd_get_sounds()
        elif action == "delete_sound":
            return self.daemon.notifications_manager.cmd_delete_sound(cmd)
        elif action == "upload_sound":
            return self.daemon.notifications_manager.cmd_upload_sound(cmd)
        else:
            return {"status": "error", "message": f"Unknown action: {action}"}
