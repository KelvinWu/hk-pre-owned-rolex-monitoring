from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from inventory_sentinel.market_intelligence import compare_snapshot, market_sources
from inventory_sentinel.models import InventoryItem, MarketPacket


AS_OF = "2026-07-13T12:00:00+08:00"


def observation(
    observation_id: str,
    source: str,
    price: int,
    *,
    region: str = "HK",
    basis: str = "asking_price",
    observed_at: str = "2026-07-13T10:00:00+08:00",
    year: int | None = 2020,
    condition: str = "excellent",
    completeness: str = "full_set",
    evidence_status: str = "verified",
    acquisition_method: str | None = None,
    independence_group: str | None = None,
    underlying_listing_id: str | None = None,
    dealer_name: str | None = None,
) -> dict:
    row = {
        "observation_id": observation_id,
        "source": source,
        "source_listing_id": observation_id,
        "rolex_reference": "126334",
        "region": region,
        "basis": basis,
        "price_hkd": price,
        "observed_at": observed_at,
        "year": year,
        "condition": condition,
        "completeness": completeness,
        "evidence_url": f"https://market-evidence.test/{observation_id}",
        "evidence_status": evidence_status,
        "acquisition_method": acquisition_method
        or ("fixture" if evidence_status == "fixture" else "manual_url"),
        "independence_group": independence_group,
        "underlying_listing_id": underlying_listing_id,
        "dealer_name": dealer_name,
    }
    if evidence_status == "verified":
        row["evidence_verified_at"] = "2026-07-13T11:00:00+08:00"
        row["evidence_sha256"] = "sha256:" + "a" * 64
    return row


def target(
    price: int = 94000,
    *,
    year: int | None = 2020,
) -> InventoryItem:
    return InventoryItem(
        stable_id="LOT-126334",
        source_id="LOT-126334",
        title="Datejust 41",
        reference="126334",
        year=year,
        price=Decimal(price),
        currency="HKD",
    )


def test_hk_asking_cohort_is_primary_and_not_mixed_with_global_valuation() -> None:
    rows = [
        observation("wc", "watchcharts", 98000, region="GLOBAL", basis="market_estimate"),
        observation("wrist", "wristcheck-listings", 102000),
        observation("28-a", "28watches", 99000),
        observation("28-b", "28watches", 101000),
        observation("mainland", "mainland-marketplace", 70000, region="MAINLAND_CN"),
        observation(
            "stale",
            "kens-watches",
            50000,
            observed_at="2025-01-01T00:00:00+08:00",
        ),
    ]
    packet = MarketPacket.model_validate(
        {"schema_version": 1, "packet_id": "packet-1", "as_of": AS_OF, "observations": rows}
    )
    comparisons, warnings, stats = compare_snapshot([target()], packet)
    result = comparisons[0]
    assert result["benchmark_status"] == "VERIFIED"
    assert result["confidence"] == "MEDIUM"
    assert result["reference_price_hkd"] == "101000.00"
    assert result["aggregation_method"] == "SOURCE_YEAR_BALANCED_MEAN"
    assert result["target_premium_percent"] == "-6.93"
    assert result["position"] == "BELOW_REFERENCE"
    assert result["price_basis"] == "HK_ASKING"
    assert result["product_identity"]["rolex_reference"] == "126334"
    assert result["product_identity"]["oriental_lot_number"] == "LOT-126334"
    assert "Rolex Datejust 41" in result["product_identity"]["display_name"]
    assert result["trusted_source_count"] == 2
    assert result["primary_cohort_id"] == "HK:ASKING"
    assert {row["cohort_id"] for row in result["reference_cohorts"]} == {
        "GLOBAL:VALUATION",
        "HK:ASKING",
    }
    assert result["context_only_sources"][0]["source"] == "mainland-marketplace"
    assert "TIER_C_CONTEXT_EXCLUDED_FROM_REFERENCE" in result["comparability_flags"]
    assert stats["stale_observations_excluded"] == 1
    assert "已排除 1 条" in warnings[0]


def test_one_trusted_source_cannot_claim_fair_reference() -> None:
    packet = MarketPacket.model_validate(
        {
            "schema_version": 1,
            "packet_id": "packet-2",
            "as_of": AS_OF,
            "observations": [
                observation("wrist", "wristcheck-listings", 102000),
                observation("mainland", "mainland-marketplace", 80000, region="MAINLAND_CN"),
            ],
        }
    )
    comparisons, warnings, stats = compare_snapshot([target()], packet)
    result = comparisons[0]
    assert result["benchmark_status"] == "INSUFFICIENT_SOURCES"
    assert result["confidence"] == "LOW"
    assert result["position"] == "INSUFFICIENT_EVIDENCE"
    assert result["target_premium_percent"] is None
    assert stats["verified_benchmarks"] == 0
    assert any("独立可信来源门槛" in warning for warning in warnings)


