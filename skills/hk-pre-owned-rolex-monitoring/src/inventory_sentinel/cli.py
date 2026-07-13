from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable

from .errors import InvalidSnapshot, InventorySentinelError
from .output import result_envelope
from .service import InventoryService, ServiceResult


def _json_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="输出结构化 JSON（默认行为）")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="inventoryctl", description="Portable inventory monitor control CLI")
    parser.add_argument("--state-dir", help="覆盖用户状态目录")
    root = parser.add_subparsers(dest="group", required=True)

    skill = root.add_parser("skill")
    skill_sub = skill.add_subparsers(dest="command", required=True)
    skill_info = skill_sub.add_parser("info")
    _json_flag(skill_info)
    skill_info.set_defaults(operation="skill.info")

    runtime = root.add_parser("runtime")
    runtime_sub = runtime.add_subparsers(dest="command", required=True)
    runtime_probe = runtime_sub.add_parser("probe")
    _json_flag(runtime_probe)
    runtime_probe.set_defaults(operation="runtime.probe")

    monitor = root.add_parser("monitor")
    monitor_sub = monitor.add_subparsers(dest="command", required=True)

    create = monitor_sub.add_parser("create")
    create.add_argument("--config", required=True)
    _json_flag(create)
    create.set_defaults(operation="monitor.create")

    baseline = monitor_sub.add_parser("baseline")
    baseline.add_argument("--id", required=True)
    _json_flag(baseline)
    baseline.set_defaults(operation="monitor.baseline")

    run = monitor_sub.add_parser("run")
    run.add_argument("--id", required=True)
    run.add_argument("--trigger", default="manual")
    _json_flag(run)
    run.set_defaults(operation="monitor.run")

    status = monitor_sub.add_parser("status")
    status.add_argument("--id", required=True)
    _json_flag(status)
    status.set_defaults(operation="monitor.status")

    doctor = monitor_sub.add_parser("doctor")
    doctor.add_argument("--id", required=True)
    _json_flag(doctor)
    doctor.set_defaults(operation="monitor.doctor")

    reconcile = monitor_sub.add_parser("reconcile-plan")
    reconcile.add_argument("--id", required=True)
    _json_flag(reconcile)
    reconcile.set_defaults(operation="monitor.reconcile-plan")

    apply_result = monitor_sub.add_parser("apply-runtime-result")
    apply_result.add_argument("--file", required=True)
    _json_flag(apply_result)
    apply_result.set_defaults(operation="monitor.apply-runtime-result")

    backup = monitor_sub.add_parser("backup")
    backup.add_argument("--id", required=True)
    _json_flag(backup)
    backup.set_defaults(operation="monitor.backup")

    restore = monitor_sub.add_parser("restore")
    restore.add_argument("--file", required=True)
    _json_flag(restore)
    restore.set_defaults(operation="monitor.restore")

    live_fetch = monitor_sub.add_parser("live-fetch", help="低频只读 Adapter smoke test")
    live_fetch.add_argument("--config", required=True)
    _json_flag(live_fetch)
    live_fetch.set_defaults(operation="adapter.live-fetch")

    outbox = root.add_parser("outbox")
    outbox_sub = outbox.add_subparsers(dest="command", required=True)
    outbox_list = outbox_sub.add_parser("list")
    outbox_list.add_argument("--id", required=True)
    _json_flag(outbox_list)
    outbox_list.set_defaults(operation="outbox.list")
    outbox_ack = outbox_sub.add_parser("ack")
    outbox_ack.add_argument("--event-id", required=True)
    _json_flag(outbox_ack)
    outbox_ack.set_defaults(operation="outbox.ack")

    market = root.add_parser("market", help="二手 Rolex 行业价格参考")
    market_sub = market.add_subparsers(dest="command", required=True)
    market_sources = market_sub.add_parser("sources", help="列出来源分级和允许的接入方式")
    _json_flag(market_sources)
    market_sources.set_defaults(operation="market.sources")
    market_source = market_sub.add_parser("source", help="检查单个行情来源的接入前提")
    market_source_sub = market_source.add_subparsers(dest="source_command", required=True)
    market_source_doctor = market_source_sub.add_parser("doctor")
    market_source_doctor.add_argument("--source", required=True)
    market_source_doctor.add_argument(
        "--mode", choices=("automatic", "manual"), default="automatic"
    )
    market_source_doctor.add_argument(
        "--usage", choices=("internal", "public_display", "resale"), default="internal"
    )
    _json_flag(market_source_doctor)
    market_source_doctor.set_defaults(operation="market.source.doctor")
    market_collect = market_sub.add_parser("collect", help="通过已实现的正式接口生成 Market Packet")
    market_collect.add_argument("--source", choices=("watchcharts",), required=True)
    market_collect.add_argument("--reference", required=True)
    market_collect.add_argument("--target-year", type=int, required=True)
    market_collect.add_argument("--region", choices=("APAC", "GLOBAL"), default="APAC")
    market_collect.add_argument(
        "--completeness", choices=("full_set", "watch_only"), required=True
    )
    market_collect.add_argument(
        "--usage", choices=("internal", "public_display", "resale"), default="internal"
    )
    market_collect.add_argument(
        "--license", choices=("internal", "distribution", "resale")
    )
    market_collect.add_argument("--output")
    market_collect.add_argument("--overwrite", action="store_true")
    _json_flag(market_collect)
    market_collect.set_defaults(operation="market.collect")
    market_packet = market_sub.add_parser("packet", help="校验行情证据 Packet")
    market_packet_sub = market_packet.add_subparsers(dest="packet_command", required=True)
    market_packet_validate = market_packet_sub.add_parser(
        "validate", help="校验 Market Packet 和证据状态"
    )
    market_packet_validate.add_argument("--file", required=True)
    _json_flag(market_packet_validate)
    market_packet_validate.set_defaults(operation="market.packet.validate")
    market_compare = market_sub.add_parser("compare", help="用有证据的 Market Packet 对比可信库存快照")
    market_compare.add_argument("--id", required=True)
    market_compare.add_argument("--file", required=True)
    _json_flag(market_compare)
    market_compare.set_defaults(operation="market.compare")
    return parser


