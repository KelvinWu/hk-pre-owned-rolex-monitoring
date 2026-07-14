from __future__ import annotations


class InventorySentinelError(Exception):
    code = "INVENTORY_SENTINEL_ERROR"
    exit_code = 4

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ConfigError(InventorySentinelError):
    code = "CONFIG_ERROR"
    exit_code = 3


class MonitorNotFound(ConfigError):
    code = "MONITOR_NOT_FOUND"


class InvalidSnapshot(InventorySentinelError):
    code = "INVALID_SNAPSHOT"
    exit_code = 2


class BrowserRequired(InvalidSnapshot):
    code = "BROWSER_REQUIRED"


class RunLocked(InventorySentinelError):
    code = "RUN_LOCKED"
    exit_code = 4


class RuntimeFailure(InventorySentinelError):
    code = "RUNTIME_FAILURE"
    exit_code = 4


class BackupError(InventorySentinelError):
    code = "BACKUP_ERROR"
    exit_code = 4


class SourceAuthRequired(ConfigError):
    code = "SOURCE_AUTH_REQUIRED"


class SourceLicenseNotConfirmed(ConfigError):
    code = "SOURCE_LICENSE_NOT_CONFIRMED"


class SourceAutomationProhibited(ConfigError):
    code = "SOURCE_AUTOMATION_PROHIBITED"


class SourceTermsReviewRequired(ConfigError):
    code = "SOURCE_TERMS_REVIEW_REQUIRED"


class SourcePolicyStale(ConfigError):
    code = "SOURCE_POLICY_STALE"


class SourceRateLimited(RuntimeFailure):
    code = "SOURCE_RATE_LIMITED"


class SourceApiAccessDenied(RuntimeFailure):
    code = "SOURCE_API_ACCESS_DENIED"


class SourceSchemaChanged(InvalidSnapshot):
    code = "SOURCE_SCHEMA_CHANGED"
