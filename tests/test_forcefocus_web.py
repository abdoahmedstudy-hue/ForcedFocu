import unittest
from unittest.mock import patch, MagicMock
import json
import socket
from pathlib import Path
from http.server import BaseHTTPRequestHandler

import forcefocus_web


class TestForceFocusWeb(unittest.TestCase):
    def setUp(self):
        pass

    @patch("socket.socket")
    def test_send_to_daemon_success(self, mock_socket):
        # Setup mock socket
        mock_sock_inst = MagicMock()
        mock_socket.return_value = mock_sock_inst

        # Mock receiving a valid JSON response
        mock_sock_inst.recv.side_effect = [
            b'{"status": "ok", "message": "success"}',
            b"",
        ]

        cmd = {"action": "status"}
        result = forcefocus_web.send_to_daemon(cmd)

        self.assertEqual(result, {"status": "ok", "message": "success"})
        mock_sock_inst.connect.assert_called_once_with(forcefocus_web.SOCK_PATH)
        mock_sock_inst.sendall.assert_called_once_with(json.dumps(cmd).encode("utf-8"))
        mock_sock_inst.close.assert_called_once()

    @patch("time.sleep")
    @patch("socket.socket")
    def test_send_to_daemon_connection_refused_retry(self, mock_socket, mock_sleep):
        mock_sock_inst = MagicMock()

        # Setup to fail first 2 times, then succeed
        mock_socket.side_effect = [
            ConnectionRefusedError("Connection refused"),
            FileNotFoundError("No socket"),
            mock_sock_inst,
        ]
        mock_sock_inst.recv.side_effect = [b'{"status": "ok"}', b""]

        result = forcefocus_web.send_to_daemon({"action": "status"})

        self.assertEqual(result, {"status": "ok"})
        self.assertEqual(mock_sleep.call_count, 2)

    @patch("time.sleep")
    @patch("socket.socket")
    def test_send_to_daemon_max_retries(self, mock_socket, mock_sleep):
        mock_socket.side_effect = ConnectionRefusedError("Connection refused")

        result = forcefocus_web.send_to_daemon({"action": "status"}, retries=3)

        self.assertEqual(result["status"], "daemon_starting")
        self.assertTrue("Daemon not ready" in result["message"])
        self.assertEqual(mock_sleep.call_count, 2)

    @patch("socket.socket")
    def test_send_to_daemon_exception(self, mock_socket):
        mock_socket.side_effect = Exception("Unexpected error")

        result = forcefocus_web.send_to_daemon({"action": "status"}, retries=3)

        self.assertEqual(result["status"], "error")
        self.assertTrue("Daemon communication failed" in result["message"])


class DummyRequest:
    def makefile(self, *args, **kwargs):
        import io

        return io.BytesIO(b"")