def _dispatch(service: InventoryService, args: argparse.Namespace) -> ServiceResult:
    if args.operation == "runtime.probe":
        return service.runtime_probe()
    if args.operation == "monitor.create":
        return service.create_monitor(args.config)
    if args.operation == "monitor.baseline":
        return service.baseline(args.id)
    if args.operation == "monitor.run":
        return service.run_monitor(args.id, args.trigger)
    if args.operation == "monitor.status":
        return service.status(args.id)
    if args.operation == "monitor.doctor":
        return service.doctor(args.id)
    if args.operation == "monitor.reconcile-plan":
        return service.reconcile_plan(args.id)
    if args.operation == "monitor.apply-runtime-result":
        return service.apply_runtime_result(args.file)
    if args.operation == "monitor.backup":
        return service.backup(args.id)
    if args.operation == "monitor.restore":
        return service.restore(args.file)
    if args.operation == "adapter.live-fetch":
        return service.live_fetch(args.config)
    if args.operation == "outbox.list":
        return service.outbox_list(args.id)
    if args.operation == "outbox.ack":
        return service.outbox_ack(args.event_id)
    if args.operation == "market.sources":
        return service.market_sources()
    if args.operation == "market.packet.validate":
        return service.market_packet_validate(args.file)
    if args.operation == "market.compare":
        return service.market_compare(args.id, args.file)
    raise RuntimeError(f"未实现操作: {args.operation}")


def _static_dispatch(args: argparse.Namespace) -> ServiceResult:
    if args.operation == "skill.info":
        return InventoryService.skill_info()
    if args.operation == "market.sources":
        return InventoryService.market_sources()
    if args.operation == "market.source.doctor":
        return InventoryService.market_source_doctor(
            args.source,
            mode=args.mode,
            intended_use=args.usage,
        )
    if args.operation == "market.collect":
        return InventoryService.market_collect(
            source=args.source,
            reference=args.reference,
            target_year=args.target_year,
            region=args.region,
            completeness=args.completeness,
            intended_use=args.usage,
            license_type=args.license,
            output_path=args.output,
            overwrite=args.overwrite,
        )
    if args.operation == "market.packet.validate":
        return InventoryService.market_packet_validate(args.file)
    raise RuntimeError(f"未实现静态操作: {args.operation}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    static_operations = {
        "skill.info",
        "market.sources",
        "market.source.doctor",
        "market.collect",
        "market.packet.validate",
    }
    service: InventoryService | None = None
    try:
        if args.operation in static_operations:
            payload, exit_code = _static_dispatch(args)
        else:
            service = InventoryService(args.state_dir)
            payload, exit_code = _dispatch(service, args)
    except InventorySentinelError as exc:
        invalid = isinstance(exc, InvalidSnapshot)
        payload = result_envelope(
            operation=getattr(args, "operation", "unknown"),
            status="INVALID" if invalid else "ERROR",
            ok=False,
            monitor_id=getattr(args, "id", None),
            result={"last_verified_snapshot_preserved": True} if invalid else {},
            error={"code": exc.code, "message": exc.message, "details": exc.details},
        )
        exit_code = exc.exit_code
    except Exception as exc:
        payload = result_envelope(
            operation=getattr(args, "operation", "unknown"),
            status="ERROR",
            ok=False,
            monitor_id=getattr(args, "id", None),
            error={"code": "UNEXPECTED_ERROR", "message": str(exc)},
        )
        exit_code = 4
    finally:
        if service is not None:
            try:
                service.close()
            except Exception:
                pass
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
