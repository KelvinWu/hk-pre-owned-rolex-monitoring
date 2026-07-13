from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from .models import InventoryItem


FIELD_LABELS_ZH = {
    "source_id": "来源货号",
    "title": "名称",
    "family_code": "系列代码",
    "year": "年份",
    "condition": "成色",
    "price": "价格",
    "currency": "币种",
    "diameter": "表径",
    "material": "材质",
    "bracelet": "表带",
    "reference": "Rolex 型号",
    "detail_url": "详情页",
    "image_url": "图片",
    "attributes": "其他资料",
}


def product_identity(item: InventoryItem) -> dict[str, Any]:
    """返回同时适合系统审计和面向用户展示的腕表身份。"""

    product_name = item.title or "腕表"
    rolex_reference = item.reference
    parts = [
        f"Rolex {product_name}",
        f"型号 {rolex_reference or '未提供'}",
        f"东方表行货号 {item.stable_id}",
    ]
    if item.year:
        parts.append(f"年份 {item.year}")
    if item.condition != "unknown":
        parts.append(f"成色 {item.condition}")
    identity = {
        "brand": "Rolex",
        "product_name": product_name,
        "rolex_reference": rolex_reference,
        "oriental_lot_number": item.stable_id,
        "year": item.year,
        "diameter": item.diameter,
        "material": item.material,
        "bracelet": item.bracelet,
        "detail_url": item.detail_url,
        "display_name": "｜".join(parts),
    }
    if item.condition != "unknown":
        identity["condition"] = item.condition
    return identity


def item_change_payload(item: InventoryItem) -> dict[str, Any]:
    payload = item.model_dump(mode="json")
    payload["product_identity"] = product_identity(item)
    return payload


def _identity_phrase(identity: dict[str, Any]) -> str:
    details = [
        f"型号 {identity.get('rolex_reference') or '未提供'}",
        f"东方表行货号 {identity.get('oriental_lot_number') or '未提供'}",
    ]
    if identity.get("year"):
        details.append(f"年份 {identity['year']}")
    if identity.get("condition") not in (None, "", "unknown"):
        details.append(f"成色 {identity['condition']}")
    return f"Rolex {identity.get('product_name') or '腕表'}（{'；'.join(details)}）"


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _format_money(value: Any, currency: str | None, *, signed: bool = False) -> str:
    amount = _decimal(value)
    if amount is None:
        return "价格未提供"
    currency = (currency or "").upper()
    prefix = {"HKD": "HK$", "USD": "US$", "CNY": "CN¥"}.get(
        currency, f"{currency} " if currency else ""
    )
    absolute = abs(amount)
    digits = f"{absolute:,.0f}" if absolute == absolute.to_integral_value() else f"{absolute:,.2f}"
    sign = "+" if signed and amount > 0 else "-" if amount < 0 else ""
    return f"{sign}{prefix}{digits}"


def change_summary_zh(change_type: str, change: dict[str, Any]) -> str:
    identity = change.get("product_identity") or {}
    label = _identity_phrase(identity)
    if change_type == "added":
        return f"新上架：{label}，挂牌价 {_format_money(change.get('price'), change.get('currency'))}。"
    if change_type == "removed":
        return f"已下架：{label}，最后挂牌价 {_format_money(change.get('price'), change.get('currency'))}。"

    before = change.get("before") or {}
    after = change.get("after") or {}
    fields = list(change.get("fields") or [])
    if "price" in fields:
        old_price = _decimal(before.get("price"))
        new_price = _decimal(after.get("price"))
        old_currency = before.get("currency")
        new_currency = after.get("currency")
        old_text = _format_money(old_price, old_currency)
        new_text = _format_money(new_price, new_currency)
        if old_price is not None and new_price is not None and old_currency == new_currency:
            delta = new_price - old_price
            direction = "价格上调" if delta > 0 else "价格下调" if delta < 0 else "价格变化"
            detail = _format_money(delta, new_currency, signed=True)
            if old_price:
                percent = delta / old_price * Decimal("100")
                detail += f"，{percent:+.2f}%"
            line = f"{direction}：{label}，{old_text} → {new_text}（{detail}）"
        else:
            line = f"价格变化：{label}，{old_text} → {new_text}"
        remaining = [FIELD_LABELS_ZH.get(field, field) for field in fields if field != "price"]
        if remaining:
            line += f"；同时变化：{'、'.join(remaining)}"
        return line + "。"

    labels = [FIELD_LABELS_ZH.get(field, field) for field in fields]
    return f"资料变化：{label}；变化字段：{'、'.join(labels) if labels else '未说明'}。"


def build_human_summary_zh(
    status: str,
    diff: dict[str, list[dict[str, Any]]],
    item_count: int,
) -> dict[str, Any]:
    if status == "NO_CHANGE":
        return {"headline": f"库存无变化，当前共 {item_count} 只。", "changes": []}
    added = len(diff.get("added", []))
    removed = len(diff.get("removed", []))
    modified = len(diff.get("modified", []))
    lines = [
        change_summary_zh(change_type, change)
        for change_type in ("added", "removed", "modified")
        for change in diff.get(change_type, [])
    ]
    return {
        "headline": f"库存发生 {added + removed + modified} 项变化：上新 {added}、下架 {removed}、资料变化 {modified}。",
        "changes": lines,
    }
