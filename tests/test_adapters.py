import unittest

from emergency_adapter import (
    NOTIFICATION_CHANNELS,
    DevelopmentMockEmergencyNotificationProvider,
    ProviderDisabledError as NotificationProviderDisabledError,
    create_emergency_notification_provider,
)
from verification_adapter import (
    VERIFICATION_STATES,
    DevelopmentMockVerificationProvider,
    ProviderDisabledError as VerificationProviderDisabledError,
    create_verification_provider,
)


class ProviderAdapterTests(unittest.TestCase):
    def test_verification_mock_only_returns_a_submission_state(self):
        provider = create_verification_provider("mock", "development")
        self.assertIsInstance(provider, DevelopmentMockVerificationProvider)
        result = provider.submit("user-17")
        self.assertEqual(result.status, "Submitted")
        self.assertIsNone(result.provider_reference)
        self.assertIn("Expired", VERIFICATION_STATES)

    def test_verification_provider_is_disabled_by_default(self):
        provider = create_verification_provider("disabled", "production")
        with self.assertRaises(VerificationProviderDisabledError):
            provider.submit("user-17")
        with self.assertRaises(RuntimeError):
            create_verification_provider("mock", "production")

    def test_notification_mock_supports_all_declared_channels(self):
        provider = create_emergency_notification_provider("mock", "development")
        self.assertIsInstance(provider, DevelopmentMockEmergencyNotificationProvider)
        for channel in NOTIFICATION_CHANNELS:
            self.assertTrue(provider.send(channel, "test-recipient", 7).sent)

    def test_notification_provider_stays_disabled_outside_development(self):
        provider = create_emergency_notification_provider("disabled", "production")
        with self.assertRaises(NotificationProviderDisabledError):
            provider.send("Email", "test-recipient", 7)
        with self.assertRaises(RuntimeError):
            create_emergency_notification_provider("mock", "test")


if __name__ == "__main__":
    unittest.main()
