from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from .market_sources import market_sources, source_definition
from .models import InventoryItem, MarketObservation, MarketPacket
from .presentation import product_identity

def _definition(source: str) -> dict[str, Any]:
    return source_definition(source)


PRICE_BASIS_GROUPS = {
    "asking_price": "ASKING",
    "dealer_quote": "ASKING",
    "market_estimate": "VALUATION",
    "transaction_index": "VALUATION",
    "auction_result": "AUCTION",
}

COHORT_PRIORITY = [
    (region, basis)
    for basis in ("ASKING", "VALUATION", "AUCTION")
    for region in ("HK", "APAC", "GLOBAL", "MAINLAND_CN")
]

PREFERRED_CONDITIONS = {"excellent", "very_good"}
FALLBACK_CONDITIONS = {"good", "unknown"}


def _mean(values: list[Decimal]) -> Decimal:
    return sum(values, Decimal(0)) / Decimal(len(values))


def _median(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal(2)


def _money(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")


def _percent(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")


def _independence_key(observation: MarketObservation) -> str:
    return observation.independence_group or observation.source


def _deduplicate_observations(
    observations: list[MarketObservation],
) -> tuple[list[MarketObservation], list[MarketObservation]]:
    ordered = sorted(
        observations,
        key=lambda row: (
            row.underlying_listing_id or f"unique:{row.observation_id}",
            0 if row.evidence_status == "verified" else 1,
            {"A": 0, "B": 1, "C": 2}.get(_definition(row.source)["tier"], 3),
            -row.observed_at.timestamp(),
            row.source,
            row.observation_id,
        ),
    )
    selected: list[MarketObservation] = []
    duplicates: list[MarketObservation] = []
    seen: set[str] = set()
    for row in ordered:
        if not row.underlying_listing_id:
            selected.append(row)
            continue
        key = row.underlying_listing_id.strip().lower()
        if key in seen:
            duplicates.append(row)
            continue
        seen.add(key)
        selected.append(row)
    return selected, duplicates


def _outlier_ids(
    rows: list[MarketObservation], warning_percent: Decimal
) -> list[str]:
    if len(rows) < 3:
        return []
    midpoint = _median([row.price_hkd for row in rows])
    if midpoint == 0:
        return []
    return [
        row.observation_id
        for row in rows
        if abs(row.price_hkd - midpoint) / midpoint * Decimal(100) >= warning_percent
    ]


def _summarize_sources(
    observations: list[MarketObservation],
    *,
    outlier_warning_percent: Decimal = Decimal("30"),
) -> list[dict[str, Any]]:
    grouped: dict[str, list[MarketObservation]] = defaultdict(list)
    for observation in observations:
        grouped[_independence_key(observation)].append(observation)
    summaries: list[dict[str, Any]] = []
    for independence_group, rows in sorted(grouped.items()):
        sources = sorted({row.source for row in rows})
        definitions = [_definition(source) for source in sources]
        tier = min((item["tier"] for item in definitions), default="C")
        by_year: dict[int, list[Decimal]] = defaultdict(list)
        for row in rows:
            if row.year is not None:
                by_year[row.year].append(row.price_hkd)
        year_summaries = [
            {
                "year": year,
                "observation_count": len(prices),
                "year_mean_hkd": _money(_mean(prices)),
            }
            for year, prices in sorted(by_year.items())
        ]
        source_mean = (
            _mean([Decimal(item["year_mean_hkd"]) for item in year_summaries])
            if year_summaries
            else _mean([row.price_hkd for row in rows])
        )
        outlier_observation_ids = _outlier_ids(rows, outlier_warning_percent)
        summaries.append(
            {
                "source": sources[0],
                "sources": sources,
                "independence_group": independence_group,
                "display_name": " / ".join(
                    _definition(source)["display_name"] for source in sources
                ),
                "tier": tier,
                "regions": sorted({row.region for row in rows}),
                "bases": sorted({row.basis for row in rows}),
                "years": sorted({row.year for row in rows if row.year is not None}),
                "conditions": sorted({row.condition for row in rows}),
                "completeness": sorted({row.completeness for row in rows}),
                "observation_count": len(rows),
                "year_summaries": year_summaries,
                "source_mean_hkd": _money(source_mean),
                "outlier_observation_ids": outlier_observation_ids,
                "evidence": [
                    {
                        "observation_id": row.observation_id,
                        "year": row.year,
                        "condition": row.condition,
                        "completeness": row.completeness,
                        "evidence_status": row.evidence_status,
                        "acquisition_method": row.acquisition_method,
                        "evidence_verified_at": (
                            row.evidence_verified_at.isoformat()
                            if row.evidence_verified_at
                            else None
                        ),
                        "evidence_sha256": row.evidence_sha256,
                        "evidence_url": row.evidence_url,
                        "evidence_note": row.evidence_note,
                    }
                    for row in rows
                ],
            }
        )
    return summaries


def _select_by_condition(
    observations: list[MarketObservation],
) -> tuple[
    list[MarketObservation],
    list[MarketObservation],
    list[MarketObservation],
    list[MarketObservation],
    set[str],
    set[str],
]:
    grouped: dict[str, list[MarketObservation]] = defaultdict(list)
    for observation in observations:
        grouped[_independence_key(observation)].append(observation)
    selected: list[MarketObservation] = []
    deprioritized: list[MarketObservation] = []
    unworn_context: list[MarketObservation] = []
    fair_context: list[MarketObservation] = []
    preferred_groups: set[str] = set()
    fallback_groups: set[str] = set()
    for group, rows in grouped.items():
        preferred = [row for row in rows if row.condition in PREFERRED_CONDITIONS]
        fallback = [row for row in rows if row.condition in FALLBACK_CONDITIONS]
        unworn_context.extend(row for row in rows if row.condition == "unworn")
        fair_context.extend(row for row in rows if row.condition == "fair")
        if preferred:
            chosen = preferred
            preferred_groups.add(group)
            deprioritized.extend(fallback)
        else:
            chosen = fallback
            if chosen:
                fallback_groups.add(group)
        selected.extend(chosen)
    return (
        selected,
        deprioritized,
        unworn_context,
        fair_context,
        preferred_groups,
        fallback_groups,
    )


def _build_reference_cohorts(
    observations: list[MarketObservation],
    *,
    minimum_sources: int,
    outlier_warning_percent: Decimal,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[MarketObservation]] = defaultdict(list)
    for row in observations:
        grouped[(row.region, PRICE_BASIS_GROUPS[row.basis])].append(row)
    cohorts: list[dict[str, Any]] = []
    for (region, basis_group), rows in sorted(grouped.items()):
        summaries = _summarize_sources(
            rows,
            outlier_warning_percent=outlier_warning_percent,
        )
        source_means = [Decimal(item["source_mean_hkd"]) for item in summaries]
        source_count = len(summaries)
        cohorts.append(
            {
                "cohort_id": f"{region}:{basis_group}",
                "region": region,
                "price_basis_group": basis_group,
                "trusted_source_count": source_count,
                "benchmark_status": (
                    "VERIFIED" if source_count >= minimum_sources else "INSUFFICIENT_SOURCES"
                ),
                "reference_price_hkd": _money(_mean(source_means)),
                "reference_low_hkd": _money(min(source_means)),
                "reference_high_hkd": _money(max(source_means)),
                "source_summaries": summaries,
            }
        )
    priority = {f"{region}:{basis}": index for index, (region, basis) in enumerate(COHORT_PRIORITY)}
    return sorted(cohorts, key=lambda row: priority.get(row["cohort_id"], 999))


def _market_summary_zh(comparisons: list[dict[str, Any]]) -> dict[str, Any]:
    verified = sum(row["benchmark_status"] == "VERIFIED" for row in comparisons)
    demo = sum(row["benchmark_status"] == "DEMO_ONLY" for row in comparisons)
    if verified == len(comparisons) and comparisons:
        headline = f"行情对比完成：{verified} 个商品均形成已验证参考。"
    elif verified:
        headline = f"行情对比部分完成：{verified}/{len(comparisons)} 个商品形成已验证参考。"
    elif demo:
        headline = "行情对比未形成已验证参考：当前只有示例数据。"
    else:
        headline = "行情对比未形成已验证参考：可比证据不足。"
    items: list[dict[str, Any]] = []
    for row in comparisons:
        identity = row["product_identity"]
        label = identity["display_name"]
        year_from = row["comparison_key"]["year_from"]
        year_to = row["comparison_key"]["year_to"]
        if row["benchmark_status"] == "VERIFIED":
            target = f"HK${Decimal(row['target_price_hkd']):,.0f}" if row["target_price_hkd"] else "价格未提供"
            reference = f"HK${Decimal(row['reference_price_hkd']):,.0f}"
            premium = Decimal(row["target_premium_percent"])
            relation = "低于" if premium < 0 else "高于" if premium > 0 else "等于"
            basis_label = {
                "HK_ASKING": "香港专业平台挂牌",
                "APAC_ASKING": "亚太专业平台挂牌",
                "GLOBAL_ASKING": "全球专业平台挂牌",
                "HK_VALUATION": "香港估值/交易指数",
                "APAC_VALUATION": "亚太估值/交易指数",
                "GLOBAL_VALUATION": "全球估值/交易指数",
                "HK_AUCTION": "香港拍卖结果",
                "APAC_AUCTION": "亚太拍卖结果",
                "GLOBAL_AUCTION": "全球拍卖结果",
            }.get(row["price_basis"], row["price_basis"])
            summary = (
                f"{label}：东方表行挂牌 {target}；{year_from}–{year_to} 年"
                f"{basis_label}好成色参考 {reference}；"
                f"{relation}参考价 {abs(premium):.2f}%；"
                f"依据 {row['trusted_source_count']} 个独立来源。"
            )
        elif row["benchmark_status"] == "DEMO_ONLY":
            summary = f"{label}：只有示例行情，不能形成已验证参考价。"
        elif row["benchmark_status"] == "TARGET_YEAR_UNKNOWN":
            summary = f"{label}：缺少目标年份，无法形成年份窗口。"
        elif row["benchmark_status"] == "UNVERIFIED_EVIDENCE":
            summary = f"{label}：只有未核验行情证据，不能形成已验证参考价。"
        else:
            summary = f"{label}：同口径独立可信来源不足。"
        items.append({"stable_id": row["stable_id"], "summary": summary})
    return {"headline": headline, "items": items}


def market_analysis_status(comparisons: list[dict[str, Any]]) -> str:
    verified = sum(row["benchmark_status"] == "VERIFIED" for row in comparisons)
    if comparisons and verified == len(comparisons):
        return "FULLY_VERIFIED"
    if verified:
        return "PARTIALLY_VERIFIED"
    if any(row["benchmark_status"] == "DEMO_ONLY" for row in comparisons):
        return "DEMO_ONLY"
    if any(row["benchmark_status"] == "UNVERIFIED_EVIDENCE" for row in comparisons):
        return "UNVERIFIED_EVIDENCE"
    return "INSUFFICIENT_EVIDENCE"


def market_human_summary(comparisons: list[dict[str, Any]]) -> dict[str, Any]:
    return _market_summary_zh(comparisons)


def compare_snapshot(
    items: list[InventoryItem], packet: MarketPacket
) -> tuple[list[dict[str, Any]], list[str], dict[str, int]]:
    warnings: list[str] = []
    valid_by_reference: dict[str, list[MarketObservation]] = defaultdict(list)
    stale = 0
    future = 0
    for observation in packet.observations:
        age = packet.as_of - observation.observed_at
        if age < -timedelta(days=1):
            future += 1
            continue
        if age > timedelta(days=packet.comparison.max_age_days):
            stale += 1
            continue
        valid_by_reference[observation.rolex_reference].append(observation)

    if stale:
        warnings.append(f"已排除 {stale} 条超过 {packet.comparison.max_age_days} 天的行情")
    if future:
        warnings.append(f"已排除 {future} 条时间晚于 Market Packet as_of 的行情")

    comparisons: list[dict[str, Any]] = []
    missing_reference = 0
    unavailable = 0
    target_year_unknown = 0
    non_comparable_excluded = 0
    condition_deprioritized = 0
    duplicate_excluded = 0
    demo_only = 0
    unverified_only = 0
    for item in sorted(items, key=lambda row: row.stable_id):
        if not item.reference:
            missing_reference += 1
            continue
        reference = "".join(
            char for char in str(item.reference).strip().upper() if char.isalnum() or char == "-"
        )
        target_year = item.year
        year_window = packet.comparison.year_window
        year_from = target_year - year_window if target_year is not None else None
        year_to = target_year + year_window if target_year is not None else None
        flags: list[str] = []
        candidate_observations = valid_by_reference.get(reference, [])
        year_eligible = (
            [
                row
                for row in candidate_observations
                if row.year is not None and year_from <= row.year <= year_to
            ]
            if target_year is not None and year_from is not None and year_to is not None
            else []
        )
        non_comparable = [row for row in candidate_observations if row not in year_eligible]
        non_comparable_excluded += len(non_comparable)
        if target_year is None:
            flags.append("TARGET_YEAR_UNKNOWN")
        if any(row.year is None for row in candidate_observations):
            flags.append("OBSERVATION_YEAR_UNKNOWN_EXCLUDED")
        if target_year is not None and any(
            row.year is not None and not (year_from <= row.year <= year_to)
            for row in candidate_observations
        ):
            flags.append("OUTSIDE_YEAR_WINDOW_EXCLUDED")

        fixture_evidence = [row for row in year_eligible if row.evidence_status == "fixture"]
        unverified_evidence = [
            row for row in year_eligible if row.evidence_status == "unverified"
        ]
        verified_evidence = [row for row in year_eligible if row.evidence_status == "verified"]
        trusted_candidates = [
            row for row in verified_evidence if _definition(row.source)["tier"] in {"A", "B"}
        ]
        contextual = [
            row for row in verified_evidence if _definition(row.source)["tier"] == "C"
        ]
        (
            trusted,
            deprioritized,
            unworn_context,
            fair_context,
            preferred_groups,
            fallback_groups,
        ) = _select_by_condition(trusted_candidates)
        trusted, duplicates = _deduplicate_observations(trusted)
        duplicate_excluded += len(duplicates)
        cohorts = _build_reference_cohorts(
            trusted,
            minimum_sources=packet.comparison.minimum_independent_sources,
            outlier_warning_percent=packet.comparison.outlier_warning_percent,
        )
        condition_deprioritized += len(deprioritized)
        if preferred_groups:
            flags.append("PREFERRED_CONDITION_USED")
        if fallback_groups:
            flags.append("CONDITION_FALLBACK_USED")
        if unworn_context:
            flags.append("UNWORN_CONTEXT_EXCLUDED_FROM_REFERENCE")
        if fair_context:
            flags.append("FAIR_CONTEXT_EXCLUDED_FROM_REFERENCE")
        if fixture_evidence:
            flags.append("FIXTURE_EVIDENCE_EXCLUDED_FROM_REFERENCE")
        if unverified_evidence:
            flags.append("UNVERIFIED_EVIDENCE_EXCLUDED_FROM_REFERENCE")
        if duplicates:
            flags.append("CROSS_POST_DUPLICATE_EXCLUDED")
        if any(
            summary["outlier_observation_ids"]
            for cohort in cohorts
            for summary in cohort["source_summaries"]
        ):
            flags.append("OUTLIER_PRICE_DETECTED")
        primary = next(
            (cohort for cohort in cohorts if cohort["benchmark_status"] == "VERIFIED"),
            None,
        )
        summaries = primary["source_summaries"] if primary else []
        trusted_source_count = (
            primary["trusted_source_count"]
            if primary
            else max((cohort["trusted_source_count"] for cohort in cohorts), default=0)
        )
        target_usable = item.price is not None and (item.currency or "").upper() == "HKD"
        benchmark_verified = target_year is not None and primary is not None

        reference_price = Decimal(primary["reference_price_hkd"]) if primary else None
        premium = None
        position = (
            "INSUFFICIENT_EVIDENCE"
            if target_year is not None
            else "TARGET_YEAR_UNKNOWN"
        )
        if benchmark_verified and target_usable and reference_price is not None:
            premium = (item.price - reference_price) / reference_price * Decimal(100)
            band = packet.comparison.reference_band_percent
            if premium < -band:
                position = "BELOW_REFERENCE"
            elif premium > band:
                position = "ABOVE_REFERENCE"
            else:
                position = "WITHIN_REFERENCE_BAND"
        elif benchmark_verified and not target_usable:
            position = "TARGET_PRICE_UNAVAILABLE"

        tier_a_count = sum(summary["tier"] == "A" for summary in summaries)
        local_count = trusted_source_count if primary and primary["region"] in {"HK", "APAC"} else 0
        if target_year is None:
            confidence = "UNAVAILABLE"
            unavailable += 1
            target_year_unknown += 1
        elif not benchmark_verified:
            confidence = "LOW" if trusted_source_count else "UNAVAILABLE"
            unavailable += 1
        elif trusted_source_count >= 3 and tier_a_count >= 1 and local_count >= 1:
            confidence = "HIGH"
        else:
            confidence = "MEDIUM"

        price_basis = (
            f"{primary['region']}_{primary['price_basis_group']}"
            if primary
            else "NO_REFERENCE_DATA"
        )
        completeness = sorted(
            {
                value
                for summary in summaries
                for value in summary["completeness"]
            }
        )
        if len(completeness) > 1 or completeness == ["unknown"]:
            flags.append("COMPLETENESS_NOT_NORMALIZED")
        if contextual:
            flags.append("TIER_C_CONTEXT_EXCLUDED_FROM_REFERENCE")

        if target_year is None:
            benchmark_status = "TARGET_YEAR_UNKNOWN"
        elif primary:
            benchmark_status = "VERIFIED"
        elif cohorts:
            benchmark_status = "INSUFFICIENT_SOURCES"
        elif fixture_evidence:
            benchmark_status = "DEMO_ONLY"
            demo_only += 1
        elif unverified_evidence:
            benchmark_status = "UNVERIFIED_EVIDENCE"
            unverified_only += 1
        else:
            benchmark_status = "INSUFFICIENT_SOURCES"

        primary_source_means = [Decimal(row["source_mean_hkd"]) for row in summaries]
        comparisons.append(
            {
                "stable_id": item.stable_id,
                "product_identity": product_identity(item),
                "rolex_reference": reference,
                "title": item.title,
                "comparison_key": {
                    "rolex_reference": reference,
                    "target_year": target_year,
                    "year_from": year_from,
                    "year_to": year_to,
                },
                "match_policy": "EXACT_REFERENCE_WITH_YEAR_WINDOW",
                "condition_policy": "PREFER_EXCELLENT_VERY_GOOD_PER_SOURCE",
                "aggregation_method": "SOURCE_YEAR_BALANCED_MEAN",
                "target_price_hkd": _money(item.price) if target_usable else None,
                "benchmark_status": benchmark_status,
                "confidence": confidence,
                "price_basis": price_basis,
                "primary_cohort_id": primary["cohort_id"] if primary else None,
                "trusted_source_count": trusted_source_count,
                "tier_a_source_count": tier_a_count,
                "local_source_count": local_count,
                "reference_price_hkd": _money(reference_price),
                "reference_low_hkd": (
                    _money(min(primary_source_means)) if primary_source_means else None
                ),
                "reference_high_hkd": (
                    _money(max(primary_source_means)) if primary_source_means else None
                ),
                "target_premium_percent": _percent(premium),
                "position": position,
                "reference_cohorts": cohorts,
                "source_summaries": summaries,
                "context_only_sources": _summarize_sources(contextual),
                "fixture_evidence_sources": _summarize_sources(fixture_evidence),
                "unverified_evidence_sources": _summarize_sources(unverified_evidence),
                "unworn_context_sources": _summarize_sources(unworn_context),
                "fair_context_sources": _summarize_sources(fair_context),
                "candidate_observation_count": len(candidate_observations),
                "year_eligible_observation_count": len(year_eligible),
                "matched_observation_count": len(trusted),
                "excluded_non_comparable_observation_count": len(non_comparable),
                "non_comparable_sources": _summarize_sources(non_comparable),
                "condition_deprioritized_observation_count": len(deprioritized),
                "condition_deprioritized_sources": _summarize_sources(deprioritized),
                "duplicate_observations_excluded": len(duplicates),
                "comparability_flags": flags,
                "not_investment_advice": True,
            }
        )

    if missing_reference:
        warnings.append(f"{missing_reference} 个库存商品没有 Rolex reference，未做行业对比")
    if unavailable:
        warnings.append(f"{unavailable} 个商品没有达到独立可信来源门槛")
    if target_year_unknown:
        warnings.append(f"{target_year_unknown} 个商品缺少年份，未形成年份窗口")
    stats = {
        "inventory_items": len(items),
        "compared_items": len(comparisons),
        "missing_reference_items": missing_reference,
        "verified_benchmarks": sum(
            item["benchmark_status"] == "VERIFIED" for item in comparisons
        ),
        "insufficient_benchmarks": unavailable,
        "demo_only_benchmarks": demo_only,
        "unverified_evidence_benchmarks": unverified_only,
        "target_year_unknown_items": target_year_unknown,
        "non_comparable_observations_excluded": non_comparable_excluded,
        "condition_deprioritized_observations": condition_deprioritized,
        "duplicate_observations_excluded": duplicate_excluded,
        "stale_observations_excluded": stale,
        "future_observations_excluded": future,
    }
    return comparisons, warnings, stats