class TestForcedFocusHandler(unittest.TestCase):
    def setUp(self):
        self.mock_request = DummyRequest()
        self.mock_client_address = ("127.0.0.1", 12345)
        self.mock_server = MagicMock()

    def test_is_origin_allowed(self):
        # We need to instantiate the handler without calling __init__ because it blocks
        # handling requests. So we create a mock and bind the methods.
        handler = forcefocus_web.ForcedFocusHandler.__new__(
            forcefocus_web.ForcedFocusHandler
        )
        handler.headers = {}

        # No origin
        self.assertTrue(handler._is_origin_allowed())

        # Allowed origins
        handler.headers = {"Origin": "http://localhost:7070"}
        self.assertTrue(handler._is_origin_allowed())

        handler.headers = {"Origin": "http://127.0.0.1:7070"}
        self.assertTrue(handler._is_origin_allowed())

        handler.headers = {
            "Origin": "chrome-extension://hcgpgflhkpdccdjkkobofpaemcgjmhdc"
        }
        self.assertTrue(handler._is_origin_allowed())

        # Disallowed origins
        handler.headers = {"Origin": "http://malicious.com"}
        self.assertFalse(handler._is_origin_allowed())

        handler.headers = {"Origin": "http://localhost:8080"}
        self.assertFalse(handler._is_origin_allowed())

    def test_get_cors_origin(self):
        handler = forcefocus_web.ForcedFocusHandler.__new__(
            forcefocus_web.ForcedFocusHandler
        )

        # No origin defaults to localhost:7070
        handler.headers = {}
        self.assertEqual(handler._get_cors_origin(), "http://127.0.0.1:7070")

        # Disallowed origin defaults to localhost:7070
        handler.headers = {"Origin": "http://malicious.com"}
        self.assertEqual(handler._get_cors_origin(), "http://127.0.0.1:7070")

        # Allowed origin returns itself
        handler.headers = {"Origin": "http://localhost:7070"}
        self.assertEqual(handler._get_cors_origin(), "http://localhost:7070")

        handler.headers = {
            "Origin": "chrome-extension://hcgpgflhkpdccdjkkobofpaemcgjmhdc"
        }
        self.assertEqual(
            handler._get_cors_origin(),
            "chrome-extension://hcgpgflhkpdccdjkkobofpaemcgjmhdc",
        )

    @patch("forcefocus_web.send_to_daemon")
    @patch("forcefocus_web.ForcedFocusHandler._send_json")
    def test_do_GET_api_status(self, mock_send_json, mock_send_to_daemon):
        handler = forcefocus_web.ForcedFocusHandler.__new__(
            forcefocus_web.ForcedFocusHandler
        )
        handler.path = "/api/status"
        handler.headers = {"Origin": "http://localhost:7070"}

        mock_daemon_response = {"status": "ok"}
        mock_send_to_daemon.return_value = mock_daemon_response

        handler.do_GET()

        mock_send_to_daemon.assert_called_once_with({"action": "status"})
        mock_send_json.assert_called_once_with(mock_daemon_response)

    @patch("forcefocus_web.send_to_daemon")
    @patch("forcefocus_web.ForcedFocusHandler._send_json")
    @patch("forcefocus_web.ForcedFocusHandler._read_body")
    def test_do_POST_api_start(
        self, mock_read_body, mock_send_json, mock_send_to_daemon
    ):
        handler = forcefocus_web.ForcedFocusHandler.__new__(
            forcefocus_web.ForcedFocusHandler
        )
        handler.path = "/api/start"
        handler.headers = {"Origin": "http://localhost:7070"}

        mock_read_body.return_value = {
            "duration": 60,
            "mode": "whitelist",
            "session_type": "pomodoro",
            "focus_minutes": 25,
            "break_minutes": 5,
            "cycles": 4,
            "groups": ["work"],
        }

        handler.do_POST()

        mock_send_to_daemon.assert_called_once_with(
            {
                "action": "start",
                "duration_minutes": 60,
                "mode": "whitelist",
                "session_type": "pomodoro",
                "focus_minutes": 25,
                "break_minutes": 5,
                "cycles": 4,
                "groups": ["work"],
            }
        )
        mock_send_json.assert_called_once()

    @patch("forcefocus_web.send_to_daemon")
    @patch("forcefocus_web.ForcedFocusHandler._send_json")
    @patch("forcefocus_web.ForcedFocusHandler._read_body")
    def test_do_POST_api_lists_bulk(
        self, mock_read_body, mock_send_json, mock_send_to_daemon
    ):
        handler = forcefocus_web.ForcedFocusHandler.__new__(
            forcefocus_web.ForcedFocusHandler
        )
        handler.path = "/api/lists/blacklist/bulk"
        handler.headers = {"Origin": "http://localhost:7070"}

        mock_read_body.return_value = {"domains": ["reddit.com", "facebook.com"]}

        handler.do_POST()

        mock_send_to_daemon.assert_called_once_with(
            {
                "action": "add_domains",
                "list": "blacklist",
                "domains": ["reddit.com", "facebook.com"],
            }
        )
        mock_send_json.assert_called_once()

    @patch("forcefocus_web.send_to_daemon")
    @patch("forcefocus_web.ForcedFocusHandler._send_json")
    def test_do_DELETE_api_lists(self, mock_send_json, mock_send_to_daemon):
        handler = forcefocus_web.ForcedFocusHandler.__new__(
            forcefocus_web.ForcedFocusHandler
        )
        handler.path = "/api/lists/blacklist/reddit.com"
        handler.headers = {"Origin": "http://localhost:7070"}

        handler.do_DELETE()

        mock_send_to_daemon.assert_called_once_with(
            {"action": "remove_domain", "list": "blacklist", "domain": "reddit.com"}
        )
        mock_send_json.assert_called_once()


if __name__ == "__main__":
    unittest.main()
