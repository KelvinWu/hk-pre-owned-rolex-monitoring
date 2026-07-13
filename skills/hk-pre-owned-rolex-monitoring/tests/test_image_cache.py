from __future__ import annotations

from pathlib import Path

import httpx

from inventory_sentinel.image_cache import ImageCache
from inventory_sentinel.models import InventoryItem


def test_image_cache_validates_content_and_keeps_historical_files(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("good.jpg"):
            return httpx.Response(200, content=b"\xff\xd8\xffimage", headers={"content-type": "image/jpeg"}, request=request)
        if request.url.path.endswith("fake.jpg"):
            return httpx.Response(200, content=b"not-a-jpeg", headers={"content-type": "image/jpeg"}, request=request)
        return httpx.Response(200, content=b"html", headers={"content-type": "text/html"}, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    cache = ImageCache(tmp_path / "images", client=client)
    items = [
        InventoryItem(stable_id="LOT-1", source_id="LOT-1", image_url="https://img.test/good.jpg"),
        InventoryItem(stable_id="LOT-2", source_id="LOT-2", image_url="https://img.test/error.jpg"),
        InventoryItem(stable_id="LOT-3", source_id="LOT-3", image_url="https://img.test/fake.jpg"),
    ]
    warnings = cache.cache(items)
    assert (tmp_path / "images/LOT-1.jpg").read_bytes().startswith(b"\xff\xd8")
    assert len(warnings) == 2
    assert "LOT-2" in warnings[0] and "LOT-3" in warnings[1]

    cache.cache([])
    assert (tmp_path / "images/LOT-1.jpg").is_file()
    client.close()


def test_image_cache_reports_paths_and_falls_back_to_saved_file(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("good.jpg"):
            return httpx.Response(
                200,
                content=b"\xff\xd8\xffimage",
                headers={"content-type": "image/jpeg"},
                request=request,
            )
        return httpx.Response(404, content=b"missing", headers={"content-type": "text/html"}, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    cache = ImageCache(tmp_path / "images", client=client)
    item = InventoryItem(stable_id="LOT-1", source_id="LOT-1", image_url="https://img.test/good.jpg")
    report, warnings = cache.cache_with_report([item])
    assert warnings == []
    assert report["LOT-1"] == {
        "cache_status": "AVAILABLE",
        "original_image_url": "https://img.test/good.jpg",
        "cached_image_path": str((tmp_path / "images/LOT-1.jpg").resolve()),
        "content_type": "image/jpeg",
        "attachment_ready": True,
    }

    unavailable = item.model_copy(update={"image_url": "https://img.test/offline.jpg"})
    fallback, warnings = cache.cache_with_report([unavailable])
    assert len(warnings) == 1
    assert fallback["LOT-1"]["cache_status"] == "AVAILABLE_FROM_PREVIOUS_RUN"
    assert fallback["LOT-1"]["attachment_ready"] is True

    historical = cache.locate_historical("LOT-1", unavailable.image_url)
    assert historical["cache_status"] == "AVAILABLE_HISTORICAL"
    assert historical["cached_image_path"].endswith("/LOT-1.jpg")
    client.close()
