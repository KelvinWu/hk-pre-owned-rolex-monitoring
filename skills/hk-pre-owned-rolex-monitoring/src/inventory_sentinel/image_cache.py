from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .models import InventoryItem
from .util import safe_name


CONTENT_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
EXTENSION_CONTENT_TYPES = {extension: content_type for content_type, extension in CONTENT_EXTENSIONS.items()}


def _cache_entry(
    status: str,
    original_image_url: str | None,
    cached_path: Path | None,
    content_type: str | None = None,
    *,
    metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    available = cached_path is not None and cached_path.is_file()
    metadata = metadata or {}
    return {
        "cache_status": status,
        "original_image_url": original_image_url,
        "cached_image_path": str(cached_path.resolve()) if available else None,
        "content_type": content_type,
        "attachment_ready": available,
        "sha256": metadata.get("sha256"),
        "byte_size": metadata.get("byte_size"),
        "etag": metadata.get("etag"),
        "last_modified": metadata.get("last_modified"),
        "cached_at": metadata.get("cached_at"),
    }


def _valid_image_signature(content_type: str, content: bytes) -> bool:
    if content_type == "image/jpeg":
        return content.startswith(b"\xff\xd8\xff")
    if content_type == "image/png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/gif":
        return content.startswith((b"GIF87a", b"GIF89a"))
    if content_type == "image/webp":
        return len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP"
    return False


class ImageCache:
    def __init__(self, root: Path, *, client: httpx.Client | None = None, timeout: float = 20.0) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=True)
        self.metadata_path = self.root / ".image-metadata.json"
        self.metadata = self._load_metadata()

    def _load_metadata(self) -> dict[str, dict[str, object]]:
        if not self.metadata_path.is_file():
            return {}
        try:
            payload = json.loads(self.metadata_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _save_metadata(self) -> None:
        temporary = self.metadata_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(self.metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.metadata_path)

    @staticmethod
    def _file_metadata(path: Path, content_type: str) -> dict[str, object] | None:
        try:
            content = path.read_bytes()
        except OSError:
            return None
        if not _valid_image_signature(content_type, content):
            return None
        return {
            "sha256": "sha256:" + hashlib.sha256(content).hexdigest(),
            "byte_size": len(content),
        }

    def _existing_path(self, stable_id: str) -> Path | None:
        stem = safe_name(stable_id)
        for extension in CONTENT_EXTENSIONS.values():
            candidate = self.root / f"{stem}{extension}"
            if candidate.is_file():
                return candidate
        return None

    def locate_historical(self, stable_id: str, original_image_url: str | None) -> dict[str, object]:
        existing = self._existing_path(stable_id)
        if existing is None:
            return _cache_entry("MISSING", original_image_url, None)
        return _cache_entry(
            "AVAILABLE_HISTORICAL",
            original_image_url,
            existing,
            EXTENSION_CONTENT_TYPES.get(existing.suffix.lower()),
            metadata=self.metadata.get(stable_id),
        )

    def cache_with_report(
        self,
        items: list[InventoryItem],
    ) -> tuple[dict[str, dict[str, object]], list[str]]:
        report: dict[str, dict[str, object]] = {}
        warnings: list[str] = []
        for item in items:
            existing = self._existing_path(item.stable_id)
            previous_metadata = self.metadata.get(item.stable_id, {})
            if not item.image_url:
                report[item.stable_id] = (
                    _cache_entry(
                        "AVAILABLE_FROM_PREVIOUS_RUN",
                        None,
                        existing,
                        EXTENSION_CONTENT_TYPES.get(existing.suffix.lower()) if existing else None,
                        metadata=previous_metadata,
                    )
                    if existing
                    else _cache_entry("NO_IMAGE_URL", None, None)
                )
                continue
            if existing and previous_metadata.get("original_image_url") == item.image_url:
                content_type = EXTENSION_CONTENT_TYPES.get(existing.suffix.lower())
                verified = self._file_metadata(existing, content_type or "")
                if verified and (
                    not previous_metadata.get("sha256")
                    or previous_metadata.get("sha256") == verified["sha256"]
                ):
                    refreshed = {**previous_metadata, **verified}
                    self.metadata[item.stable_id] = refreshed
                    report[item.stable_id] = _cache_entry(
                        "REUSED_VERIFIED",
                        item.image_url,
                        existing,
                        content_type,
                        metadata=refreshed,
                    )
                    continue
            try:
                response = self.client.get(item.image_url)
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if (
                    response.status_code != 200
                    or content_type not in CONTENT_EXTENSIONS
                    or not _valid_image_signature(content_type, response.content)
                ):
                    warnings.append(
                        f"图片缓存失败 {item.stable_id}: HTTP {response.status_code}, "
                        f"Content-Type {content_type or 'unknown'}，文件签名无效或内容为空"
                    )
                    report[item.stable_id] = (
                        _cache_entry(
                            "AVAILABLE_FROM_PREVIOUS_RUN",
                            item.image_url,
                            existing,
                            EXTENSION_CONTENT_TYPES.get(existing.suffix.lower()) if existing else None,
                            metadata=previous_metadata,
                        )
                        if existing
                        else _cache_entry("FAILED", item.image_url, None)
                    )
                    continue
                extension = CONTENT_EXTENSIONS[content_type]
                target = self.root / f"{safe_name(item.stable_id)}{extension}"
                temporary = target.with_suffix(target.suffix + ".tmp")
                temporary.write_bytes(response.content)
                temporary.replace(target)
                metadata = {
                    "original_image_url": item.image_url,
                    "sha256": "sha256:" + hashlib.sha256(response.content).hexdigest(),
                    "byte_size": len(response.content),
                    "etag": response.headers.get("etag"),
                    "last_modified": response.headers.get("last-modified"),
                    "cached_at": datetime.now(timezone.utc).isoformat(),
                }
                self.metadata[item.stable_id] = metadata
                report[item.stable_id] = _cache_entry(
                    "AVAILABLE",
                    item.image_url,
                    target,
                    content_type,
                    metadata=metadata,
                )
            except Exception as exc:
                warnings.append(f"图片缓存失败 {item.stable_id}: {exc}")
                report[item.stable_id] = (
                    _cache_entry(
                        "AVAILABLE_FROM_PREVIOUS_RUN",
                        item.image_url,
                        existing,
                        EXTENSION_CONTENT_TYPES.get(existing.suffix.lower()) if existing else None,
                        metadata=previous_metadata,
                    )
                    if existing
                    else _cache_entry("FAILED", item.image_url, None)
                )
        self._save_metadata()
        return report, warnings

    def cache(self, items: list[InventoryItem]) -> list[str]:
        _, warnings = self.cache_with_report(items)
        return warnings

    def close(self) -> None:
        if self._owns_client:
            self.client.close()
