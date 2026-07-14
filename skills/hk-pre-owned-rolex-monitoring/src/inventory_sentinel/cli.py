from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable

from .errors import ConfigError, InvalidSnapshot, InventorySentinelError
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
    skill_self_test = skill_sub.add_parser("self-test", help="运行不访问网络的完整 Fixture 自测")
    _json_flag(skill_self_test)
    skill_self_test.set_defaults(operation="skill.self-test")

    runtime = root.add_parser("runtime")
    runtime_sub = runtime.add_subparsers(dest="command", required=True)
    runtime_probe = runtime_sub.add_parser("probe")
    _json_flag(runtime_probe)
    runtime_probe.set_defaults(operation="runtime.probe")

    monitor = root.add_parser("monitor")
    monitor_sub = monitor.add_subparsers(dest="command", required=True)

    init = monitor_sub.add_parser("init", help="生成不会静默创建定时任务的 Manifest 草稿")
    init.add_argument("--output", required=True)
    init.add_argument("--id", default="orientalwatch-rolex-cpo")
    init.add_argument("--display-name", default="东方表行 Rolex CPO")
    init.add_argument("--timezone", default="Asia/Hong_Kong")
    init.add_argument("--recipient", default="current-user")
    init.add_argument("--job", action="append", default=[], metavar="ROLE=CRON")
    init.add_argument("--overwrite", action="store_true")
    _json_flag(init)
    init.set_defaults(operation="monitor.init")

    monitor_list = monitor_sub.add_parser("list")
    _json_flag(monitor_list)
    monitor_list.set_defaults(operation="monitor.list")

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

    history = monitor_sub.add_parser("history")
    history.add_argument("--id", required=True)
    history.add_argument("--date")
    history.add_argument("--limit", type=int, default=50)
    _json_flag(history)
    history.set_defaults(operation="monitor.history")

    show_run = monitor_sub.add_parser("show-run")
    show_run.add_argument("--run-id", required=True)
    _json_flag(show_run)
    show_run.set_defaults(operation="monitor.show-run")

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
    outbox_ack.add_argument("--provider")
    outbox_ack.add_argument("--external-message-id")
    outbox_ack.add_argument("--delivered-at")
    outbox_ack.add_argument("--verified", action="store_true")
    outbox_ack.add_argument("--delivery-error")
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
    market_packet_init = market_packet_sub.add_parser("init", help="创建空的 Market Packet 草稿")
    market_packet_init.add_argument("--output", required=True)
    market_packet_init.add_argument("--packet-id", required=True)
    market_packet_init.add_argument("--as-of", required=True)
    market_packet_init.add_argument("--overwrite", action="store_true")
    _json_flag(market_packet_init)
    market_packet_init.set_defaults(operation="market.packet.init")
    market_packet_add = market_packet_sub.add_parser("add", help="向草稿增加一条结构化行情")
    market_packet_add.add_argument("--file", required=True)
    market_packet_add.add_argument("--observation-id", required=True)
    market_packet_add.add_argument("--source", required=True)
    market_packet_add.add_argument("--source-listing-id")
    market_packet_add.add_argument("--independence-group")
    market_packet_add.add_argument("--underlying-listing-id")
    market_packet_add.add_argument("--dealer-name")
    market_packet_add.add_argument("--reference", required=True)
    market_packet_add.add_argument("--region", choices=("HK", "MAINLAND_CN", "APAC", "GLOBAL"), required=True)
    market_packet_add.add_argument(
        "--basis",
        choices=("market_estimate", "transaction_index", "asking_price", "auction_result", "dealer_quote"),
        required=True,
    )
    market_packet_add.add_argument("--price-hkd", required=True)
    market_packet_add.add_argument("--observed-at", required=True)
    market_packet_add.add_argument("--year", type=int)
    market_packet_add.add_argument(
        "--condition",
        choices=("unworn", "excellent", "very_good", "good", "fair", "unknown"),
        default="unknown",
    )
    market_packet_add.add_argument(
        "--completeness", choices=("full_set", "watch_only", "unknown"), default="unknown"
    )
    market_packet_add.add_argument(
        "--evidence-status", choices=("fixture", "unverified", "verified"), default="unverified"
    )
    market_packet_add.add_argument(
        "--acquisition-method",
        choices=("official_api", "authorized_export", "manual_url", "manual_snapshot", "fixture"),
        default="manual_snapshot",
    )
    market_packet_add.add_argument("--evidence-url")
    market_packet_add.add_argument("--evidence-note")
    market_packet_add.add_argument("--evidence-verified-at")
    market_packet_add.add_argument("--evidence-sha256")
    _json_flag(market_packet_add)
    market_packet_add.set_defaults(operation="market.packet.add")
    market_packet_import = market_packet_sub.add_parser("import-csv", help="导入标准列 CSV")
    market_packet_import.add_argument("--file", required=True)
    market_packet_import.add_argument("--csv", required=True)
    market_packet_import.add_argument("--source")
    _json_flag(market_packet_import)
    market_packet_import.set_defaults(operation="market.packet.import-csv")
    market_packet_attach = market_packet_sub.add_parser("attach-evidence")
    market_packet_attach.add_argument("--file", required=True)
    market_packet_attach.add_argument("--observation-id", required=True)
    market_packet_attach.add_argument("--evidence-file", required=True)
    market_packet_attach.add_argument("--verified-at", required=True)
    _json_flag(market_packet_attach)
    market_packet_attach.set_defaults(operation="market.packet.attach-evidence")
    market_packet_finalize = market_packet_sub.add_parser("finalize")
    market_packet_finalize.add_argument("--file", required=True)
    _json_flag(market_packet_finalize)
    market_packet_finalize.set_defaults(operation="market.packet.finalize")
    market_packet_validate = market_packet_sub.add_parser(
        "validate", help="校验 Market Packet 和证据状态"
    )
    market_packet_validate.add_argument("--file", required=True)
    _json_flag(market_packet_validate)
    market_packet_validate.set_defaults(operation="market.packet.validate")
    market_compare = market_sub.add_parser("compare", help="用有证据的 Market Packet 对比可信库存快照")
    selection = market_compare.add_mutually_exclusive_group(required=True)
    selection.add_argument("--id")
    selection.add_argument("--run-id")
    selection.add_argument("--event-id")
    market_compare.add_argument("--file", required=True)
    _json_flag(market_compare)
    market_compare.set_defaults(operation="market.compare")

    report = root.add_parser("report", help="生成可直接交付用户的中文组合报告")
    report_sub = report.add_subparsers(dest="command", required=True)
    report_build = report_sub.add_parser("build")
    report_build.add_argument("--run-id", required=True)
    report_build.add_argument("--market-packet")
    _json_flag(report_build)
    report_build.set_defaults(operation="report.build")
    return parser


