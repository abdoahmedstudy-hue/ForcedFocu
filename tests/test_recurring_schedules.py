import unittest
from unittest.mock import patch, MagicMock
import argparse
import datetime
from pathlib import Path

# Setup sys.path so we can import the modules
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from forcefocus_cli import cmd_schedule, build_parser
from forcefocus_daemon import ForcedFocusDaemon


class TestRecurringSchedulesCLI(unittest.TestCase):
    def setUp(self):
        # Build parser
        self.parser = build_parser()

    def test_schedule_add_parser_defaults(self):
        # standard default values
        parsed = self.parser.parse_args(["schedule", "add", "--recurring", "--days", "0,1", "--time", "12:00"])
        self.assertEqual(parsed.action, "add")
        self.assertTrue(parsed.recurring)
        self.assertEqual(parsed.days, "0,1")
        self.assertEqual(parsed.time, "12:00")
        self.assertEqual(parsed.duration, 120)
        self.assertEqual(parsed.mode, "blacklist")
        self.assertEqual(parsed.session_type, "standard")
        self.assertEqual(parsed.focus, 25)
        self.assertEqual(parsed.break_time, 5)
        self.assertEqual(parsed.cycles, 4)
        self.assertEqual(parsed.name, "Focus Ritual")
        self.assertIsNone(parsed.groups)

    def test_schedule_add_parser_custom(self):
        parsed = self.parser.parse_args([
            "schedule", "add", "--recurring",
            "--days", "0,2,4", "--time", "09:00",
            "--duration", "180", "--mode", "whitelist",
            "--type", "pomodoro", "--focus", "30",
            "--break", "10", "--cycles", "3",
            "--groups", "Work", "Study"
        ])
        self.assertEqual(parsed.days, "0,2,4")
        self.assertEqual(parsed.time, "09:00")
        self.assertEqual(parsed.duration, 180)
        self.assertEqual(parsed.mode, "whitelist")
        self.assertEqual(parsed.session_type, "pomodoro")
        self.assertEqual(parsed.focus, 30)
        self.assertEqual(parsed.break_time, 10)
        self.assertEqual(parsed.cycles, 3)
        self.assertEqual(parsed.groups, ["Work", "Study"])

    @patch("forcefocus_cli.send_command")
    @patch("forcefocus_cli.out.print_data")
    def test_cmd_schedule_add_standard(self, mock_print, mock_send):
        mock_send.return_value = {"status": "ok"}
        args = argparse.Namespace(
            action="add",
            recurring=True,
            days="0,1",
            time="10:00",
            duration=150,
            mode="blacklist",
            session_type="standard",
            groups=None
        )
        cmd_schedule(args)
        mock_send.assert_called_once_with({
            "action": "add_recurring_schedule",
            "name": "Focus Ritual",
            "days_of_week": [0, 1],
            "start_time": "10:00",
            "duration_minutes": 150,
            "mode": "blacklist",
            "session_type": "standard",
            "groups": []
        })

    @patch("forcefocus_cli.send_command")
    @patch("forcefocus_cli.out.print_data")
    def test_cmd_schedule_add_pomodoro(self, mock_print, mock_send):
        mock_send.return_value = {"status": "ok"}
        args = argparse.Namespace(
            action="add",
            recurring=True,
            days="0,1,2",
            time="15:30",
            duration=120, # ignored for pomodoro
            mode="whitelist",
            session_type="pomodoro",
            focus=45,
            break_time=15,
            cycles=2,
            groups=["Work"]
        )
        cmd_schedule(args)
        mock_send.assert_called_once_with({
            "action": "add_recurring_schedule",
            "name": "Focus Ritual",
            "days_of_week": [0, 1, 2],
            "start_time": "15:30",
            "duration_minutes": 120, # (45 + 15) * 2 = 120
            "mode": "whitelist",
            "session_type": "pomodoro",
            "groups": ["Work"],
            "focus_minutes": 45,
            "break_minutes": 15,
            "cycles": 2
        })


