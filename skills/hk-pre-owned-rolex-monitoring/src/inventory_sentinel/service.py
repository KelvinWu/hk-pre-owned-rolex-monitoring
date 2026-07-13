from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from .adapters import AdapterRegistry
from .backup import BackupManager
from .diffing import calculate_diff, diff_count
from .errors import ConfigError, InvalidSnapshot, InventorySentinelError
from .image_cache import ImageCache
from .locking import RunLock
from .market_intelligence import (
    compare_snapshot,
    market_analysis_status,
    market_human_summary,
)
from .market_sources import (
    SOURCE_REGISTRY_VERSION,
    WatchChartsCollector,
    diagnose_source,
    market_sources as source_catalog,
)
from .models import FetchResult, MonitorManifest, RuntimeResult, load_manifest, load_market_packet
from .output import result_envelope
from .presentation import build_human_summary_zh, change_summary_zh
from .runtime_plan import build_runtime_plan
from .storage import SCHEMA_VERSION, Storage
from .util import items_hash, state_directory
from .validation import is_suspicious, same_id_set, same_snapshot, validate_fetch
from .version import __version__


ServiceResult = tuple[dict[str, Any], int]


class InventoryService:
    def __init__(
        self,
        state_dir: str | Path | None = None,
        *,
        adapters: AdapterRegistry | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        image_cache_factory: Callable[[Path], ImageCache] = ImageCache,
    ) -> None:
        self.state_dir = state_directory(state_dir)
        self.storage = Storage(self.state_dir)
        self.adapters = adapters or AdapterRegistry()
        self.sleeper = sleeper
        self.image_cache_factory = image_cache_factory

    @staticmethod
    def skill_info() -> ServiceResult:
        return (
            result_envelope(
                operation="skill.info",
                status="NO_CHANGE",
                ok=True,
                result={
                    "name": "hk-pre-owned-rolex-monitoring",
                    "version": __version__,
                    "manifest_schema_version": 1,
                    "market_packet_schema_version": 1,
                    "market_source_registry_version": SOURCE_REGISTRY_VERSION,
                    "state_schema_version": SCHEMA_VERSION,
                    "platform_neutral": True,
                    "host_actions_executed": False,
                },
            ),
            0,
        )

    def runtime_probe(self) -> ServiceResult:
        probe_path = self.state_dir / ".probe"
        storage_ok = False
        warning: list[str] = []
        try:
            probe_path.write_text("hk-pre-owned-rolex-monitoring", encoding="utf-8")
            storage_ok = probe_path.read_text(encoding="utf-8") == "hk-pre-owned-rolex-monitoring"
        finally:
            probe_path.unlink(missing_ok=True)
        if not storage_ok:
            warning.append("持久目录写入探测失败")
        return (
            result_envelope(
                operation="runtime.probe",
                status="NO_CHANGE" if storage_ok else "ERROR",
                ok=storage_ok,
                result={
                    "state_dir": str(self.state_dir),
                    "capabilities": {
                        "command_execution": "supported",
                        "state_directory_writable": "supported" if storage_ok else "unsupported",
                        "persistent_storage": "host_verification_required" if storage_ok else "unsupported",
                        "network": "not_probed",
                        "scheduler": "host_required",
                        "notification": "host_required",
                        "browser": "optional_host_capability",
                        "market_data": "authorized_packet_or_host_provider",
                    },
                },
                warnings=warning,
            ),
            0 if storage_ok else 4,
        )

    def create_monitor(self, config_path: str | Path) -> ServiceResult:
        manifest = load_manifest(config_path)
        self.adapters.get(manifest.target.adapter)
        modified = self.storage.register_monitor(manifest)
        return (
            result_envelope(
                operation="monitor.create",
                status="NO_CHANGE",
                ok=True,
                monitor_id=manifest.monitor_id,
                state_modified=modified,
                result={"manifest": manifest.model_dump(mode="json"), "adapter_available": True},
            ),
            0,
        )

    def baseline(self, monitor_id: str) -> ServiceResult:
        operation = "monitor.baseline"
        manifest = self.storage.get_manifest(monitor_id)
        run_id = str(uuid.uuid4())
        invalid_key = f"baseline:{run_id}"
        with RunLock(self.state_dir / "locks", monitor_id):
            try:
                samples, warnings = self._collect_consecutive_samples(
                    manifest,
                    required=manifest.validation.baseline_samples,
                    max_attempts=manifest.validation.baseline_samples + 1,
                    compare="ids",
                )
                trusted = samples[-1]
                cache_warnings, image_cache, _ = self._cache_images(manifest, trusted.items)
                warnings.extend(cache_warnings)
                snapshot_hash = items_hash(trusted.items)
                diagnostics = {
                    **trusted.diagnostics,
                    "samples": len(samples),
                    "confirmation": "consecutive_stable_id_sets",
                }
                snapshot_id = self.storage.save_baseline(
                    monitor_id=monitor_id,
                    run_id=run_id,
                    items=trusted.items,
                    snapshot_hash=snapshot_hash,
                    diagnostics=diagnostics,
                )
                return (
                    result_envelope(
                        operation=operation,
                        status="BASELINE_CREATED",
                        ok=True,
                        monitor_id=monitor_id,
                        run_id=run_id,
                        state_modified=True,
                        result={
                            "baseline": {
                                "verified": True,
                                "snapshot_id": snapshot_id,
                                "item_count": len(trusted.items),
                                "snapshot_hash": snapshot_hash,
                                "samples": len(samples),
                            },
                            "image_cache": image_cache,
                        },
                        warnings=warnings,
                    ),
                    0,
                )
            except InvalidSnapshot as exc:
                return self._record_invalid(operation, manifest, run_id, "baseline", invalid_key, exc)

    def run_monitor(self, monitor_id: str, trigger: str) -> ServiceResult:
        operation = "monitor.run"
        manifest = self.storage.get_manifest(monitor_id)
        if not manifest.enabled:
            raise ConfigError(f"Monitor 已停用: {monitor_id}")
        local_date = datetime.now(ZoneInfo(manifest.schedule.timezone)).date().isoformat()
        idempotency_key = f"{monitor_id}:{local_date}:{trigger}"
        existing = self.storage.existing_run(idempotency_key)
        if existing:
            return (
                result_envelope(
                    operation=operation,
                    status="SKIPPED_DUPLICATE",
                    ok=True,
                    monitor_id=monitor_id,
                    run_id=existing["run_id"],
                    result={"idempotency_key": idempotency_key, "previous_status": existing["status"]},
                ),
                0,
            )

        run_id = str(uuid.uuid4())
        with RunLock(self.state_dir / "locks", monitor_id):
            existing = self.storage.existing_run(idempotency_key)
            if existing:
                return (
                    result_envelope(
                        operation=operation,
                        status="SKIPPED_DUPLICATE",
                        ok=True,
                        monitor_id=monitor_id,
                        run_id=existing["run_id"],
                        result={"idempotency_key": idempotency_key, "previous_status": existing["status"]},
                    ),
                    0,
                )
            previous = self.storage.latest_snapshot(monitor_id)
            if previous is None:
                raise ConfigError("尚未建立可信基线，请先运行 monitor baseline")
            try:
                first = self._fetch(manifest)
                diff = calculate_diff(previous["items"], first.items)
                count = diff_count(diff)
                warnings = list(first.warnings)
                samples = [first]
                if count:
                    required = (
                        manifest.validation.suspicious_confirmation_samples
                        if is_suspicious(count, previous["item_count"], manifest.validation)
                        else manifest.validation.change_confirmation_samples
                    )
                    samples, confirmation_warnings = self._collect_consecutive_samples(
                        manifest,
                        required=required,
                        max_attempts=required,
                        compare="full",
                        initial=first,
                    )
                    warnings.extend(confirmation_warnings)
                    first = samples[-1]
                    diff = calculate_diff(previous["items"], first.items)
                    count = diff_count(diff)
                cache_warnings, image_cache, image_entries = self._cache_images(manifest, first.items)
                warnings.extend(cache_warnings)
                self._attach_image_cache_to_diff(manifest, diff, image_entries)
                status = "CHANGED" if count else "NO_CHANGE"
                snapshot_hash = items_hash(first.items)
                human_summary = build_human_summary_zh(status, diff, len(first.items))
                events = self._events_for_run(
                    manifest,
                    run_id,
                    idempotency_key,
                    status,
                    diff,
                    human_summary,
                )
                snapshot_id = self.storage.commit_success(
                    monitor_id=monitor_id,
                    run_id=run_id,
                    trigger=trigger,
                    idempotency_key=idempotency_key,
                    status=status,
                    items=first.items,
                    snapshot_hash=snapshot_hash,
                    diagnostics={**first.diagnostics, "samples": len(samples)},
                    diff=diff,
                    events=events,
                )
                return (
                    result_envelope(
                        operation=operation,
                        status=status,
                        ok=True,
                        monitor_id=monitor_id,
                        run_id=run_id,
                        state_modified=True,
                        result={
                            "snapshot_id": snapshot_id,
                            "snapshot_hash": snapshot_hash,
                            "item_count": len(first.items),
                            "diff": diff,
                            "change_count": count,
                            "confirmation_samples": len(samples),
                            "outbox_events": len(events),
                            "human_summary_zh": human_summary,
                            "image_cache": image_cache,
                        },
                        warnings=warnings,
                    ),
                    0,
                )
            except InvalidSnapshot as exc:
                return self._record_invalid(operation, manifest, run_id, trigger, idempotency_key, exc)

    def status(self, monitor_id: str) -> ServiceResult:
        data = self.storage.monitor_status(monitor_id)
        return (
            result_envelope(
                operation="monitor.status",
                status="NO_CHANGE",
                ok=True,
                monitor_id=monitor_id,
                result=data,
            ),
            0,
        )

    def doctor(self, monitor_id: str) -> ServiceResult:
        manifest = self.storage.get_manifest(monitor_id)
        integrity = self.storage.integrity()
        snapshot = self.storage.latest_snapshot(monitor_id)
        plan = build_runtime_plan(manifest)
        bindings = self.storage.runtime_bindings(monitor_id)
        verified = {row["logical_id"] for row in bindings if row["verified"]}
        missing = [operation.logical_id for operation in plan.operations if operation.logical_id not in verified]
        warnings: list[str] = []
        if snapshot is None:
            warnings.append("尚未建立可信基线")
        if missing:
            warnings.append("存在未验证的宿主任务；这不影响手动 CLI 运行")
        ok = integrity["ok"] and manifest.target.adapter in self.adapters.names()
        return (
            result_envelope(
                operation="monitor.doctor",
                status="NO_CHANGE" if ok else "ERROR",
                ok=ok,
                monitor_id=monitor_id,
                result={
                    "database": integrity,
                    "adapter": {"name": manifest.target.adapter, "available": True},
                    "baseline_present": snapshot is not None,
                    "runtime_bindings": bindings,
                    "missing_verified_logical_ids": missing,
                },
                warnings=warnings,
            ),
            0 if ok else 4,
        )

    def reconcile_plan(self, monitor_id: str) -> ServiceResult:
        manifest = self.storage.get_manifest(monitor_id)
        plan = build_runtime_plan(manifest)
        return (
            result_envelope(
                operation="monitor.reconcile-plan",
                status="NO_CHANGE",
                ok=True,
                monitor_id=monitor_id,
                result={"runtime_plan": plan.model_dump(mode="json")},
            ),
            0,
        )

    def apply_runtime_result(self, file_path: str | Path) -> ServiceResult:
        try:
            payload = json.loads(Path(file_path).read_text(encoding="utf-8"))
            runtime_result = RuntimeResult.model_validate(payload)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise ConfigError(f"Runtime Result 校验失败: {exc}") from exc
        self.storage.get_manifest(runtime_result.monitor_id)
        self.storage.apply_runtime_results(runtime_result.monitor_id, runtime_result.results)
        invalid = [
            item.logical_id
            for item in runtime_result.results
            if not (item.ok and item.verified and bool(item.external_id))
        ]
        ok = not invalid
        return (
            result_envelope(
                operation="monitor.apply-runtime-result",
                status="NO_CHANGE" if ok else "INVALID",
                ok=ok,
                monitor_id=runtime_result.monitor_id,
                state_modified=True,
                result={
                    "applied": len(runtime_result.results),
                    "verified": len(runtime_result.results) - len(invalid),
                    "unverified_logical_ids": invalid,
                    "last_verified_snapshot_preserved": True,
                },
                error=None
                if ok
                else {"code": "RUNTIME_RESULT_UNVERIFIED", "message": "部分宿主操作未经验证"},
            ),
            0 if ok else 2,
        )

    def backup(self, monitor_id: str) -> ServiceResult:
        manifest = self.storage.get_manifest(monitor_id)
        if not manifest.state.backup_enabled:
            raise ConfigError("此 Monitor 已禁用备份")
        path = BackupManager(self.state_dir).create(monitor_id)
        return (
            result_envelope(
                operation="monitor.backup",
                status="NO_CHANGE",
                ok=True,
                monitor_id=monitor_id,
                result={"backup_path": str(path), "verified": True},
            ),
            0,
        )

    def restore(self, file_path: str | Path) -> ServiceResult:
        manager = BackupManager(self.state_dir)
        archive = Path(file_path).expanduser().resolve()
        manifest = manager.verify(archive)
        safety = manager.create("pre-restore-safety")
        self.storage.close()
        try:
            restored = manager.restore(archive)
        except Exception:
            manager.restore(safety)
            self.storage = Storage(self.state_dir)
            raise
        self.storage = Storage(self.state_dir)
        return (
            result_envelope(
                operation="monitor.restore",
                status="NO_CHANGE",
                ok=True,
                monitor_id=restored.get("monitor_id"),
                state_modified=True,
                result={"restored_from": str(archive), "safety_backup": str(safety), "verified": True},
            ),
            0,
        )

    def outbox_list(self, monitor_id: str) -> ServiceResult:
        events = self.storage.list_outbox(monitor_id)
        return (
            result_envelope(
                operation="outbox.list",
                status="NO_CHANGE",
                ok=True,
                monitor_id=monitor_id,
                result={"events": events, "pending": sum(event["status"] == "pending" for event in events)},
            ),
            0,
        )

    def outbox_ack(self, event_id: str) -> ServiceResult:
        modified = self.storage.ack_outbox(event_id)
        return (
            result_envelope(
                operation="outbox.ack",
                status="NO_CHANGE",
                ok=True,
                state_modified=modified,
                result={"event_id": event_id, "acknowledged": modified},
            ),
            0,
        )

    @staticmethod
    def market_sources() -> ServiceResult:
        return (
            result_envelope(
                operation="market.sources",
                status="NO_CHANGE",
                ok=True,
                result={
                    "registry_version": SOURCE_REGISTRY_VERSION,
                    "sources": source_catalog(),
                    "automatic_scraping_enabled": False,
                    "official_api_collection_enabled": True,
                    "implemented_automatic_sources": ["watchcharts"],
                    "rule": "只有来源政策和凭证检查通过后才能自动采集；禁止或未审查来源保持人工证据模式",
                },
            ),
            0,
        )

    @staticmethod
    def market_source_doctor(
        source: str,
        *,
        mode: str,
        intended_use: str,
    ) -> ServiceResult:
        diagnosis = diagnose_source(
            source,
            mode=mode,
            intended_use=intended_use,
        )
        return (
            result_envelope(
                operation="market.source.doctor",
                status="NO_CHANGE",
                ok=True,
                state_modified=False,
                result=diagnosis,
                warnings=diagnosis["warnings"],
            ),
            0,
        )

    @staticmethod
    def market_collect(
        *,
        source: str,
        reference: str,
        target_year: int,
        region: str,
        completeness: str,
        intended_use: str,
        license_type: str | None,
        output_path: str | Path | None,
        overwrite: bool,
    ) -> ServiceResult:
        if source != "watchcharts":
            diagnosis = diagnose_source(
                source,
                mode="automatic",
                intended_use=intended_use,
            )
            raise ConfigError(
                f"来源尚无可用自动采集器: {source}",
                details={
                    "source": source,
                    "source_status": diagnosis["source_status"],
                    "manual_evidence_supported": diagnosis["manual_evidence_supported"],
                },
            )
        api_key = os.environ.get("WATCHCHARTS_API_KEY", "").strip()
        effective_license = (
            license_type or os.environ.get("WATCHCHARTS_LICENSE", "")
        ).strip().lower()
        collector = WatchChartsCollector()
        try:
            packet, warnings = collector.collect(
                reference=reference,
                target_year=target_year,
                region=region,
                completeness=completeness,
                api_key=api_key,
                license_type=effective_license,
                intended_use=intended_use,
            )
        finally:
            collector.close()

        output_written = False
        resolved_output: str | None = None
        if output_path is not None:
            destination = Path(output_path).expanduser().resolve()
            if destination.exists() and not overwrite:
                raise ConfigError(
                    f"输出文件已存在，未覆盖: {destination}",
                    details={"use_overwrite": True},
                )
            if not destination.parent.is_dir():
                raise ConfigError(f"输出目录不存在: {destination.parent}")
            destination.write_text(packet.model_dump_json(indent=2), encoding="utf-8")
            output_written = True
            resolved_output = str(destination)

        return (
            result_envelope(
                operation="market.collect",
                status="NO_CHANGE",
                ok=True,
                state_modified=False,
                result={
                    "source": source,
                    "packet": packet.model_dump(mode="json"),
                    "output_written": output_written,
                    "output_path": resolved_output,
                    "inventory_baseline_modified": False,
                    "note": "WatchCharts appraisal 是型号级行情；生产年份为空，只作型号背景，不冒充目标年份样本。",
                },
                warnings=warnings,
            ),
            0,
        )

    @staticmethod
    def market_packet_validate(file_path: str | Path) -> ServiceResult:
        packet = load_market_packet(file_path)
        counts = {status: 0 for status in ("fixture", "unverified", "verified")}
        for observation in packet.observations:
            counts[observation.evidence_status] += 1
        verified_groups = {
            observation.independence_group or observation.source
            for observation in packet.observations
            if observation.evidence_status == "verified"
        }
        return (
            result_envelope(
                operation="market.packet.validate",
                status="NO_CHANGE",
                ok=True,
                result={
                    "packet_id": packet.packet_id,
                    "as_of": packet.as_of.isoformat(),
                    "observation_count": len(packet.observations),
                    "evidence_status_counts": counts,
                    "verified_independence_group_count": len(verified_groups),
                    "verification_ready": (
                        counts["fixture"] == 0
                        and counts["unverified"] == 0
                        and len(verified_groups)
                        >= packet.comparison.minimum_independent_sources
                    ),
                    "note": "此命令只验证 Packet 契约和证据声明；是否能形成参考价仍由型号、年份、地区和价格口径决定。",
                },
            ),
            0,
        )

    def market_compare(self, monitor_id: str, file_path: str | Path) -> ServiceResult:
        self.storage.get_manifest(monitor_id)
        snapshot = self.storage.latest_snapshot(monitor_id)
        if snapshot is None:
            raise ConfigError("尚未建立可信库存基线，不能执行行业对比")
        packet = load_market_packet(file_path)
        comparisons, warnings, stats = compare_snapshot(snapshot["items"], packet)
        analysis_status = market_analysis_status(comparisons)
        return (
            result_envelope(
                operation="market.compare",
                status="NO_CHANGE",
                ok=True,
                monitor_id=monitor_id,
                state_modified=False,
                result={
                    "packet_id": packet.packet_id,
                    "as_of": packet.as_of.isoformat(),
                    "inventory_snapshot_id": snapshot["snapshot_id"],
                    "inventory_snapshot_hash": snapshot["snapshot_hash"],
                    "comparison_config": packet.comparison.model_dump(mode="json"),
                    "analysis_status": analysis_status,
                    "stats": stats,
                    "comparisons": comparisons,
                    "human_summary_zh": market_human_summary(comparisons),
                    "inventory_baseline_modified": False,
                    "not_investment_advice": True,
                },
                warnings=warnings,
            ),
            0,
        )

    def live_fetch(self, config_path: str | Path) -> ServiceResult:
        manifest = load_manifest(config_path)
        samples, warnings = self._collect_consecutive_samples(
            manifest,
            required=2,
            max_attempts=2,
            compare="ids",
        )
        fetch = samples[-1]
        return (
            result_envelope(
                operation="adapter.live-fetch",
                status="NO_CHANGE",
                ok=True,
                monitor_id=manifest.monitor_id,
                result={
                    "item_count": len(fetch.items),
                    "unique_stable_ids": len({item.stable_id for item in fetch.items}),
                    "snapshot_hash": items_hash(fetch.items),
                    "samples": len(samples),
                    "stable_id_sets_consistent": True,
                    "diagnostics": fetch.diagnostics,
                },
                warnings=warnings,
            ),
            0,
        )

    def _fetch(self, manifest: MonitorManifest) -> FetchResult:
        adapter = self.adapters.get(manifest.target.adapter)
        fetch = adapter.fetch(manifest)
        validate_fetch(fetch)
        return fetch

    def _collect_consecutive_samples(
        self,
        manifest: MonitorManifest,
        *,
        required: int,
        max_attempts: int,
        compare: str,
        initial: FetchResult | None = None,
    ) -> tuple[list[FetchResult], list[str]]:
        samples: list[FetchResult] = [initial] if initial else []
        warnings: list[str] = list(initial.warnings) if initial else []
        consecutive = 1 if initial else 0
        while len(samples) < max_attempts:
            if samples and manifest.validation.sample_interval_seconds:
                self.sleeper(manifest.validation.sample_interval_seconds)
            current = self._fetch(manifest)
            warnings.extend(current.warnings)
            if samples:
                matches = (
                    same_id_set(samples[-1].items, current.items)
                    if compare == "ids"
                    else same_snapshot(samples[-1].items, current.items)
                )
                consecutive = consecutive + 1 if matches else 1
            else:
                consecutive = 1
            samples.append(current)
            if consecutive >= required:
                return samples, list(dict.fromkeys(warnings))
        raise InvalidSnapshot(
            "独立抓取未形成连续一致的可信快照",
            details={"reason": "SNAPSHOT_INCONSISTENT", "attempts": len(samples), "required": required},
        )

    def _cache_images(
        self,
        manifest: MonitorManifest,
        items: list,
    ) -> tuple[list[str], dict[str, Any], dict[str, dict[str, object]]]:
        root = (self.state_dir / "images" / manifest.monitor_id).resolve()
        if not manifest.state.image_cache:
            entries = {
                item.stable_id: {
                    "cache_status": "DISABLED",
                    "original_image_url": item.image_url,
                    "cached_image_path": None,
                    "content_type": None,
                    "attachment_ready": False,
                }
                for item in items
            }
            return [], self._image_cache_summary(False, root, entries), entries
        cache = self.image_cache_factory(root)
        try:
            entries, warnings = cache.cache_with_report(items)
            return warnings, self._image_cache_summary(True, root, entries), entries
        finally:
            close = getattr(cache, "close", None)
            if close:
                close()

    @staticmethod
    def _image_cache_summary(
        enabled: bool,
        root: Path,
        entries: dict[str, dict[str, object]],
    ) -> dict[str, Any]:
        statuses = [str(entry["cache_status"]) for entry in entries.values()]
        return {
            "enabled": enabled,
            "cache_root": str(root),
            "items_considered": len(entries),
            "attempted": sum(bool(entry.get("original_image_url")) for entry in entries.values()),
            "available": sum(bool(entry.get("attachment_ready")) for entry in entries.values()),
            "downloaded": statuses.count("AVAILABLE"),
            "reused": statuses.count("AVAILABLE_FROM_PREVIOUS_RUN"),
            "failed": statuses.count("FAILED"),
            "without_image_url": statuses.count("NO_IMAGE_URL"),
        }

    def _attach_image_cache_to_diff(
        self,
        manifest: MonitorManifest,
        diff: dict[str, list[dict[str, Any]]],
        current_entries: dict[str, dict[str, object]],
    ) -> None:
        for change_type in ("added", "modified"):
            for change in diff[change_type]:
                stable_id = str(change.get("stable_id") or change.get("after", {}).get("stable_id") or "")
                original_url = (
                    change.get("image_url")
                    if change_type == "added"
                    else change.get("after", {}).get("image_url")
                )
                change["image_cache"] = current_entries.get(
                    stable_id,
                    {
                        "cache_status": "NOT_CHECKED",
                        "original_image_url": original_url,
                        "cached_image_path": None,
                        "content_type": None,
                        "attachment_ready": False,
                    },
                )

        if not manifest.state.image_cache:
            for change in diff["removed"]:
                change["image_cache"] = {
                    "cache_status": "DISABLED",
                    "original_image_url": change.get("image_url"),
                    "cached_image_path": None,
                    "content_type": None,
                    "attachment_ready": False,
                }
            return

        root = (self.state_dir / "images" / manifest.monitor_id).resolve()
        cache = self.image_cache_factory(root)
        try:
            for change in diff["removed"]:
                historical = cache.locate_historical(
                    str(change.get("stable_id") or ""),
                    change.get("image_url"),
                )
                change["image_cache"] = historical
        finally:
            close = getattr(cache, "close", None)
            if close:
                close()

    @staticmethod
    def _events_for_run(
        manifest: MonitorManifest,
        run_id: str,
        idempotency_key: str,
        status: str,
        diff: dict[str, list[dict[str, Any]]],
        human_summary: dict[str, Any],
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        if status == "NO_CHANGE" and manifest.notification.send_no_change_report:
            events.append(
                {
                    "event_id": str(uuid.uuid4()),
                    "event_type": "inventory.no_change",
                    "dedupe_key": f"{idempotency_key}:no-change",
                    "payload": {
                        "monitor_id": manifest.monitor_id,
                        "run_id": run_id,
                        "status": status,
                        "human_summary_zh": human_summary["headline"],
                    },
                }
            )
        for change_type in ("added", "removed", "modified"):
            for index, change in enumerate(diff[change_type]):
                stable_id = change.get("stable_id") or change.get("after", {}).get("stable_id")
                events.append(
                    {
                        "event_id": str(uuid.uuid4()),
                        "event_type": f"inventory.{change_type}",
                        "dedupe_key": f"{idempotency_key}:{change_type}:{stable_id}:{index}",
                        "payload": {
                            "monitor_id": manifest.monitor_id,
                            "run_id": run_id,
                            "change": change,
                            "human_summary_zh": change_summary_zh(change_type, change),
                        },
                    }
                )
        return events

    def _record_invalid(
        self,
        operation: str,
        manifest: MonitorManifest,
        run_id: str,
        trigger: str,
        idempotency_key: str,
        exc: InvalidSnapshot,
    ) -> ServiceResult:
        error = {"code": exc.code, "message": exc.message, "details": exc.details}
        self.storage.record_invalid(
            monitor_id=manifest.monitor_id,
            run_id=run_id,
            trigger=trigger,
            idempotency_key=idempotency_key,
            error=error,
        )
        return (
            result_envelope(
                operation=operation,
                status="INVALID",
                ok=False,
                monitor_id=manifest.monitor_id,
                run_id=run_id,
                state_modified=False,
                result={"last_verified_snapshot_preserved": True},
                error=error,
            ),
            2,
        )

    def close(self) -> None:
        self.storage.close()
        for name in self.adapters.names():
            adapter = self.adapters.get(name)
            close = getattr(adapter, "close", None)
            if close:
                close()
