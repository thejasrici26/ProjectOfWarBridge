from dataclasses import dataclass
from typing import Protocol


VERIFICATION_STATES = (
    "Not started",
    "Submitted",
    "Under review",
    "Approved",
    "Rejected",
    "Expired",
)


@dataclass(frozen=True)
class VerificationSubmission:
    status: str
    provider_reference: str | None = None


class VerificationProvider(Protocol):
    def submit(self, subject_id: str) -> VerificationSubmission: ...


class ProviderDisabledError(RuntimeError):
    pass


class DisabledVerificationProvider:
    def submit(self, subject_id: str) -> VerificationSubmission:
        raise ProviderDisabledError("Identity verification provider is disabled")


class DevelopmentMockVerificationProvider:
    def submit(self, subject_id: str) -> VerificationSubmission:
        if not subject_id:
            raise ValueError("A subject identifier is required")
        return VerificationSubmission(status="Submitted")


def create_verification_provider(name: str, app_environment: str) -> VerificationProvider:
    if name == "disabled":
        return DisabledVerificationProvider()
    if name == "mock" and app_environment == "development":
        return DevelopmentMockVerificationProvider()
    raise RuntimeError(
        "WARBRIDGE_VERIFICATION_PROVIDER must be 'disabled' or 'mock' in development"
    )
