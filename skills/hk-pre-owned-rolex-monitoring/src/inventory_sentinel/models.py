from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from .errors import ConfigError


WatchCondition = Literal["unworn", "excellent", "very_good", "good", "fair", "unknown"]
EvidenceStatus = Literal["fixture", "unverified", "verified"]
AcquisitionMethod = Literal[
    "official_api",
    "authorized_export",
    "manual_url",
    "manual_snapshot",
    "fixture",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TargetConfig(StrictModel):
    adapter: str
    url: str
    fixture_path: str | None = None


class ScheduleJob(StrictModel):
    role: str
    cron: str


class ScheduleConfig(StrictModel):
    timezone: str = "UTC"
    jobs: list[ScheduleJob] = Field(default_factory=list)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"未知时区: {value}") from exc
        return value


class NotificationConfig(StrictModel):
    provider: str = "runtime-default"
    recipient: str = "current-user"
    send_no_change_report: bool = True
    include_images: bool = True


class ValidationConfig(StrictModel):
    baseline_samples: int = Field(default=2, ge=2, le=5)
    change_confirmation_samples: int = Field(default=2, ge=2, le=5)
    suspicious_confirmation_samples: int = Field(default=3, ge=3, le=5)
    sample_interval_seconds: float = Field(default=5, ge=0, le=3600)
    retry_delays_seconds: list[int] = Field(default_factory=lambda: [120, 300, 600])
    suspicious_absolute_change: int = Field(default=5, ge=1)
    suspicious_percentage_change: float = Field(default=10, gt=0, le=100)


class StateConfig(StrictModel):
    storage_backend: Literal["sqlite"] = "sqlite"
    image_cache: bool = True
    backup_enabled: bool = True


class MonitorManifest(StrictModel):
    schema_version: Literal[1] = 1
    monitor_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
    display_name: str
    enabled: bool = True
    target: TargetConfig
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    notification: NotificationConfig = Field(default_factory=NotificationConfig)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    state: StateConfig = Field(default_factory=StateConfig)