def test_context_only_data_is_not_described_as_asking_reference() -> None:
    packet = MarketPacket.model_validate(
        {
            "schema_version": 1,
            "packet_id": "packet-context-only",
            "as_of": AS_OF,
            "observations": [
                observation("mainland", "mainland-marketplace", 80000, region="MAINLAND_CN"),
            ],
        }
    )
    comparisons, _, _ = compare_snapshot([target()], packet)
    result = comparisons[0]
    assert result["benchmark_status"] == "INSUFFICIENT_SOURCES"
    assert result["price_basis"] == "NO_REFERENCE_DATA"
    assert result["reference_price_hkd"] is None
    assert result["context_only_sources"][0]["source"] == "mainland-marketplace"


def test_missing_reference_and_non_hkd_target_are_not_silently_compared() -> None:
    packet = MarketPacket.model_validate(
        {
            "schema_version": 1,
            "packet_id": "packet-3",
            "as_of": AS_OF,
            "observations": [
                observation("watchfinder", "watchfinder-hk", 98000),
                observation("wrist", "wristcheck-listings", 102000),
            ],
        }
    )
    no_reference = InventoryItem(stable_id="NO-REF", source_id="NO-REF", price=Decimal(1), currency="HKD")
    non_hkd = target()
    non_hkd = non_hkd.model_copy(update={"currency": "USD"})
    comparisons, warnings, stats = compare_snapshot([no_reference, non_hkd], packet)
    assert len(comparisons) == 1
    assert comparisons[0]["position"] == "TARGET_PRICE_UNAVAILABLE"
    assert stats["missing_reference_items"] == 1
    assert any("没有 Rolex reference" in warning for warning in warnings)


def test_market_packet_requires_unique_ids_timezone_and_evidence() -> None:
    row = observation("duplicate", "watchcharts", 98000, region="GLOBAL", basis="market_estimate")
    with pytest.raises(ValidationError, match="observation_id 不得重复"):
        MarketPacket.model_validate(
            {"schema_version": 1, "packet_id": "bad", "as_of": AS_OF, "observations": [row, row]}
        )
    without_evidence = {**row, "observation_id": "no-evidence", "source_listing_id": None}
    without_evidence.pop("evidence_url")
    with pytest.raises(ValidationError, match="evidence_url 或 evidence_note"):
        MarketPacket.model_validate(
            {"schema_version": 1, "packet_id": "bad-2", "as_of": AS_OF, "observations": [without_evidence]}
        )
    with pytest.raises(ValidationError, match="as_of 必须包含时区"):
        MarketPacket.model_validate(
            {"schema_version": 1, "packet_id": "bad-3", "as_of": "2026-07-13T12:00:00", "observations": [row]}
        )
    verified_without_attestation = observation("missing-attestation", "watchfinder-hk", 98000)
    verified_without_attestation.pop("evidence_sha256")
    with pytest.raises(ValidationError, match="verified 行情必须提供"):
        MarketPacket.model_validate(
            {
                "schema_version": 1,
                "packet_id": "bad-attestation",
                "as_of": AS_OF,
                "observations": [verified_without_attestation],
            }
        )


def test_source_catalog_exposes_access_policy() -> None:
    sources = {item["source"]: item for item in market_sources()}
    assert sources["watchcharts"]["access"] == "official_api_with_api_key"
    assert sources["wristcheck-listings"]["tier"] == "B"
    assert sources["mainland-marketplace"]["tier"] == "C"


def test_same_reference_within_two_year_window_enters_benchmark() -> None:
    packet = MarketPacket.model_validate(
        {
            "schema_version": 1,
            "packet_id": "year-window-key",
            "as_of": AS_OF,
            "observations": [
                observation("wf-minus-two", "watchfinder-hk", 100000, year=2019),
                observation("wf-plus-two", "watchfinder-hk", 110000, year=2023, condition="very_good"),
                observation("wrist-exact", "wristcheck-listings", 102000, year=2021),
                observation("too-old", "wristcheck-listings", 70000, year=2018),
                observation("too-new", "wristcheck-listings", 80000, year=2024),
            ],
        }
    )
    comparisons, _, stats = compare_snapshot([target(year=2021)], packet)
    result = comparisons[0]
    assert result["comparison_key"] == {
        "rolex_reference": "126334",
        "target_year": 2021,
        "year_from": 2019,
        "year_to": 2023,
    }
    assert result["match_policy"] == "EXACT_REFERENCE_WITH_YEAR_WINDOW"
    assert result["benchmark_status"] == "VERIFIED"
    assert result["reference_price_hkd"] == "103500.00"
    assert result["matched_observation_count"] == 3
    assert result["excluded_non_comparable_observation_count"] == 2
    assert "OUTSIDE_YEAR_WINDOW_EXCLUDED" in result["comparability_flags"]
    assert stats["non_comparable_observations_excluded"] == 2


