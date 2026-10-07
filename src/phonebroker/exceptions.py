"""PhoneBroker exceptions."""


class PhoneBrokerError(Exception):
    """Base exception for phonebroker."""


class SecretResolutionError(PhoneBrokerError):
    """Failed to resolve a SecretRef to its value."""


class LeaseError(PhoneBrokerError):
    """Lease lifecycle error."""


class LeaseNotFoundError(LeaseError):
    """Lease not found."""


class LeaseNotActiveError(LeaseError):
    """Operation requested on a non-active lease."""


class QueueError(PhoneBrokerError):
    """Queue error."""


class SiteLimitExceeded(PhoneBrokerError):
    """Site limit (interval or daily) exceeded."""

    def __init__(self, reason: str, detail: str):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}")


class PhoneUnavailableError(PhoneBrokerError):
    """Phone is not in 'device' state."""


class PlatformUnavailableError(PhoneBrokerError):
    """Platform package is not installed on phone."""


class MaintenanceActiveError(PhoneBrokerError):
    """Maintenance mode is active."""


class ADBError(PhoneBrokerError):
    """ADB command failed."""

    def __init__(self, command: str, returncode: int, stderr: str):
        self.command = command
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(f"ADB command failed ({returncode}): {command}\n{stderr}")