class InventoryItem(StrictModel):
    stable_id: str
    source_id: str
    title: str | None = None
    family_code: str | None = None
    year: int | None = None
    condition: WatchCondition = "unknown"
    price: Decimal | None = None
    currency: str | None = None
    diameter: str | None = None
    material: str | None = None
    bracelet: str | None = None
    reference: str | None = None
    detail_url: str | None = None
    image_url: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)

    def business_payload(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data.pop("stable_id", None)
        return data


class FetchResult(StrictModel):
    items: list[InventoryItem]
    warnings: list[str] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    raw_payload: Any = None


class MarketComparisonConfig(StrictModel):
    max_age_days: int = Field(default=90, ge=1, le=3650)
    minimum_independent_sources: int = Field(default=2, ge=2, le=10)
    reference_band_percent: Decimal = Field(default=Decimal("5"), gt=0, le=50)
    year_window: int = Field(default=2, ge=0, le=5)
    outlier_warning_percent: Decimal = Field(default=Decimal("30"), gt=0, le=100)

    @field_serializer(
        "reference_band_percent",
        "outlier_warning_percent",
        when_used="json",
    )
    def serialize_decimal_percent(self, value: Decimal) -> float:
        return float(value)


class MarketObservation(StrictModel):
    observation_id: str = Field(min_length=1, max_length=128)
    source: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,63}$")
    source_listing_id: str | None = None
    independence_group: str | None = Field(default=None, min_length=2, max_length=128)
    underlying_listing_id: str | None = Field(default=None, min_length=2, max_length=256)
    dealer_name: str | None = Field(default=None, min_length=1, max_length=256)
    rolex_reference: str = Field(min_length=2, max_length=64)
    region: Literal["HK", "MAINLAND_CN", "APAC", "GLOBAL"]
    basis: Literal[
        "market_estimate",
        "transaction_index",
        "asking_price",
        "auction_result",
        "dealer_quote",
    ]
    price_hkd: Decimal = Field(gt=0)
    observed_at: datetime
    year: int | None = Field(ge=1900, le=2200)
    condition: WatchCondition
    completeness: Literal["full_set", "watch_only", "unknown"] = "unknown"
    evidence_status: EvidenceStatus = "unverified"
    acquisition_method: AcquisitionMethod = "manual_url"
    evidence_url: str | None = None
    evidence_note: str | None = None
    evidence_verified_at: datetime | None = None
    evidence_sha256: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )

    @field_serializer("price_hkd", when_used="json")
    def serialize_price_hkd(self, value: Decimal) -> float:
        return float(value)

    @field_validator("source", mode="before")
    @classmethod
    def normalize_source(cls, value: str) -> str:
        return str(value).strip().lower()

    @field_validator("independence_group", mode="before")
    @classmethod
    def normalize_independence_group(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip().lower()
        return normalized or None

    @field_validator("rolex_reference", mode="before")
    @classmethod
    def normalize_reference(cls, value: str) -> str:
        return "".join(char for char in str(value).strip().upper() if char.isalnum() or char == "-")

    @model_validator(mode="after")
    def validate_provenance(self) -> "MarketObservation":
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at 必须包含时区")
        if not self.evidence_url and not self.evidence_note:
            raise ValueError("每条行情必须提供 evidence_url 或 evidence_note")
        if self.evidence_url and not self.evidence_url.startswith(("https://", "http://")):
            raise ValueError("evidence_url 必须是 HTTP(S) 地址")
        if self.evidence_verified_at is not None and (
            self.evidence_verified_at.tzinfo is None
            or self.evidence_verified_at.utcoffset() is None
        ):
            raise ValueError("evidence_verified_at 必须包含时区")
        if self.evidence_status == "verified":
            if self.acquisition_method == "fixture":
                raise ValueError("fixture 证据不得标记为 verified")
            if self.evidence_verified_at is None or self.evidence_sha256 is None:
                raise ValueError(
                    "verified 行情必须提供 evidence_verified_at 和 evidence_sha256"
                )
        if self.evidence_status == "fixture" and self.acquisition_method != "fixture":
            raise ValueError("fixture 证据必须使用 acquisition_method=fixture")
        if self.acquisition_method == "fixture" and self.evidence_status != "fixture":
            raise ValueError("acquisition_method=fixture 只能用于 fixture 证据")
        if self.acquisition_method == "manual_url" and not self.evidence_url:
            raise ValueError("manual_url 必须提供 evidence_url")
        return self


class MarketPacket(StrictModel):
    schema_version: Literal[1] = 1
    packet_id: str = Field(min_length=1, max_length=128)
    as_of: datetime
    comparison: MarketComparisonConfig = Field(default_factory=MarketComparisonConfig)
    collection_context: dict[str, Any] = Field(default_factory=dict)
    observations: list[MarketObservation] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_packet(self) -> "MarketPacket":
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of 必须包含时区")
        ids = [item.observation_id for item in self.observations]
        if len(ids) != len(set(ids)):
            raise ValueError("observation_id 不得重复")
        source_keys = [
            (item.source, item.source_listing_id)
            for item in self.observations
            if item.source_listing_id
        ]
        if len(source_keys) != len(set(source_keys)):
            raise ValueError("同一来源的 source_listing_id 不得重复")
        for item in self.observations:
            if item.evidence_verified_at and item.evidence_verified_at > self.as_of:
                raise ValueError("evidence_verified_at 不得晚于 Market Packet as_of")
        return self


class RuntimeOperation(StrictModel):
    op: str
    logical_id: str
    required_capability: str
    idempotency_key: str
    parameters: dict[str, Any]
    verification: dict[str, Any]


class RuntimeNotification(StrictModel):
    delivery: Literal["outbox"] = "outbox"
    provider: str
    recipient: str
    include_images: bool
    event_types: list[str]
    list_command: list[str]
    ack_command: list[str]


class RuntimeRequirements(StrictModel):
    scheduler: bool
    notification_delivery: bool
    persistent_state: bool = True
    persist_external_ids: bool = True
    requery_after_write: bool = True


class RuntimePlan(StrictModel):
    schema_version: Literal[1] = 1
    monitor_id: str
    operations: list[RuntimeOperation]
    notification: RuntimeNotification
    requirements: RuntimeRequirements


class RuntimeActionResult(StrictModel):
    logical_id: str
    ok: bool
    external_id: str | None = None
    verified: bool = False
    error: dict[str, Any] | None = None


class RuntimeResult(StrictModel):
    schema_version: Literal[1] = 1
    monitor_id: str
    results: list[RuntimeActionResult]


def load_manifest(path: str | Path) -> MonitorManifest:
    import json
    import yaml

    source = Path(path)
    if not source.is_file():
        raise ConfigError(f"Manifest 不存在: {source}")
    try:
        text = source.read_text(encoding="utf-8")
        if source.suffix.lower() == ".json":
            data = json.loads(text)
        else:
            data = yaml.safe_load(text)
        return MonitorManifest.model_validate(data)
    except ConfigError:
        raise
    except Exception as exc:
        raise ConfigError(f"Manifest 校验失败: {exc}") from exc


def load_market_packet(path: str | Path) -> MarketPacket:
    import json
    import yaml

    source = Path(path)
    if not source.is_file():
        raise ConfigError(f"Market Packet 不存在: {source}")
    try:
        text = source.read_text(encoding="utf-8")
        data = json.loads(text) if source.suffix.lower() == ".json" else yaml.safe_load(text)
        return MarketPacket.model_validate(data)
    except ConfigError:
        raise
    except Exception as exc:
        raise ConfigError(f"Market Packet 校验失败: {exc}") from exc
