from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_ROOT / "scripts/inventoryctl.py"


def invoke(
    *args: str, env: dict[str, str] | None = None
) -> tuple[subprocess.CompletedProcess[str], dict]:
    environment = os.environ.copy()
    if env:
        environment.update(env)
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        check=False,
        text=True,
        capture_output=True,
        env=environment,
    )
    return completed, json.loads(completed.stdout)


def make_fixture_manifest(tmp_path: Path, fixture: Path) -> Path:
    path = tmp_path / "fixture-monitor.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "monitor_id": "cli-monitor",
                "display_name": "CLI 测试",
                "target": {"adapter": "fixture", "url": str(fixture), "fixture_path": str(fixture)},
                "schedule": {"timezone": "Asia/Shanghai", "jobs": []},
                "notification": {"include_images": False},
                "validation": {"sample_interval_seconds": 0},
                "state": {"image_cache": False},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def test_stable_cli_lifecycle_and_json_envelope(tmp_path: Path) -> None:
    fixture = SKILL_ROOT / "tests/fixtures/catalog-baseline.json"
    manifest = make_fixture_manifest(tmp_path, fixture)
    state = tmp_path / "state"

    info_process, info = invoke("skill", "info", "--json")
    assert info_process.returncode == 0
    assert info["result"]["platform_neutral"] is True

    process, created = invoke("--state-dir", str(state), "monitor", "create", "--config", str(manifest), "--json")
    assert process.returncode == 0 and created["state_modified"]
    process, baseline = invoke("--state-dir", str(state), "monitor", "baseline", "--id", "cli-monitor", "--json")
    assert process.returncode == 0 and baseline["status"] == "BASELINE_CREATED"
    process, run = invoke(
        "--state-dir", str(state), "monitor", "run", "--id", "cli-monitor", "--trigger", "manual", "--json"
    )
    assert process.returncode == 0 and run["status"] == "NO_CHANGE"
    process, duplicate = invoke(
        "--state-dir", str(state), "monitor", "run", "--id", "cli-monitor", "--trigger", "manual", "--json"
    )
    assert process.returncode == 0 and duplicate["status"] == "SKIPPED_DUPLICATE"
    assert set(duplicate) == {
        "schema_version",
        "ok",
        "operation",
        "status",
        "skill_version",
        "monitor_id",
        "run_id",
        "state_modified",
        "result",
        "warnings",
        "error",
    }

    process, sources = invoke("--state-dir", str(state), "market", "sources", "--json")
    assert process.returncode == 0
    assert sources["result"]["automatic_scraping_enabled"] is False
    market_packet = SKILL_ROOT / "assets/templates/market-packet.example.json"
    process, validation = invoke(
        "market", "packet", "validate", "--file", str(market_packet), "--json"
    )
    assert process.returncode == 0
    assert validation["result"]["evidence_status_counts"] == {
        "fixture": 2,
        "unverified": 0,
        "verified": 0,
    }
    assert validation["result"]["verification_ready"] is False
    process, comparison = invoke(
        "--state-dir",
        str(state),
        "market",
        "compare",
        "--id",
        "cli-monitor",
        "--file",
        str(market_packet),
        "--json",
    )
    assert process.returncode == 0
    assert comparison["result"]["inventory_baseline_modified"] is False
    assert comparison["result"]["stats"]["verified_benchmarks"] == 0
    assert comparison["result"]["analysis_status"] == "DEMO_ONLY"
    assert comparison["result"]["human_summary_zh"]["headline"].startswith("行情对比未形成已验证参考")
    compared = next(item for item in comparison["result"]["comparisons"] if item["rolex_reference"] == "126334")
    assert compared["benchmark_status"] == "DEMO_ONLY"


def test_cli_invalid_exit_code_and_preservation_flag(tmp_path: Path) -> None:
    fixture = tmp_path / "empty.json"
    fixture.write_text('{"items": []}', encoding="utf-8")
    manifest = make_fixture_manifest(tmp_path, fixture)
    state = tmp_path / "state"
    invoke("--state-dir", str(state), "monitor", "create", "--config", str(manifest), "--json")
    process, payload = invoke("--state-dir", str(state), "monitor", "baseline", "--id", "cli-monitor", "--json")
    assert process.returncode == 2
    assert payload["status"] == "INVALID"
    assert payload["result"]["last_verified_snapshot_preserved"] is True


def test_market_source_doctor_is_state_free_and_structured() -> None:
    process, payload = invoke(
        "market",
        "source",
        "doctor",
        "--source",
        "watchcharts",
        "--mode",
        "automatic",
        "--usage",
        "internal",
        "--json",
        env={"WATCHCHARTS_API_KEY": "", "WATCHCHARTS_LICENSE": ""},
    )

    assert process.returncode == 0
    assert payload["operation"] == "market.source.doctor"
    assert payload["state_modified"] is False
    assert payload["result"]["ready"] is False
    assert payload["result"]["source_status"] == "SOURCE_AUTH_REQUIRED"


def test_market_collect_missing_credentials_returns_json_error() -> None:
    process, payload = invoke(
        "market",
        "collect",
        "--source",
        "watchcharts",
        "--reference",
        "126334",
        "--target-year",
        "2021",
        "--region",
        "APAC",
        "--completeness",
        "full_set",
        "--license",
        "internal",
        "--json",
        env={"WATCHCHARTS_API_KEY": "", "WATCHCHARTS_LICENSE": ""},
    )

    assert process.returncode == 3
    assert payload["operation"] == "market.collect"
    assert payload["status"] == "ERROR"
    assert payload["error"]["code"] == "SOURCE_AUTH_REQUIRED"
    assert "secret" not in json.dumps(payload).lower()
