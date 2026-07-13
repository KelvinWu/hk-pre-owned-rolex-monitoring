from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from .errors import BackupError
from .util import safe_name, utc_now


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class BackupManager:
    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir
        self.backup_dir = state_dir / "backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def create(self, monitor_id: str, *, destination: Path | None = None) -> Path:
        timestamp = utc_now().replace(":", "-")
        destination = destination or self.backup_dir / f"{safe_name(monitor_id)}-{timestamp}.zip"
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory(prefix="hk-rolex-monitoring-backup-") as temp_name:
                stage = Path(temp_name)
                source_db = self.state_dir / "state.db"
                if source_db.exists():
                    target_db = stage / "state.db"
                    source_conn = sqlite3.connect(source_db)
                    target_conn = sqlite3.connect(target_db)
                    try:
                        source_conn.backup(target_conn)
                    finally:
                        target_conn.close()
                        source_conn.close()
                for folder_name in ("images", "raw"):
                    source = self.state_dir / folder_name
                    if source.exists():
                        shutil.copytree(source, stage / folder_name)
                files = sorted(path for path in stage.rglob("*") if path.is_file())
                manifest = {
                    "schema_version": 1,
                    "created_at": utc_now(),
                    "monitor_id": monitor_id,
                    "files": {str(path.relative_to(stage)): _sha256(path) for path in files},
                }
                (stage / "backup-manifest.json").write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    for path in sorted(stage.rglob("*")):
                        if path.is_file():
                            archive.write(path, path.relative_to(stage))
        except Exception as exc:
            raise BackupError(f"创建备份失败: {exc}") from exc
        return destination

    def verify(self, archive_path: Path) -> dict:
        if not archive_path.is_file():
            raise BackupError(f"备份不存在: {archive_path}")
        try:
            with tempfile.TemporaryDirectory(prefix="hk-rolex-monitoring-verify-") as temp_name:
                stage = Path(temp_name)
                with zipfile.ZipFile(archive_path) as archive:
                    for member in archive.infolist():
                        target = (stage / member.filename).resolve()
                        if stage.resolve() not in target.parents and target != stage.resolve():
                            raise BackupError("备份包含不安全路径")
                    archive.extractall(stage)
                manifest_path = stage / "backup-manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                for relative, expected in manifest["files"].items():
                    path = stage / relative
                    if not path.is_file() or _sha256(path) != expected:
                        raise BackupError(f"备份校验失败: {relative}")
                return manifest
        except BackupError:
            raise
        except Exception as exc:
            raise BackupError(f"备份校验失败: {exc}") from exc

    def restore(self, archive_path: Path) -> dict:
        manifest = self.verify(archive_path)
        try:
            with tempfile.TemporaryDirectory(prefix="hk-rolex-monitoring-restore-") as temp_name:
                stage = Path(temp_name)
                with zipfile.ZipFile(archive_path) as archive:
                    archive.extractall(stage)
                for relative in manifest["files"]:
                    source = stage / relative
                    target = self.state_dir / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    temporary = target.with_suffix(target.suffix + ".restore-tmp")
                    shutil.copy2(source, temporary)
                    temporary.replace(target)
        except Exception as exc:
            raise BackupError(f"恢复备份失败: {exc}") from exc
        return manifest