def test_good_condition_is_preferred_without_becoming_a_hard_key() -> None:
    packet = MarketPacket.model_validate(
        {
            "schema_version": 1,
            "packet_id": "condition-preference",
            "as_of": AS_OF,
            "observations": [
                observation("wf-excellent", "watchfinder-hk", 100000, condition="excellent"),
                observation("wf-good", "watchfinder-hk", 80000, condition="good"),
                observation("hk-very-good", "wristcheck-listings", 102000, condition="very_good"),
                observation("hk-unknown", "wristcheck-listings", 70000, condition="unknown"),
            ],
        }
    )
    comparisons, warnings, _ = compare_snapshot([target()], packet)
    result = comparisons[0]
    assert result["benchmark_status"] == "VERIFIED"
    assert result["reference_price_hkd"] == "101000.00"
    assert result["condition_policy"] == "PREFER_EXCELLENT_VERY_GOOD_PER_SOURCE"
    assert result["condition_deprioritized_observation_count"] == 2
    assert "PREFERRED_CONDITION_USED" in result["comparability_flags"]
    assert not warnings


def test_good_or_unknown_condition_is_used_as_fallback_when_needed() -> None:
    packet = MarketPacket.model_validate(
        {
            "schema_version": 1,
            "packet_id": "condition-fallback",
            "as_of": AS_OF,
            "observations": [
                observation("wc-unknown", "watchcharts", 100000, condition="unknown"),
                observation("hk-good", "watchfinder-hk", 102000, condition="good"),
            ],
        }
    )
    comparisons, warnings, _ = compare_snapshot([target()], packet)
    result = comparisons[0]
    assert result["benchmark_status"] == "VERIFIED"
    assert result["reference_price_hkd"] == "101000.00"
    assert "CONDITION_FALLBACK_USED" in result["comparability_flags"]
    assert not warnings


def test_unknown_target_year_cannot_form_year_window_benchmark() -> None:
    packet = MarketPacket.model_validate(
        {
            "schema_version": 1,
            "packet_id": "unknown-target-year",
            "as_of": AS_OF,
            "observations": [
                observation("wc", "watchcharts", 100000),
                observation("hk", "watchfinder-hk", 102000),
            ],
        }
    )
    comparisons, warnings, stats = compare_snapshot([target(year=None)], packet)
    result = comparisons[0]
    assert result["benchmark_status"] == "TARGET_YEAR_UNKNOWN"
    assert result["position"] == "TARGET_YEAR_UNKNOWN"
    assert result["reference_price_hkd"] is None
    assert "TARGET_YEAR_UNKNOWN" in result["comparability_flags"]
    assert stats["verified_benchmarks"] == 0
    assert any("缺少年份" in warning for warning in warnings)


def test_source_balanced_arithmetic_mean_is_used_instead_of_listing_median() -> None:
    packet = MarketPacket.model_validate(
        {
            "schema_version": 1,
            "packet_id": "source-balanced-mean",
            "as_of": AS_OF,
            "observations": [
                observation("wf-a", "watchfinder-hk", 90000),
                observation("wf-b", "watchfinder-hk", 100000),
                observation("wf-c", "watchfinder-hk", 140000),
                observation("hk", "wristcheck-listings", 100000),
            ],
        }
    )
    comparisons, _, _ = compare_snapshot([target()], packet)
    result = comparisons[0]
    assert result["source_summaries"][0]["source_mean_hkd"] in {"100000.00", "110000.00"}
    assert {row["source_mean_hkd"] for row in result["source_summaries"]} == {
        "100000.00",
        "110000.00",
    }
    assert result["reference_price_hkd"] == "105000.00"
    assert "OUTLIER_PRICE_DETECTED" in result["comparability_flags"]


