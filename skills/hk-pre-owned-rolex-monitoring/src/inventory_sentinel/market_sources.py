from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Mapping

import httpx

from .errors import (
    ConfigError,
    SourceApiAccessDenied,
    SourceAuthRequired,
    SourceAutomationProhibited,
    SourceLicenseNotConfirmed,
    SourcePolicyStale,
    SourceRateLimited,
    SourceSchemaChanged,
    SourceTermsReviewRequired,
)
from .models import MarketObservation, MarketPacket


SOURCE_REGISTRY_VERSION = 3
SOURCE_POLICY_CHECKED_AT = "2026-07-13"
SOURCE_POLICY_REVIEW_DAYS = 90


MARKET_SOURCES: dict[str, dict[str, Any]] = {
    "watchcharts": {
        "display_name": "WatchCharts",
        "tier": "A",
        "home_region": "GLOBAL",
        "price_semantics": "模型级市场估值、经销商价格、波动率与挂牌中位数",
        "access": "official_api_with_api_key",
        "automation_status": "SUPPORTED_WITH_USER_CREDENTIALS",
        "adapter_status": "IMPLEMENTED_OFFLINE_TESTED",
        "manual_evidence_supported": True,
        "credential_env": ["WATCHCHARTS_API_KEY"],
        "license_env": "WATCHCHARTS_LICENSE",
        "supported_licenses": ["internal", "distribution", "resale"],
        "rate_limit": {"requests_per_second": 1, "metering": "data_credits"},
        "storage": {
            "raw_response_in_public_repository": False,
            "derived_output_depends_on_license": True,
        },
        "terms": {
            "url": "https://watchcharts.com/api/license",
            "api_url": "https://watchcharts.com/api",
            "checked_at": SOURCE_POLICY_CHECKED_AT,
            "review_status": "OFFICIAL_API_AND_LICENSE_DOCUMENTED",
        },
        "url": "https://watchcharts.com/api/documentation",
    },
    "chrono24-valuation": {
        "display_name": "Chrono24 Valuation / Watch Collection",
        "tier": "A",
        "home_region": "GLOBAL",
        "price_semantics": "基于全球平台数据的估值或平均价格区间",
        "access": "manual_or_authorized_export",
        "automation_status": "TERMS_REVIEW_REQUIRED",
        "adapter_status": "NOT_IMPLEMENTED",
        "manual_evidence_supported": True,
        "credential_env": [],
        "license_env": None,
        "terms": {
            "url": "https://about.chrono24.com/en/imprint",
            "checked_at": SOURCE_POLICY_CHECKED_AT,
            "review_status": "NO_PUBLIC_MARKET_DATA_API_CONFIRMED",
        },
        "url": "https://www.chrono24.com/info/valuation.htm",
    },
    "wristcheck-index": {
        "display_name": "Wristcheck Watch Index",
        "tier": "A",
        "home_region": "HK",
        "price_semantics": "平台声明的交易价格及假定流动价格指数",
        "access": "manual_or_licensed_export",
        "automation_status": "PROHIBITED_WITHOUT_WRITTEN_PERMISSION",
        "adapter_status": "NOT_IMPLEMENTED",
        "manual_evidence_supported": True,
        "credential_env": [],
        "license_env": None,
        "terms": {
            "url": "https://wristcheck.com/terms-and-conditions",
            "checked_at": SOURCE_POLICY_CHECKED_AT,
            "review_status": "AUTOMATED_ACCESS_REQUIRES_EXPRESS_PERMISSION",
        },
        "url": "https://wristcheck.com/us/about-us",
    },
    "christies-hk": {
        "display_name": "Christie's Hong Kong",
        "tier": "A",
        "home_region": "HK",
        "price_semantics": "拍卖成交结果；仅在型号、成色、附件和费用口径可比时使用",
        "access": "manual_public_result",
        "automation_status": "TERMS_REVIEW_REQUIRED",
        "adapter_status": "NOT_IMPLEMENTED",
        "manual_evidence_supported": True,
        "credential_env": [],
        "license_env": None,
        "terms": {
            "url": "https://www.christies.com/about-us/legal/terms-and-conditions",
            "checked_at": SOURCE_POLICY_CHECKED_AT,
            "review_status": "MANUAL_EVIDENCE_ONLY_UNTIL_REVIEWED",
        },
        "url": "https://www.christies.com/en/results",
    },
    "wristcheck-listings": {
        "display_name": "Wristcheck Listings",
        "tier": "B",
        "home_region": "HK",
        "price_semantics": "香港市场挂牌或可议价价格",
        "access": "manual_or_authorized_export",
        "automation_status": "PROHIBITED_WITHOUT_WRITTEN_PERMISSION",
        "adapter_status": "NOT_IMPLEMENTED",
        "manual_evidence_supported": True,
        "credential_env": [],
        "license_env": None,
        "terms": {
            "url": "https://wristcheck.com/terms-and-conditions",
            "checked_at": SOURCE_POLICY_CHECKED_AT,
            "review_status": "AUTOMATED_ACCESS_REQUIRES_EXPRESS_PERMISSION",
        },
        "url": "https://wristcheck.com/us/store/hong-kong",
    },
    "28watches": {
        "display_name": "28Watches",
        "tier": "B",
        "home_region": "HK",
        "price_semantics": "香港实体商户挂牌或报价",
        "access": "manual_or_authorized_export",
        "automation_status": "TERMS_REVIEW_REQUIRED",
        "adapter_status": "NOT_IMPLEMENTED",
        "manual_evidence_supported": True,
        "credential_env": [],
        "license_env": None,
        "terms": {
            "url": "https://en.28watches.com/",
            "checked_at": SOURCE_POLICY_CHECKED_AT,
            "review_status": "NO_AUTOMATION_PERMISSION_CONFIRMED",
        },
        "url": "https://en.28watches.com/",
    },
    "kens-watches": {
        "display_name": "Ken's Watches",
        "tier": "B",
        "home_region": "HK",
        "price_semantics": "香港实体商户挂牌或报价",
        "access": "manual_or_authorized_export",
        "automation_status": "TERMS_REVIEW_REQUIRED",
        "adapter_status": "NOT_IMPLEMENTED",
        "manual_evidence_supported": True,
        "credential_env": [],
        "license_env": None,
        "terms": {
            "url": "https://kenwatches.com/aboutUs",
            "checked_at": SOURCE_POLICY_CHECKED_AT,
            "review_status": "NO_AUTOMATION_PERMISSION_CONFIRMED",
        },
        "url": "https://kenwatches.com/aboutUs",
    },
    "watchfinder-hk": {
        "display_name": "Watchfinder Hong Kong",
        "tier": "B",
        "home_region": "HK",
        "price_semantics": "专业二手平台香港挂牌价格",
        "access": "manual_or_authorized_export",
        "automation_status": "TERMS_REVIEW_REQUIRED",
        "adapter_status": "NOT_IMPLEMENTED",
        "manual_evidence_supported": True,
        "credential_env": [],
        "license_env": None,
        "terms": {
            "url": "https://www.watchfinder.hk/",
            "checked_at": SOURCE_POLICY_CHECKED_AT,
            "review_status": "NO_AUTOMATION_PERMISSION_CONFIRMED",
        },
        "url": "https://www.watchfinder.hk/",
    },
    "orientalwatch-inventory": {
        "display_name": "Oriental Watch Hong Kong Rolex CPO Inventory",
        "tier": "INVENTORY",
        "home_region": "HK",
        "price_semantics": "东方表行当前 CPO 库存挂牌价；属于监控目标，不是独立市场参考源",
        "access": "public_site_internal_endpoint",
        "automation_status": "PUBLIC_RELEASE_REVIEW_REQUIRED",
        "adapter_status": "IMPLEMENTED_FIXTURE_TESTED_POLICY_REVIEW_PENDING",
        "manual_evidence_supported": True,
        "credential_env": [],
        "license_env": None,
        "terms": {
            "url": "https://www.orientalwatch.com/owh/article.aspx?id=50038&lang=eng",
            "checked_at": SOURCE_POLICY_CHECKED_AT,
            "review_status": "TECHNICALLY_VALIDATED_PUBLIC_RELEASE_PERMISSION_PENDING",
        },
        "url": "https://www.orientalwatch.com/zh-hant/rolex-certified-pre-owned/watches/",
    },
    "mainland-marketplace": {
        "display_name": "Mainland Marketplace Sample",
        "tier": "C",
        "home_region": "MAINLAND_CN",
        "price_semantics": "大陆个人或平台挂牌样本；真实性、税费、成色与成交状态未统一",
        "access": "manual_evidence_only",
        "automation_status": "MANUAL_ONLY",
        "adapter_status": "NOT_APPLICABLE",
        "manual_evidence_supported": True,
        "credential_env": [],
        "license_env": None,
        "terms": {
            "url": None,
            "checked_at": SOURCE_POLICY_CHECKED_AT,
            "review_status": "SOURCE_SPECIFIC_REVIEW_REQUIRED",
        },
        "url": None,
    },
    "other": {
        "display_name": "Other Documented Source",
        "tier": "C",
        "home_region": "GLOBAL",
        "price_semantics": "未纳入来源目录的有证据行情，仅作上下文",
        "access": "manual_evidence_only",
        "automation_status": "MANUAL_ONLY",
        "adapter_status": "NOT_APPLICABLE",
        "manual_evidence_supported": True,
        "credential_env": [],
        "license_env": None,
        "terms": {
            "url": None,
            "checked_at": SOURCE_POLICY_CHECKED_AT,
            "review_status": "SOURCE_SPECIFIC_REVIEW_REQUIRED",
        },
        "url": None,
    },
}


