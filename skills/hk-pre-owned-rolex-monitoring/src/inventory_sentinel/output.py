from __future__ import annotations

from typing import Any

from .version import __version__


def result_envelope(
    *,
    operation: str,
    status: str,
    ok: bool,
    monitor_id: str | None = None,
    run_id: str | None = None,
    state_modified: bool = False,
    result: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "ok": ok,
        "operation": operation,
        "status": status,
        "skill_version": __version__,
        "monitor_id": monitor_id,
        "run_id": run_id,
        "state_modified": state_modified,
        "result": result or {},
        "warnings": warnings or [],
        "error": error,
    }
