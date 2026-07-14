from __future__ import annotations

from .models import (
    MonitorManifest,
    RuntimeNotification,
    RuntimeOperation,
    RuntimePlan,
    RuntimeRequirements,
)


def build_runtime_plan(manifest: MonitorManifest) -> RuntimePlan:
    operations: list[RuntimeOperation] = []
    for job in manifest.schedule.jobs:
        logical_id = f"{manifest.monitor_id}:{job.role}"
        operations.append(
            RuntimeOperation(
                op="schedule.upsert",
                logical_id=logical_id,
                required_capability="scheduler",
                idempotency_key=f"schedule:{logical_id}:{job.cron}:{manifest.schedule.timezone}",
                parameters={
                    "cron": job.cron,
                    "timezone": manifest.schedule.timezone,
                    "retry_delays_seconds": manifest.validation.retry_delays_seconds,
                    "invocation": {
                        "skill": "hk-pre-owned-rolex-monitoring",
                        "command": [
                            "monitor",
                            "run",
                            "--id",
                            manifest.monitor_id,
                            "--trigger",
                            job.role,
                            "--json",
                        ],
                    },
                },
                verification={"required": True, "method": "host_requery", "record_external_id": True},
            )
        )
    return RuntimePlan(
        monitor_id=manifest.monitor_id,
        operations=operations,
        notification=RuntimeNotification(
            provider=manifest.notification.provider,
            recipient=manifest.notification.recipient,
            include_images=manifest.notification.include_images,
            event_types=[
                "inventory.added",
                "inventory.removed",
                "inventory.modified",
                "inventory.no_change",
                "monitor.invalid",
            ],
            list_command=["outbox", "list", "--id", manifest.monitor_id, "--json"],
            ack_command=[
                "outbox",
                "ack",
                "--event-id",
                "<event_id>",
                "--provider",
                "<provider>",
                "--external-message-id",
                "<external_message_id>",
                "--delivered-at",
                "<ISO-8601>",
                "--verified",
                "--json",
            ],
        ),
        requirements=RuntimeRequirements(
            scheduler=bool(manifest.schedule.jobs),
            notification_delivery=True,
            persistent_state=True,
        ),
    )