def market_sources() -> list[dict[str, Any]]:
    return [
        {
            "source": source,
            **definition,
            "review_due_at": _review_due_at(definition).isoformat()
            if _review_due_at(definition)
            else None,
        }
        for source, definition in sorted(MARKET_SOURCES.items())
    ]


def _review_due_at(policy: Mapping[str, Any]) -> date | None:
    checked_at = policy.get("terms", {}).get("checked_at")
    if not checked_at:
        return None
    return date.fromisoformat(str(checked_at)) + timedelta(days=SOURCE_POLICY_REVIEW_DAYS)


def source_definition(source: str) -> dict[str, Any]:
    return MARKET_SOURCES.get(source, MARKET_SOURCES["other"])


def diagnose_source(
    source: str,
    *,
    mode: str,
    intended_use: str,
    environ: Mapping[str, str] | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    if source not in MARKET_SOURCES:
        raise ConfigError(f"未知行情来源: {source}", details={"source": source})
    if mode not in {"automatic", "manual"}:
        raise ConfigError(f"不支持的来源接入模式: {mode}")
    if intended_use not in {"internal", "public_display", "resale"}:
        raise ConfigError(f"不支持的行情用途: {intended_use}")

    policy = MARKET_SOURCES[source]
    environment = os.environ if environ is None else environ
    missing: list[str] = []
    warnings: list[str] = []
    source_status = "SOURCE_READY"
    ready = True
    review_due_at = _review_due_at(policy)
    policy_stale = bool(review_due_at and (today or date.today()) > review_due_at)

    if mode == "manual":
        ready = bool(policy["manual_evidence_supported"])
        source_status = "MANUAL_EVIDENCE_READY" if ready else "SOURCE_MANUAL_EVIDENCE_UNSUPPORTED"
        if policy_stale:
            warnings.append("来源政策复核日期已过；人工证据仍须由使用者重新确认用途与条款。")
    elif policy_stale:
        ready = False
        source_status = "SOURCE_POLICY_STALE"
        warnings.append("来源政策复核日期已过，自动访问保持关闭，需重新核验官方条款。")
    elif policy["automation_status"] == "PROHIBITED_WITHOUT_WRITTEN_PERMISSION":
        ready = False
        source_status = "SOURCE_AUTOMATION_PROHIBITED"
        warnings.append("该来源官方条款要求自动化访问取得明确书面许可。")
    elif policy["automation_status"] in {
        "TERMS_REVIEW_REQUIRED",
        "PUBLIC_RELEASE_REVIEW_REQUIRED",
        "MANUAL_ONLY",
    }:
        ready = False
        source_status = "SOURCE_TERMS_REVIEW_REQUIRED"
        warnings.append("尚未确认该来源允许自动化访问，只能使用人工证据或授权导出。")
    elif source == "watchcharts":
        for name in policy["credential_env"]:
            if not str(environment.get(name, "")).strip():
                missing.append(name)
        license_env = policy["license_env"]
        license_type = str(environment.get(license_env, "")).strip().lower()
        if not license_type:
            missing.append(license_env)
        if policy["credential_env"][0] in missing:
            ready = False
            source_status = "SOURCE_AUTH_REQUIRED"
        elif not license_type or not _license_satisfies(license_type, intended_use):
            ready = False
            source_status = "SOURCE_LICENSE_NOT_CONFIRMED"
            warnings.append("需要由数据订阅者确认当前 WatchCharts license 覆盖目标使用方式。")

    return {
        "registry_version": SOURCE_REGISTRY_VERSION,
        "source": source,
        "display_name": policy["display_name"],
        "requested_mode": mode,
        "intended_use": intended_use,
        "source_status": source_status,
        "ready": ready,
        "missing": missing,
        "automation_status": policy["automation_status"],
        "adapter_status": policy["adapter_status"],
        "manual_evidence_supported": policy["manual_evidence_supported"],
        "terms": policy["terms"],
        "review_due_at": review_due_at.isoformat() if review_due_at else None,
        "policy_stale": policy_stale,
        "warnings": warnings,
        "credentials_present": bool(policy["credential_env"]) and not any(
            name in missing for name in policy["credential_env"]
        ),
        "license_attested": bool(policy["license_env"]) and policy["license_env"] not in missing,
        "secret_values_returned": False,
    }


def _license_satisfies(license_type: str, intended_use: str) -> bool:
    levels = {"internal": 0, "distribution": 1, "resale": 2}
    required = {"internal": 0, "public_display": 1, "resale": 2}[intended_use]
    return license_type in levels and levels[license_type] >= required


def _normalized_reference(reference: str) -> str:
    return "".join(char for char in str(reference).upper().strip() if char.isalnum() or char == "-")


class WatchChartsCollector:
    base_url = "https://api.watchcharts.com"

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        timeout: float = 30.0,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._owns_client = client is None
        self.sleeper = sleeper
        self.client = client or httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "HKPreOwnedRolexMonitoring/0.2 (official WatchCharts API)"},
        )

    def collect(
        self,
        *,
        reference: str,
        target_year: int,
        region: str,
        completeness: str,
        api_key: str,
        license_type: str,
        intended_use: str,
        now: datetime | None = None,
    ) -> tuple[MarketPacket, list[str]]:
        normalized_reference = _normalized_reference(reference)
        if not normalized_reference:
            raise ConfigError("Rolex reference 不能为空")
        if not 1900 <= target_year <= 2200:
            raise ConfigError("target_year 必须在 1900–2200 之间")
        if region not in {"APAC", "GLOBAL"}:
            raise ConfigError("WatchCharts 官方 appraisal 仅支持 APAC 或 GLOBAL 口径")
        if completeness not in {"full_set", "watch_only"}:
            raise ConfigError("WatchCharts appraisal 必须明确 full_set 或 watch_only")

        diagnosis = diagnose_source(
            "watchcharts",
            mode="automatic",
            intended_use=intended_use,
            environ={
                "WATCHCHARTS_API_KEY": api_key,
                "WATCHCHARTS_LICENSE": license_type,
            },
        )
        if not diagnosis["ready"]:
            self._raise_not_ready(diagnosis)

        collected_at = now or datetime.now(timezone.utc)
        if collected_at.tzinfo is None or collected_at.utcoffset() is None:
            raise ConfigError("采集时间必须包含时区")
        headers = {"x-api-key": api_key}
        search = self._get_json(
            "/v3/search/watch",
            headers=headers,
            params={
                "brand_name": "rolex",
                "reference": normalized_reference,
                "exact_match": "true",
            },
        )
        uuid = self._select_uuid(search, normalized_reference)
        self.sleeper(1.0)
        appraisal = self._get_json(
            "/v3/watch/appraisal",
            headers=headers,
            params={
                "uuid": uuid,
                "condition": "used",
                "delivery_contents": (
                    "watch_with_box_and_papers" if completeness == "full_set" else "watch_only"
                ),
                "region": "as" if region == "APAC" else "g",
                "type": "market",
                "currency": "HKD",
            },
        )
        price = appraisal.get("price")
        try:
            price_hkd = Decimal(str(price))
        except Exception as exc:
            raise SourceSchemaChanged(
                "WatchCharts appraisal 缺少可解析的 HKD 价格",
                details={"field": "price"},
            ) from exc
        if price_hkd <= 0:
            raise SourceSchemaChanged(
                "WatchCharts appraisal 返回非正价格",
                details={"field": "price"},
            )

        evidence_payload = {"search": search, "appraisal": appraisal}
        canonical = json.dumps(
            evidence_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        evidence_sha256 = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
        response_date = str(appraisal.get("date") or collected_at.date().isoformat())
        observation = MarketObservation(
            observation_id=f"watchcharts-{uuid}-{response_date}-market",
            source="watchcharts",
            source_listing_id=f"{uuid}:{response_date}:market",
            independence_group="watchcharts",
            rolex_reference=normalized_reference,
            region=region,
            basis="market_estimate",
            price_hkd=price_hkd,
            observed_at=collected_at,
            year=None,
            condition="unknown",
            completeness=completeness,
            evidence_status="verified",
            acquisition_method="official_api",
            evidence_url=f"https://api.watchcharts.com/v3/watch/appraisal?uuid={uuid}",
            evidence_note=(
                "WatchCharts 官方 API 的型号级 used appraisal；该接口不接收生产年份，"
                "因此不得冒充目标年份样本。"
            ),
            evidence_verified_at=collected_at,
            evidence_sha256=evidence_sha256,
        )
        packet = MarketPacket(
            packet_id=f"watchcharts-{normalized_reference}-{collected_at.date().isoformat()}",
            as_of=collected_at,
            collection_context={
                "source": "watchcharts",
                "requested_target_year": target_year,
                "requested_region": region,
                "source_year_semantics": "MODEL_LEVEL_NO_PRODUCTION_YEAR",
                "license_attestation": license_type,
                "intended_use": intended_use,
                "raw_response_persisted": False,
            },
            observations=[observation],
        )
        return packet, ["WATCHCHARTS_MODEL_LEVEL_NO_PRODUCTION_YEAR"]

    @staticmethod
    def _raise_not_ready(diagnosis: dict[str, Any]) -> None:
        status = diagnosis["source_status"]
        details = {
            "source": diagnosis["source"],
            "source_status": status,
            "missing": diagnosis["missing"],
        }
        if status == "SOURCE_AUTH_REQUIRED":
            raise SourceAuthRequired("WatchCharts API 凭证未配置", details=details)
        if status == "SOURCE_LICENSE_NOT_CONFIRMED":
            raise SourceLicenseNotConfirmed("WatchCharts license 未确认或不足", details=details)
        if status == "SOURCE_AUTOMATION_PROHIBITED":
            raise SourceAutomationProhibited("来源不允许默认自动采集", details=details)
        if status == "SOURCE_POLICY_STALE":
            raise SourcePolicyStale("来源政策复核日期已过，自动访问保持关闭", details=details)
        raise SourceTermsReviewRequired("来源条款尚未完成审查", details=details)

    def _get_json(
        self,
        path: str,
        *,
        headers: dict[str, str],
        params: dict[str, str],
    ) -> dict[str, Any]:
        try:
            response = self.client.get(path, headers=headers, params=params)
        except httpx.HTTPError as exc:
            raise SourceApiAccessDenied(f"WatchCharts API 请求失败: {exc}") from exc
        if response.status_code == 429:
            raise SourceRateLimited(
                "WatchCharts API 达到速率或 credits 限制",
                details={"http_status": 429},
            )
        if response.status_code in {401, 403}:
            raise SourceApiAccessDenied(
                "WatchCharts API 拒绝访问；请检查 API key、订阅级别和 data credits",
                details={"http_status": response.status_code},
            )
        if response.status_code != 200:
            raise SourceApiAccessDenied(
                f"WatchCharts API 返回 HTTP {response.status_code}",
                details={"http_status": response.status_code},
            )
        try:
            payload = response.json()
        except Exception as exc:
            raise SourceSchemaChanged("WatchCharts API 返回无法解析的 JSON") from exc
        if not isinstance(payload, dict):
            raise SourceSchemaChanged("WatchCharts API 返回结构不是对象")
        return payload

    @staticmethod
    def _select_uuid(search: dict[str, Any], reference: str) -> str:
        results = search.get("results")
        if search.get("success") is not True or not isinstance(results, list):
            raise SourceSchemaChanged("WatchCharts 搜索响应缺少 results")
        target = _normalized_reference(reference)
        for result in results:
            if not isinstance(result, dict):
                continue
            if _normalized_reference(result.get("model", "")) == target and result.get("uuid"):
                return str(result["uuid"])
            for variant in result.get("variants") or []:
                if (
                    isinstance(variant, dict)
                    and _normalized_reference(variant.get("model", "")) == target
                    and variant.get("uuid")
                ):
                    return str(variant["uuid"])
        raise SourceSchemaChanged(
            "WatchCharts 未返回完全匹配的 Rolex reference",
            details={"reference": reference},
        )

    def close(self) -> None:
        if self._owns_client:
            self.client.close()
