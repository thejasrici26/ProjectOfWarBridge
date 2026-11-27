from dataclasses import dataclass
from typing import Protocol


NOTIFICATION_CHANNELS = ("Email", "SMS", "WhatsApp", "Push notification")
NOTIFICATION_STATES = ("Queued", "Sent", "Failed", "Retried")


@dataclass(frozen=True)
class NotificationResult:
    sent: bool
    error_code: str | None = None


class EmergencyNotificationProvider(Protocol):
    def send(self, channel: str, recipient: str, request_id: int) -> NotificationResult: ...


class ProviderDisabledError(RuntimeError):
    pass


class NotificationDispatchError(RuntimeError):
    def __init__(self, error_code: str):
        super().__init__("Emergency notification delivery failed")
        self.error_code = error_code


class DisabledEmergencyNotificationProvider:
    def send(self, channel: str, recipient: str, request_id: int) -> NotificationResult:
        raise ProviderDisabledError("Emergency notification provider is disabled")


class DevelopmentMockEmergencyNotificationProvider:
    def send(self, channel: str, recipient: str, request_id: int) -> NotificationResult:
        if channel not in NOTIFICATION_CHANNELS:
            raise ValueError("Unsupported notification channel")
        if not recipient or request_id < 1:
            raise ValueError("A recipient and valid request identifier are required")
        return NotificationResult(sent=True)


def create_emergency_notification_provider(name: str, app_environment: str):
    if name == "disabled":
        return DisabledEmergencyNotificationProvider()
    if name == "mock" and app_environment == "development":
        return DevelopmentMockEmergencyNotificationProvider()
    raise RuntimeError(
        "WARBRIDGE_EMERGENCY_PROVIDER must be 'disabled' or 'mock' in development"
    )
