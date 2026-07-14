from __future__ import annotations

from typing import Any

from .version import __version__


def _next_actions(
    operation: str,
    status: str,
    monitor_id: str | None,
    run_id: str | None,
) -> list[dict[str, Any]]:
    monitor = monitor_id or "<monitor-id>"
    run = run_id or "<run-id>"
    actions: dict[tuple[str, str | None], list[dict[str, Any]]] = {
        ("skill.info", None): [
            {
                "action": "检查运行环境",
                "command": ["runtime", "probe", "--json"],
                "condition": "首次使用或运行环境发生变化",
            }
        ],
        ("runtime.probe", None): [
            {
                "action": "列出现有监控",
                "command": ["monitor", "list", "--json"],
                "condition": "继续使用已有状态",
            },
            {
                "action": "生成新监控配置草稿",
                "command": ["monitor", "init", "--output", "<manifest.yaml>", "--json"],
                "condition": "首次创建监控",
            },
        ],
        ("monitor.create", None): [
            {
                "action": "建立可信基线",
                "command": ["monitor", "baseline", "--id", monitor, "--json"],
                "condition": "配置已确认且当前允许访问目标站点",
            }
        ],
        ("monitor.baseline", "BASELINE_CREATED"): [
            {
                "action": "生成宿主运行计划",
                "command": ["monitor", "reconcile-plan", "--id", monitor, "--json"],
                "condition": "需要定时运行或通知",
            }
        ],
        ("monitor.run", "CHANGED"): [
            {
                "action": "生成可交付报告",
                "command": ["report", "build", "--run-id", run, "--json"],
                "condition": "向用户展示本次变化",
            },
            {
                "action": "读取待发送事件",
                "command": ["outbox", "list", "--id", monitor, "--json"],
                "condition": "宿主具备通知能力",
            },
        ],
        ("monitor.run", "NO_CHANGE"): [
            {
                "action": "生成本次运行报告",
                "command": ["report", "build", "--run-id", run, "--json"],
                "condition": "用户要求查看本次结果",
            }
        ],
        ("monitor.run", "INVALID"): [
            {
                "action": "诊断监控状态",
                "command": ["monitor", "doctor", "--id", monitor, "--json"],
                "condition": "确认失败原因且不覆盖成功基线",
            }
        ],
        ("market.packet.validate", None): [
            {
                "action": "对比库存或指定运行",
                "command": ["market", "compare", "--run-id", run, "--file", "<packet>", "--json"],
                "condition": "Packet 已完成且目标运行已确定",
            }
        ],
    }
    return actions.get((operation, status), actions.get((operation, None), []))


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
    next_actions: list[dict[str, Any]] | None = None,
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
        "next_actions": (
            _next_actions(operation, status, monitor_id, run_id)
            if next_actions is None
            else next_actions
        ),
    }
