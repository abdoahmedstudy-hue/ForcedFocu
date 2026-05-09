import unittest
from forcefocus_daemon import ForcedFocusDaemon


class TestWhitelistExpansion(unittest.TestCase):
    def test_google_not_whitelisted_by_default(self):
        daemon = ForcedFocusDaemon()
        # Test basic whitelist expansion
        expanded = daemon._expand_whitelist_domains(["example.com"])

        # Verify that example.com is in the expanded list
        self.assertIn("example.com", expanded)

        # Verify that google.com is NOT in the expanded list
        # Because we removed it from CDN_INFRASTRUCTURE_DOMAINS
        self.assertNotIn("google.com", expanded)

        # Verify that some necessary google domains ARE still there
        self.assertIn("accounts.google.com", expanded)
        self.assertIn("gstatic.com", expanded)
        self.assertIn("googleapis.com", expanded)


if __name__ == "__main__":
    unittest.main()
