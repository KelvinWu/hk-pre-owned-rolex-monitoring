from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest

from inventory_sentinel.errors import SourceRateLimited
from inventory_sentinel.market_sources import (
    WatchChartsCollector,
    diagnose_source,
    market_sources,
)


def test_source_registry_exposes_machine_readable_access_policy() -> None:
    sources = {item["source"]: item for item in market_sources()}

    watchcharts = sources["watchcharts"]
    assert watchcharts["automation_status"] == "SUPPORTED_WITH_USER_CREDENTIALS"
    assert watchcharts["credential_env"] == ["WATCHCHARTS_API_KEY"]
    assert watchcharts["license_env"] == "WATCHCHARTS_LICENSE"
    assert watchcharts["terms"]["checked_at"] == "2026-07-13"
    assert watchcharts["terms"]["url"].startswith("https://watchcharts.com/")

    wristcheck = sources["wristcheck-listings"]
    assert wristcheck["automation_status"] == "PROHIBITED_WITHOUT_WRITTEN_PERMISSION"
    assert wristcheck["manual_evidence_supported"] is True

    oriental = sources["orientalwatch-inventory"]
    assert oriental["tier"] == "INVENTORY"
    assert oriental["automation_status"] == "PUBLIC_RELEASE_REVIEW_REQUIRED"
    assert oriental["adapter_status"] == "IMPLEMENTED_FIXTURE_TESTED_POLICY_REVIEW_PENDING"


def test_source_doctor_reports_missing_secret_without_leaking_it() -> None:
    diagnosis = diagnose_source(
        "watchcharts",
        mode="automatic",
        intended_use="internal",
        environ={},
    )

    assert diagnosis["ready"] is False
    assert diagnosis["source_status"] == "SOURCE_AUTH_REQUIRED"
    assert diagnosis["missing"] == ["WATCHCHARTS_API_KEY", "WATCHCHARTS_LICENSE"]
    assert "credential_value" not in json.dumps(diagnosis).lower()


def test_source_doctor_requires_sufficient_license_for_public_display() -> None:
    internal = diagnose_source(
        "watchcharts",
        mode="automatic",
        intended_use="public_display",
        environ={
            "WATCHCHARTS_API_KEY": "secret-value",
            "WATCHCHARTS_LICENSE": "internal",
        },
    )
    distribution = diagnose_source(
        "watchcharts",
        mode="automatic",
        intended_use="public_display",
        environ={
            "WATCHCHARTS_API_KEY": "secret-value",
            "WATCHCHARTS_LICENSE": "distribution",
        },
    )

    assert internal["source_status"] == "SOURCE_LICENSE_NOT_CONFIRMED"
    assert internal["ready"] is False
    assert distribution["source_status"] == "SOURCE_READY"
    assert distribution["ready"] is True
    assert "secret-value" not in json.dumps(distribution)


def test_source_doctor_fails_closed_for_prohibited_or_unreviewed_automation() -> None:
    wristcheck = diagnose_source(
        "wristcheck-listings", mode="automatic", intended_use="internal", environ={}
    )
    chrono24 = diagnose_source(
        "chrono24-valuation", mode="automatic", intended_use="internal", environ={}
    )

    assert wristcheck["source_status"] == "SOURCE_AUTOMATION_PROHIBITED"
    assert wristcheck["ready"] is False
    assert chrono24["source_status"] == "SOURCE_TERMS_REVIEW_REQUIRED"
    assert chrono24["ready"] is False


def test_watchcharts_official_api_collection_produces_attested_model_context() -> None:
    seen_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        assert request.headers["x-api-key"] == "secret-value"
        if request.url.path == "/v3/search/watch":
            assert request.url.params["brand_name"] == "rolex"
            assert request.url.params["reference"] == "126334"
            assert request.url.params["exact_match"] == "true"
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "results": [
                        {
                            "uuid": "7901c9d7-22f9-4783-b5ce-48ee079a62ab",
                            "model": "126334",
                            "variants": [],
                        }
                    ],
                },
            )
        if request.url.path == "/v3/watch/appraisal":
            assert request.url.params["region"] == "as"
            assert request.url.params["condition"] == "used"
            assert request.url.params["delivery_contents"] == "watch_with_box_and_papers"
            assert request.url.params["currency"] == "HKD"
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "brand": "Rolex",
                    "collection": "Datejust",
                    "model": "126334",
                    "date": "2026-07-13",
                    "price": 105000,
                    "volatility": 0.051,
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://api.watchcharts.com",
    )
    sleeps: list[float] = []
    collector = WatchChartsCollector(client=client, sleeper=sleeps.append)
    packet, warnings = collector.collect(
        reference="126334",
        target_year=2021,
        region="APAC",
        completeness="full_set",
        api_key="secret-value",
        license_type="internal",
        intended_use="internal",
        now=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc),
    )

    assert len(seen_requests) == 2
    assert sleeps == [1.0]
    observation = packet.observations[0]
    assert observation.source == "watchcharts"
    assert observation.rolex_reference == "126334"
    assert observation.region == "APAC"
    assert observation.basis == "market_estimate"
    assert observation.price_hkd == 105000
    assert observation.year is None
    assert observation.condition == "unknown"
    assert observation.evidence_status == "verified"
    assert observation.acquisition_method == "official_api"
    assert observation.evidence_sha256.startswith("sha256:")
    assert "secret-value" not in packet.model_dump_json()
    serialized = json.loads(packet.model_dump_json())
    assert isinstance(serialized["observations"][0]["price_hkd"], (int, float))
    assert isinstance(serialized["comparison"]["reference_band_percent"], (int, float))
    assert "WATCHCHARTS_MODEL_LEVEL_NO_PRODUCTION_YEAR" in warnings
    assert packet.collection_context["requested_target_year"] == 2021


def test_watchcharts_rate_limit_is_structured() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "Too many requests"})

    collector = WatchChartsCollector(
        client=httpx.Client(
            transport=httpx.MockTransport(handler),
            base_url="https://api.watchcharts.com",
        )
    )
    with pytest.raises(SourceRateLimited) as exc_info:
        collector.collect(
            reference="126334",
            target_year=2021,
            region="APAC",
            completeness="full_set",
            api_key="secret-value",
            license_type="internal",
            intended_use="internal",
            now=datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc),
        )
    assert exc_info.value.code == "SOURCE_RATE_LIMITED"