class TestRecurringSchedulesDaemon(unittest.TestCase):
    def setUp(self):
        with patch("forcefocus_daemon.ForcedFocusDaemon._load_settings", return_value={}):
            with patch("forcefocus_daemon.ForcedFocusDaemon._restore_session"):
                with patch("forcefocus_daemon.ForcedFocusDaemon._send_mac_notification"):
                    self.daemon = ForcedFocusDaemon()
                    self.daemon.recurring_schedules = []

    @patch("forcefocus_daemon.ForcedFocusDaemon._load_groups", return_value={"Study": ["example.com"]})
    @patch("forcefocus_daemon.ForcedFocusDaemon._persist_session_lock")
    def test_daemon_add_recurring_schedule(self, mock_persist, mock_load_groups):
        cmd = {
            "name": "Study Pomodoro",
            "days_of_week": [0, 1],
            "start_time": "08:30",
            "duration_minutes": 60,
            "mode": "whitelist",
            "session_type": "pomodoro",
            "focus_minutes": 25,
            "break_minutes": 5,
            "cycles": 2,
            "groups": ["Study"]
        }
        res = self.daemon._cmd_add_recurring_schedule(cmd)
        self.assertEqual(res["status"], "ok")
        self.assertEqual(len(self.daemon.recurring_schedules), 1)
        rule = self.daemon.recurring_schedules[0]
        self.assertEqual(rule["days_of_week"], [0, 1])
        self.assertEqual(rule["start_time"], "08:30")
        self.assertEqual(rule["name"], "Study Pomodoro")
        self.assertTrue(rule["enabled"])
        self.assertEqual(rule["session_type"], "pomodoro")
        self.assertEqual(rule["focus_minutes"], 25)
        self.assertEqual(rule["groups"], ["Study"])
        self.assertIn("next_run_label", res["rule"])
        self.assertTrue(self.daemon.state_changed.is_set())
        mock_persist.assert_called_once()

    def test_daemon_rejects_invalid_recurring_schedule(self):
        res = self.daemon._cmd_add_recurring_schedule({
            "days_of_week": [7],
            "start_time": "25:00",
            "duration_minutes": 60,
        })
        self.assertEqual(res["status"], "error")

    def test_daemon_get_status_active_contains_recurring_schedules(self):
        self.daemon.active = True
        self.daemon.mode = "blacklist"
        self.daemon._mono_session_end = 1000.0
        self.daemon.session_expiry = datetime.datetime.now() + datetime.timedelta(hours=2)
        self.daemon.total_duration_seconds = 7200
        self.daemon.active_domains = ["facebook.com"]
        self.daemon.session_type = "standard"
        self.daemon.intent = "Work on project"
        self.daemon.intent_tasks = []
        self.daemon.recurring_schedules = [{"id": "rule-1", "days_of_week": [0], "start_time": "10:00"}]

        with patch("forcefocus_daemon.get_continuous_time", return_value=100.0):
            status = self.daemon._get_status()
            self.assertTrue(status["active"])
            self.assertIn("recurring_schedules", status)
            self.assertEqual(status["recurring_schedules"][0]["id"], "rule-1")
            self.assertEqual(status["recurring_schedules"][0]["days_of_week"], [0])
            self.assertEqual(status["recurring_schedules"][0]["start_time"], "10:00")
            self.assertIn("next_run_at", status["recurring_schedules"][0])
            self.assertIn("next_run_label", status["recurring_schedules"][0])

    @patch("forcefocus_daemon.ForcedFocusDaemon._persist_session_lock")
    def test_daemon_pause_resume_duplicate_recurring_schedule(self, mock_persist):
        self.daemon.recurring_schedules = [{
            "id": "rule-1",
            "name": "Morning",
            "enabled": True,
            "days_of_week": [0],
            "start_time": "10:00",
            "duration_minutes": 60,
            "mode": "blacklist",
            "groups": [],
            "session_type": "standard",
            "focus_minutes": 25,
            "break_minutes": 5,
            "cycles": 4,
            "last_triggered": "",
        }]

        pause_res = self.daemon._cmd_toggle_recurring_schedule({"id": "rule-1"}, False)
        self.assertEqual(pause_res["status"], "ok")
        self.assertFalse(self.daemon.recurring_schedules[0]["enabled"])

        resume_res = self.daemon._cmd_toggle_recurring_schedule({"id": "rule-1"}, True)
        self.assertEqual(resume_res["status"], "ok")
        self.assertTrue(self.daemon.recurring_schedules[0]["enabled"])

        dup_res = self.daemon._cmd_duplicate_recurring_schedule({"id": "rule-1", "name": "Morning Copy"})
        self.assertEqual(dup_res["status"], "ok")
        self.assertEqual(len(self.daemon.recurring_schedules), 2)
        self.assertNotEqual(self.daemon.recurring_schedules[0]["id"], self.daemon.recurring_schedules[1]["id"])
        self.assertEqual(self.daemon.recurring_schedules[1]["name"], "Morning Copy")

    @patch("forcefocus_daemon.ForcedFocusDaemon._persist_session_lock")
    def test_daemon_remove_recurring_schedule(self, mock_persist):
        self.daemon.recurring_schedules = [
            {"id": "rule-1", "days_of_week": [0], "start_time": "10:00"}
        ]
        res = self.daemon._cmd_remove_recurring_schedule({"id": "rule-1"})
        self.assertEqual(res["status"], "ok")
        self.assertEqual(len(self.daemon.recurring_schedules), 0)
        self.assertTrue(self.daemon.state_changed.is_set())
        mock_persist.assert_called_once()

    @patch("forcefocus_daemon.ForcedFocusDaemon._persist_session_lock")
    def test_daemon_update_recurring_schedule(self, mock_persist):
        self.daemon.recurring_schedules = [{
            "id": "rule-1",
            "name": "Morning",
            "enabled": True,
            "days_of_week": [0],
            "start_time": "10:00",
            "duration_minutes": 60,
            "mode": "blacklist",
            "groups": [],
            "session_type": "standard",
            "focus_minutes": 25,
            "break_minutes": 5,
            "cycles": 4,
            "last_triggered": "",
        }]

        # 1. Update name, days, time, duration, and mode
        update_cmd = {
            "id": "rule-1",
            "name": "New Morning Focus",
            "days_of_week": [1, 2],
            "start_time": "09:30",
            "duration_minutes": 90,
            "mode": "whitelist",
        }
        res = self.daemon._cmd_update_recurring_schedule(update_cmd)
        self.assertEqual(res["status"], "ok")
        updated = self.daemon.recurring_schedules[0]
        self.assertEqual(updated["name"], "New Morning Focus")
        self.assertEqual(updated["days_of_week"], [1, 2])
        self.assertEqual(updated["start_time"], "09:30")
        self.assertEqual(updated["duration_minutes"], 90)
        self.assertEqual(updated["mode"], "whitelist")

        # 2. Update to Pomodoro type
        pomo_update_cmd = {
            "id": "rule-1",
            "session_type": "pomodoro",
            "focus_minutes": 30,
            "break_minutes": 10,
            "cycles": 3,
        }
        res = self.daemon._cmd_update_recurring_schedule(pomo_update_cmd)
        self.assertEqual(res["status"], "ok")
        updated = self.daemon.recurring_schedules[0]
        self.assertEqual(updated["session_type"], "pomodoro")
        self.assertEqual(updated["focus_minutes"], 30)
        self.assertEqual(updated["break_minutes"], 10)
        self.assertEqual(updated["cycles"], 3)
        self.assertEqual(updated["duration_minutes"], 120)

        # 3. Validation failure: missing id
        res = self.daemon._cmd_update_recurring_schedule({"name": "No ID"})
        self.assertEqual(res["status"], "error")
        self.assertEqual(res["message"], "Rule ID is required.")

        # 4. Validation failure: invalid rule id
        res = self.daemon._cmd_update_recurring_schedule({"id": "nonexistent-id", "name": "Test"})
        self.assertEqual(res["status"], "error")
        self.assertEqual(res["message"], "Recurring schedule not found.")

        # 5. Validation failure: invalid days
        res = self.daemon._cmd_update_recurring_schedule({"id": "rule-1", "days_of_week": [7]})
        self.assertEqual(res["status"], "error")
        self.assertTrue("days_of_week" in res["message"] or "values must be" in res["message"])


    @patch("forcefocus_daemon.ForcedFocusDaemon._start_session")
    @patch("forcefocus_daemon.ForcedFocusDaemon._play_sound")
    @patch("forcefocus_daemon.ForcedFocusDaemon._send_mac_notification")
    @patch("forcefocus_daemon.ForcedFocusDaemon._persist_session_lock")
    @patch("forcefocus_daemon.get_continuous_time")
    @patch("forcefocus_daemon.datetime")
    def test_watchdog_recurring_schedule_evaluation(
        self, mock_datetime, mock_get_time, mock_persist, mock_notif, mock_sound, mock_start
    ):
        mock_start.return_value = {"status": "ok"}
        
        # Add a recurring schedule: Mon, Tue at 09:00
        rule = {
            "id": "rule-1",
            "days_of_week": [0, 1], # Monday, Tuesday
            "start_time": "09:00",
            "duration_minutes": 45,
            "mode": "blacklist",
            "session_type": "standard",
            "groups": [],
            "last_triggered": ""
        }
        self.daemon.recurring_schedules = [rule]
        
        # 1. First watchdog check - mismatch weekday (let's say it's Wednesday = 2)
        mock_get_time.return_value = 100.0
        
        # Mock datetime to Wed May 20, 2026, 09:00:00
        # weekday() == 2 (Wednesday)
        mock_datetime.now.return_value = datetime.datetime(2026, 5, 20, 9, 0)
        
        self.daemon._watchdog_tick()
        mock_start.assert_not_called()
        self.assertEqual(rule["last_triggered"], "")
        
        # 2. Match weekday (Tuesday = 1) but time mismatch (08:59)
        self.daemon._mono_last_recurring_check = 0.0 # reset check interval
        mock_get_time.return_value = 200.0
        mock_datetime.now.return_value = datetime.datetime(2026, 5, 19, 8, 59)
        
        self.daemon._watchdog_tick()
        mock_start.assert_not_called()
        self.assertEqual(rule["last_triggered"], "")

        # 3. Match weekday (Tuesday = 1) and match time (09:00) -> should trigger!
        self.daemon._mono_last_recurring_check = 0.0
        mock_get_time.return_value = 300.0
        mock_datetime.now.return_value = datetime.datetime(2026, 5, 19, 9, 0)
        
        self.daemon._watchdog_tick()
        mock_start.assert_called_once_with({
            "action": "start",
            "duration_minutes": 45,
            "mode": "blacklist",
            "groups": [],
            "session_type": "standard"
        })
        self.assertEqual(rule["last_triggered"], "2026-05-19")
        self.assertEqual(rule["last_result"], "started")
        self.assertEqual(mock_persist.call_count, 2)
        mock_sound.assert_called_once_with("scheduled")
        
        # 4. Subsequent ticks on same day/time should not trigger again (due to last_triggered)
        mock_start.reset_mock()
        self.daemon._mono_last_recurring_check = 0.0
        mock_get_time.return_value = 400.0
        self.daemon._watchdog_tick()
        mock_start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