def test_fixture_or_unverified_evidence_can_never_form_verified_reference() -> None:
    packet = MarketPacket.model_validate(
        {
            "schema_version": 1,
            "packet_id": "fixture-only",
            "as_of": AS_OF,
            "observations": [
                observation("fixture-a", "watchfinder-hk", 98000, evidence_status="fixture"),
                observation("fixture-b", "wristcheck-listings", 102000, evidence_status="fixture"),
            ],
        }
    )
    comparisons, _, stats = compare_snapshot([target()], packet)
    result = comparisons[0]
    assert result["benchmark_status"] == "DEMO_ONLY"
    assert result["reference_price_hkd"] is None
    assert result["trusted_source_count"] == 0
    assert len(result["fixture_evidence_sources"]) == 2
    assert stats["demo_only_benchmarks"] == 1


def test_two_price_basis_cohorts_with_one_source_each_are_not_combined() -> None:
    packet = MarketPacket.model_validate(
        {
            "schema_version": 1,
            "packet_id": "mixed-basis",
            "as_of": AS_OF,
            "observations": [
                observation("hk-asking", "watchfinder-hk", 100000),
                observation(
                    "global-valuation",
                    "watchcharts",
                    90000,
                    region="GLOBAL",
                    basis="market_estimate",
                ),
            ],
        }
    )
    comparisons, _, _ = compare_snapshot([target()], packet)
    result = comparisons[0]
    assert result["benchmark_status"] == "INSUFFICIENT_SOURCES"
    assert result["reference_price_hkd"] is None
    assert {row["trusted_source_count"] for row in result["reference_cohorts"]} == {1}


def test_years_are_balanced_before_source_and_cross_source_mean() -> None:
    packet = MarketPacket.model_validate(
        {
            "schema_version": 1,
            "packet_id": "year-balanced",
            "as_of": AS_OF,
            "observations": [
                observation("wf-2019-a", "watchfinder-hk", 90000, year=2019),
                observation("wf-2019-b", "watchfinder-hk", 110000, year=2019),
                observation("wf-2020", "watchfinder-hk", 200000, year=2020),
                observation("wrist-2020", "wristcheck-listings", 100000, year=2020),
            ],
        }
    )
    comparisons, _, _ = compare_snapshot([target(year=2020)], packet)
    result = comparisons[0]
    watchfinder = next(
        row for row in result["source_summaries"] if row["source"] == "watchfinder-hk"
    )
    assert watchfinder["source_mean_hkd"] == "150000.00"
    assert watchfinder["year_summaries"] == [
        {"year": 2019, "observation_count": 2, "year_mean_hkd": "100000.00"},
        {"year": 2020, "observation_count": 1, "year_mean_hkd": "200000.00"},
    ]
    assert result["reference_price_hkd"] == "125000.00"


def test_unworn_is_reported_as_upper_bound_context_not_primary_condition() -> None:
    packet = MarketPacket.model_validate(
        {
            "schema_version": 1,
            "packet_id": "unworn-context",
            "as_of": AS_OF,
            "observations": [
                observation("wf-unworn", "watchfinder-hk", 130000, condition="unworn"),
                observation("wrist-excellent", "wristcheck-listings", 100000),
                observation("28-very-good", "28watches", 102000, condition="very_good"),
            ],
        }
    )
    comparisons, _, _ = compare_snapshot([target()], packet)
    result = comparisons[0]
    assert result["benchmark_status"] == "VERIFIED"
    assert result["reference_price_hkd"] == "101000.00"
    assert result["unworn_context_sources"][0]["source"] == "watchfinder-hk"
    assert "UNWORN_CONTEXT_EXCLUDED_FROM_REFERENCE" in result["comparability_flags"]


def test_independence_group_prevents_cross_platform_double_counting() -> None:
    packet = MarketPacket.model_validate(
        {
            "schema_version": 1,
            "packet_id": "cross-post",
            "as_of": AS_OF,
            "observations": [
                observation(
                    "platform-a",
                    "watchfinder-hk",
                    100000,
                    independence_group="dealer-a",
                    underlying_listing_id="dealer-a-126334-2020",
                ),
                observation(
                    "platform-b",
                    "wristcheck-listings",
                    100000,
                    independence_group="dealer-a",
                    underlying_listing_id="dealer-a-126334-2020",
                ),
            ],
        }
    )
    comparisons, _, stats = compare_snapshot([target()], packet)
    result = comparisons[0]
    assert result["benchmark_status"] == "INSUFFICIENT_SOURCES"
    assert result["reference_cohorts"][0]["trusted_source_count"] == 1
    assert stats["duplicate_observations_excluded"] == 1