def _dispatch(service: InventoryService, args: argparse.Namespace) -> ServiceResult:
    if args.operation == "runtime.probe":
        return service.runtime_probe()
    if args.operation == "monitor.create":
        return service.create_monitor(args.config)
    if args.operation == "monitor.list":
        return service.monitor_list()
    if args.operation == "monitor.baseline":
        return service.baseline(args.id)
    if args.operation == "monitor.run":
        return service.run_monitor(args.id, args.trigger)
    if args.operation == "monitor.status":
        return service.status(args.id)
    if args.operation == "monitor.history":
        return service.monitor_history(args.id, date=args.date, limit=args.limit)
    if args.operation == "monitor.show-run":
        return service.show_run(args.run_id)
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
        return service.outbox_ack(
            args.event_id,
            provider=args.provider,
            external_message_id=args.external_message_id,
            delivered_at=args.delivered_at,
            verified=args.verified,
            delivery_error={"message": args.delivery_error} if args.delivery_error else None,
        )
    if args.operation == "market.sources":
        return service.market_sources()
    if args.operation == "market.packet.validate":
        return service.market_packet_validate(args.file)
    if args.operation == "market.compare":
        return service.market_compare(
            args.id,
            args.file,
            run_id=args.run_id,
            event_id=args.event_id,
        )
    if args.operation == "report.build":
        return service.report_build(args.run_id, market_packet=args.market_packet)
    raise RuntimeError(f"未实现操作: {args.operation}")


def _jobs(values: list[str]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for value in values:
        if "=" not in value:
            raise ConfigError("--job 必须使用 ROLE=CRON，例如 daily=0 9 * * *")
        role, cron = value.split("=", 1)
        if not role.strip() or not cron.strip():
            raise ConfigError("--job 的 role 和 cron 均不能为空")
        result.append({"role": role.strip(), "cron": cron.strip()})
    return result


def _observation(args: argparse.Namespace) -> dict[str, object]:
    values = {
        "observation_id": args.observation_id,
        "source": args.source,
        "source_listing_id": args.source_listing_id,
        "independence_group": args.independence_group,
        "underlying_listing_id": args.underlying_listing_id,
        "dealer_name": args.dealer_name,
        "rolex_reference": args.reference,
        "region": args.region,
        "basis": args.basis,
        "price_hkd": args.price_hkd,
        "observed_at": args.observed_at,
        "year": args.year,
        "condition": args.condition,
        "completeness": args.completeness,
        "evidence_status": args.evidence_status,
        "acquisition_method": args.acquisition_method,
        "evidence_url": args.evidence_url,
        "evidence_note": args.evidence_note,
        "evidence_verified_at": args.evidence_verified_at,
        "evidence_sha256": args.evidence_sha256,
    }
    return {key: value for key, value in values.items() if value is not None}


def _static_dispatch(args: argparse.Namespace) -> ServiceResult:
    if args.operation == "skill.info":
        return InventoryService.skill_info()
    if args.operation == "skill.self-test":
        return InventoryService.self_test()
    if args.operation == "monitor.init":
        return InventoryService.monitor_init(
            output_path=args.output,
            monitor_id=args.id,
            display_name=args.display_name,
            timezone=args.timezone,
            recipient=args.recipient,
            jobs=_jobs(args.job),
            overwrite=args.overwrite,
        )
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
    if args.operation == "market.packet.init":
        return InventoryService.market_packet_init(
            output_path=args.output,
            packet_id=args.packet_id,
            as_of=args.as_of,
            overwrite=args.overwrite,
        )
    if args.operation == "market.packet.add":
        return InventoryService.market_packet_add(
            file_path=args.file,
            observation=_observation(args),
        )
    if args.operation == "market.packet.import-csv":
        return InventoryService.market_packet_import_csv(
            file_path=args.file,
            csv_path=args.csv,
            source=args.source,
        )
    if args.operation == "market.packet.attach-evidence":
        return InventoryService.market_packet_attach_evidence(
            file_path=args.file,
            observation_id=args.observation_id,
            evidence_file=args.evidence_file,
            verified_at=args.verified_at,
        )
    if args.operation == "market.packet.finalize":
        return InventoryService.market_packet_finalize(args.file)
    raise RuntimeError(f"未实现静态操作: {args.operation}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    static_operations = {
        "skill.info",
        "skill.self-test",
        "monitor.init",
        "market.sources",
        "market.source.doctor",
        "market.collect",
        "market.packet.validate",
        "market.packet.init",
        "market.packet.add",
        "market.packet.import-csv",
        "market.packet.attach-evidence",
        "market.packet.finalize",
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
