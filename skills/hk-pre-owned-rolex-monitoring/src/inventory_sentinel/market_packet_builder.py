from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from .errors import ConfigError
from .models import MarketObservation, MarketPacket


def _path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def _read(path: str | Path) -> tuple[Path, dict[str, Any]]:
    source = _path(path)
    if not source.is_file():
        raise ConfigError(f"Market Packet 不存在: {source}")
    try:
        text = source.read_text(encoding="utf-8")
        data = json.loads(text) if source.suffix.lower() == ".json" else yaml.safe_load(text)
    except Exception as exc:
        raise ConfigError(f"Market Packet 草稿读取失败: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError("Market Packet 顶层必须是对象")
    return source, data


def _write(path: Path, payload: dict[str, Any]) -> None:
    if path.suffix.lower() == ".json":
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    else:
        text = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def init_packet(
    output_path: str | Path,
    *,
    packet_id: str,
    as_of: str,
    overwrite: bool,
) -> tuple[Path, dict[str, Any]]:
    destination = _path(output_path)
    if destination.exists() and not overwrite:
        raise ConfigError(f"输出文件已存在，未覆盖: {destination}")
    if not destination.parent.is_dir():
        raise ConfigError(f"输出目录不存在: {destination.parent}")
    payload = {
        "schema_version": 1,
        "packet_id": packet_id,
        "as_of": as_of,
        "comparison": {
            "max_age_days": 90,
            "minimum_independent_sources": 2,
            "reference_band_percent": 5,
            "year_window": 2,
            "outlier_warning_percent": 30,
        },
        "collection_context": {
            "builder": "inventoryctl market packet",
            "status": "draft",
        },
        "observations": [],
    }
    # 用空列表之外的同构数据验证顶层时间和比较参数。
    try:
        MarketPacket.model_validate({**payload, "observations": [_placeholder_observation(as_of)]})
    except Exception as exc:
        raise ConfigError(f"Market Packet 草稿参数无效: {exc}") from exc
    _write(destination, payload)
    return destination, payload


def _placeholder_observation(as_of: str) -> dict[str, Any]:
    return {
        "observation_id": "draft-placeholder",
        "source": "other",
        "rolex_reference": "DRAFT",
        "region": "GLOBAL",
        "basis": "asking_price",
        "price_hkd": 1,
        "observed_at": as_of,
        "year": None,
        "condition": "unknown",
        "evidence_status": "unverified",
        "acquisition_method": "manual_snapshot",
        "evidence_note": "draft validation",
    }


def add_observation(
    file_path: str | Path,
    observation: dict[str, Any],
) -> tuple[Path, dict[str, Any], MarketObservation]:
    destination, payload = _read(file_path)
    try:
        validated = MarketObservation.model_validate(observation)
    except Exception as exc:
        raise ConfigError(f"行情 observation 校验失败: {exc}") from exc
    rows = list(payload.get("observations") or [])
    if any(row.get("observation_id") == validated.observation_id for row in rows):
        raise ConfigError(f"observation_id 已存在: {validated.observation_id}")
    rows.append(validated.model_dump(mode="json"))
    payload["observations"] = rows
    _write(destination, payload)
    return destination, payload, validated


def import_csv_observations(
    file_path: str | Path,
    csv_path: str | Path,
    *,
    source_override: str | None = None,
) -> tuple[Path, dict[str, Any], int]:
    destination, payload = _read(file_path)
    source = _path(csv_path)
    if not source.is_file():
        raise ConfigError(f"CSV 不存在: {source}")
    rows = list(payload.get("observations") or [])
    existing = {row.get("observation_id") for row in rows}
    imported = 0
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        for line_number, row in enumerate(csv.DictReader(handle), start=2):
            data: dict[str, Any] = {key: value for key, value in row.items() if value not in (None, "")}
            if source_override:
                data["source"] = source_override
            for key in ("price_hkd", "year"):
                if key in data:
                    data[key] = int(data[key]) if key == "year" else data[key]
            if data.get("year") in ("", "null", "None"):
                data["year"] = None
            try:
                validated = MarketObservation.model_validate(data)
            except Exception as exc:
                raise ConfigError(f"CSV 第 {line_number} 行校验失败: {exc}") from exc
            if validated.observation_id in existing:
                raise ConfigError(f"CSV observation_id 重复: {validated.observation_id}")
            existing.add(validated.observation_id)
            rows.append(validated.model_dump(mode="json"))
            imported += 1
    payload["observations"] = rows
    _write(destination, payload)
    return destination, payload, imported


def attach_evidence(
    file_path: str | Path,
    *,
    observation_id: str,
    evidence_file: str | Path,
    verified_at: str,
) -> tuple[Path, dict[str, Any], MarketObservation]:
    destination, payload = _read(file_path)
    evidence = _path(evidence_file)
    if not evidence.is_file():
        raise ConfigError(f"证据文件不存在: {evidence}")
    digest = "sha256:" + hashlib.sha256(evidence.read_bytes()).hexdigest()
    rows = list(payload.get("observations") or [])
    found = False
    validated: MarketObservation | None = None
    for index, row in enumerate(rows):
        if row.get("observation_id") != observation_id:
            continue
        found = True
        candidate = {
            **row,
            "evidence_status": "verified",
            "acquisition_method": (
                "authorized_export"
                if evidence.suffix.lower() in {".csv", ".json", ".xlsx"}
                else "manual_snapshot"
            ),
            "evidence_verified_at": verified_at,
            "evidence_sha256": digest,
            "evidence_note": row.get("evidence_note") or f"本地证据文件 {evidence.name}",
        }
        try:
            validated = MarketObservation.model_validate(candidate)
        except Exception as exc:
            raise ConfigError(f"附加证据后 observation 无效: {exc}") from exc
        rows[index] = validated.model_dump(mode="json")
        break
    if not found or validated is None:
        raise ConfigError(f"observation_id 不存在: {observation_id}")
    payload["observations"] = rows
    _write(destination, payload)
    return destination, payload, validated


def finalize_packet(file_path: str | Path) -> tuple[Path, MarketPacket]:
    destination, payload = _read(file_path)
    try:
        packet = MarketPacket.model_validate(payload)
    except Exception as exc:
        raise ConfigError(f"Market Packet 尚不能 finalize: {exc}") from exc
    finalized = packet.model_dump(mode="json")
    finalized["collection_context"] = {
        **finalized.get("collection_context", {}),
        "status": "finalized",
    }
    packet = MarketPacket.model_validate(finalized)
    _write(destination, packet.model_dump(mode="json"))
    return destination, packet
