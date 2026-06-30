import json
import re
import unittest
from unittest.mock import MagicMock
from pathlib import Path

import forcefocus_daemon


ROOT = Path(__file__).parent.parent


class TestProductionReadinessStaticChecks(unittest.TestCase):
    def test_fetch_helpers_do_not_hang_on_aborted_gets(self):
        for rel_path in ("web/app.js", "web/settings.js", "web/menubar.js"):
            source = (ROOT / rel_path).read_text(encoding="utf-8")
            self.assertNotIn("return new Promise(() => {})", source, rel_path)
            self.assertIn('status: "aborted"', source, rel_path)
            self.assertIn("finally", source, rel_path)
            self.assertIn("activeRequests.get(requestKey) === controller", source, rel_path)

    def test_extension_rebuilds_rules_from_effective_state_signature(self):
        source = (ROOT / "chrome-extension" / "background.js").read_text(encoding="utf-8")

        required_patterns = [
            "let lastRulesSignature",
            "function buildRulesSignature",
            'buildRulesSignature("blacklist", domains)',
            "lastRulesSignature !== nextSignature",
            "buildRulesSignature(modeKey, allowed)",
            "buildRulesSignature(\"idle\", [])",
        ]
        for pattern in required_patterns:
            self.assertIn(pattern, source)

    def test_extension_treats_alarm_sync_as_guaranteed_path(self):
        source = (ROOT / "chrome-extension" / "background.js").read_text(encoding="utf-8")

        self.assertIn("function ensureSyncAlarm()", source)
        self.assertIn('chrome.alarms.create("syncRules", { periodInMinutes: 1 })', source)
        self.assertIn("Alarms are the guaranteed MV3 sync path", source)
        self.assertRegex(source, re.compile(r"ensureSyncAlarm\(\);\s*connectSSE\(\);", re.MULTILINE))

    def test_extension_guards_dnr_rule_capacity_before_rule_replacement(self):
        source = (ROOT / "chrome-extension" / "background.js").read_text(encoding="utf-8")

        self.assertIn("class RuleCapacityError", source)
        self.assertIn("function assertDynamicRuleCapacity", source)
        self.assertIn("function surfaceRuleCapacityError", source)
        self.assertIn('assertDynamicRuleCapacity(rules, "Blacklist session");\n  await clearBlockRules();', source)
        self.assertIn('assertDynamicRuleCapacity(rules, "Whitelist session");\n  await clearBlockRules();', source)
        self.assertIn('chrome.action.setBadgeText({ text: "ERR" })', source)

    def test_sse_reconnect_paths_are_singleton_guarded(self):
        for rel_path in ("web/app.js", "web/menubar.js", "chrome-extension/background.js"):
            source = (ROOT / rel_path).read_text(encoding="utf-8")
            self.assertIn("let sseReconnectTimer", source, rel_path)
            self.assertIn("function scheduleSSEReconnect()", source, rel_path)
            self.assertIn("eventSource.readyState === 0 || eventSource.readyState === 1", source, rel_path)
            self.assertIn("clearTimeout(sseReconnectTimer)", source, rel_path)

    def test_mutations_wait_for_status_confirmation(self):
        for rel_path in ("web/app.js", "web/menubar.js", "chrome-extension/popup.js"):
            source = (ROOT / rel_path).read_text(encoding="utf-8")
            self.assertIn("function sessionStatusMatchesPayload", source, rel_path)
            self.assertIn("function stopStatusConfirmed", source, rel_path)
            self.assertIn("async function waitForStatusConfirmation", source, rel_path)
            self.assertIn("waiting for daemon confirmation", source, rel_path)

    def test_extension_permissions_are_documented(self):
        manifest = json.loads((ROOT / "chrome-extension" / "manifest.json").read_text(encoding="utf-8"))
        doc = (ROOT / "chrome-extension" / "PERMISSIONS.md").read_text(encoding="utf-8")

        for permission in manifest["permissions"]:
            self.assertIn(f"`{permission}`", doc)
        for host_permission in manifest["host_permissions"]:
            self.assertIn(f"`{host_permission}`", doc)

    def test_settings_changes_emit_sse_revision_for_extension_sync(self):
        source = (ROOT / "forcefocus_daemon.py").read_text(encoding="utf-8")

        self.assertIn("self.state_revision = 0", source)
        self.assertIn("self.state_revision += 1", source)
        self.assertIn('"state_revision": self.state_revision', source)
        self.assertRegex(
            source,
            re.compile(r"if self\._save_settings\(validated_settings\):\n\s+self\.broadcast_state_changed\(\)", re.MULTILINE),
        )

    def test_notification_fallback_surfaces_to_clients(self):
        daemon = (ROOT / "forcefocus_daemon.py").read_text(encoding="utf-8")
        web_html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        web_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        menubar_html = (ROOT / "web" / "menubar.html").read_text(encoding="utf-8")
        menubar_js = (ROOT / "web" / "menubar.js").read_text(encoding="utf-8")
        swift = (ROOT / "forcefocus_menubar.swift").read_text(encoding="utf-8")

        self.assertIn("notification_warning", daemon)
        self.assertIn("notificationFallback", web_html)
        self.assertIn("renderNotificationFallback", web_js)
        self.assertIn("mbNotificationFallback", menubar_html)
        self.assertIn("window.showNotificationFallback", menubar_js)
        self.assertIn("showNotificationFallback(title:", swift)

    def test_generated_icon_controls_have_accessible_names(self):
        app_source = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        settings_source = (ROOT / "web" / "settings.js").read_text(encoding="utf-8")
        index_source = (ROOT / "web" / "index.html").read_text(encoding="utf-8")

        self.assertIn('setAttribute("aria-label", `Edit ${sch.name', app_source)
        self.assertIn('setAttribute("aria-label", `Start ${template.name', app_source)
        self.assertIn('aria-label="Play ${safeSound}"', settings_source)
        self.assertIn('aria-label="Previous month"', index_source)

    def test_extension_permanent_blocks_win_inside_whitelist_rules(self):
        source = (ROOT / "chrome-extension" / "background.js").read_text(encoding="utf-8")

        self.assertIn("Permanent blocks must win even if a domain is also in the whitelist.", source)
        self.assertIn("priority: 3", source)
        self.assertIn("Pomodoro break — kept", source)

    def test_canonical_web_source_and_release_gate_are_documented(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        checklist = (ROOT / "PRODUCTION_READINESS.md").read_text(encoding="utf-8")
        install = (ROOT / "install.sh").read_text(encoding="utf-8")

        self.assertIn('WEB_DIR_SRC="${SCRIPT_DIR}/web"', install)
        self.assertIn("static vanilla JavaScript", readme)
        self.assertIn("Server-Sent Events", readme)
        self.assertIn("web/ is the canonical UI source", checklist)
        self.assertIn("Web/Menu Bar <= 1 second", checklist)
        self.assertIn("Extension <= 3 seconds", checklist)

    def test_motion_and_focus_accessibility_gate_is_enforced_in_css(self):
        web_css = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")
        popup_css = (ROOT / "chrome-extension" / "popup.css").read_text(encoding="utf-8")
        blocked_html = (ROOT / "chrome-extension" / "blocked.html").read_text(encoding="utf-8")

        for source in (web_css, popup_css, blocked_html):
            self.assertIn("prefers-reduced-motion: reduce", source)
            self.assertIn("transition-duration: 0.01ms", source)

        self.assertIn(":focus-visible", web_css)
        self.assertIn(":focus-visible", popup_css)

    def test_embedded_handler_owns_production_auth_and_cors_rules(self):
        handler = forcefocus_daemon.EmbeddedWebHandler.__new__(
            forcefocus_daemon.EmbeddedWebHandler
        )
        handler.server = MagicMock()
        handler.server.daemon_ref.settings = {
            "allowed_extension_ids": ["allowed-extension-id"]
        }
        handler.server.daemon_ref.api_token = "test-token"

        handler.headers = {}
        self.assertTrue(handler._is_origin_allowed())
        self.assertFalse(handler._is_api_token_valid())

        handler.headers = {
            "Origin": "chrome-extension://allowed-extension-id",
            "X-API-Token": "test-token",
        }
        self.assertTrue(handler._is_origin_allowed())
        self.assertTrue(handler._is_api_token_valid())
        self.assertEqual(
            handler._get_cors_origin(),
            "chrome-extension://allowed-extension-id",
        )

        handler.headers = {
            "Origin": "chrome-extension://blocked-extension-id",
            "X-API-Token": "wrong-token",
        }
        self.assertFalse(handler._is_origin_allowed())
        self.assertFalse(handler._is_api_token_valid())

    def test_menu_bar_notifications_report_denied_or_failed_delivery(self):
        source = (ROOT / "forcefocus_menubar.swift").read_text(encoding="utf-8")

        self.assertIn("notification delivery failed", source)
        self.assertIn("notification permission denied", source)
        self.assertIn("notification permission failed", source)


if __name__ == "__main__":
    unittest.main()
