from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import httpx

from inventory_sentinel.errors import BrowserRequired, InvalidSnapshot, RuntimeFailure
from inventory_sentinel.models import FetchResult, InventoryItem, MonitorManifest
from inventory_sentinel.validation import validate_fetch


class OrientalWatchAdapter:
    name = "orientalwatch-rolex-cpo"
    api_url = "https://www.orientalwatch.com/rolex.asmx/Rolex_Watches2"
    image_base = "https://img.orientalwatch.biz/rolex-certified-pre-owned"

    def __init__(self, *, timeout: float = 30.0, client: httpx.Client | None = None) -> None:
        self._owns_client = client is None
        self.client = client or httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "HKPreOwnedRolexMonitoring/0.1 (+read-only CPO monitor)"},
        )

    def fetch(self, manifest: MonitorManifest) -> FetchResult:
        try:
            page = self.client.get(manifest.target.url)
        except httpx.HTTPError as exc:
            raise RuntimeFailure(f"无法访问东方表行页面: {exc}") from exc
        self._validate_page(page)

        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://www.orientalwatch.com",
            "Referer": manifest.target.url,
        }
        body = {"parameters": {"sortOrder": ["high-low"], "selectedFamily": [""]}}
        try:
            response = self.client.post(self.api_url, headers=headers, json=body)
        except httpx.HTTPError as exc:
            raise RuntimeFailure(f"东方表行数据接口请求失败: {exc}") from exc
        if response.status_code in {401, 403, 429}:
            raise BrowserRequired(
                f"东方表行数据接口需要浏览器或额外授权: HTTP {response.status_code}",
                details={"http_status": response.status_code},
            )
        if response.status_code != 200:
            raise RuntimeFailure(f"东方表行数据接口返回 HTTP {response.status_code}")
        payload = self._parse_response(response)
        return self._normalize(payload, manifest)

    @staticmethod
    def _validate_page(response: httpx.Response) -> None:
        if response.status_code in {401, 403, 429}:
            raise BrowserRequired(
                f"目标页面需要浏览器或额外授权: HTTP {response.status_code}",
                details={"http_status": response.status_code},
            )
        if response.status_code != 200:
            raise RuntimeFailure(f"目标页面返回 HTTP {response.status_code}")
        lowered = response.text.lower()
        blocked_markers = ("captcha", "access denied", "verify you are human", "cloudflare challenge")
        if any(marker in lowered for marker in blocked_markers):
            raise BrowserRequired("目标页面返回了访问验证页")
        if "rolex.asmx/Rolex_Watches2" not in response.text and "rcpo_watches.js" not in response.text:
            raise InvalidSnapshot("目标页面结构不符合东方表行 Rolex CPO 页面", details={"reason": "PAGE_MISMATCH"})

    @staticmethod
    def _parse_response(response: httpx.Response) -> dict[str, Any]:
        try:
            outer = response.json()
            if "d" not in outer or not isinstance(outer["d"], str):
                raise ValueError("缺少 ASMX d 字段")
            payload = json.loads(outer["d"])
        except Exception as exc:
            raise InvalidSnapshot("东方表行接口返回无法解析的双层 JSON", details={"reason": "MALFORMED_JSON"}) from exc
        if "table_column" not in payload or "ds" not in payload:
            raise InvalidSnapshot("东方表行接口响应缺少字段结构", details={"reason": "SCHEMA_MISMATCH"})
        return payload

    def _normalize(self, payload: dict[str, Any], manifest: MonitorManifest) -> FetchResult:
        columns = [column.strip() for column in str(payload["table_column"]).split(",") if column.strip()]
        index = {column: position for position, column in enumerate(columns)}
        required = {"Lot_Number_Code"}
        missing = sorted(required - index.keys())
        if missing:
            raise InvalidSnapshot("东方表行接口缺少必要列", details={"reason": "MISSING_COLUMNS", "columns": missing})
        try:
            rows = payload["ds"]["filter_result"]
        except Exception as exc:
            raise InvalidSnapshot("东方表行接口缺少商品集合", details={"reason": "MISSING_RESULTS"}) from exc
        if not isinstance(rows, list):
            raise InvalidSnapshot("东方表行商品集合格式错误", details={"reason": "RESULTS_NOT_LIST"})

        def value(row: list[Any], name: str) -> Any:
            position = index.get(name)
            return row[position] if position is not None and position < len(row) else None

        items: list[InventoryItem] = []
        warnings: list[str] = []
        for row_number, row in enumerate(rows):
            if not isinstance(row, list):
                raise InvalidSnapshot(
                    "东方表行商品行格式错误",
                    details={"reason": "ROW_NOT_LIST", "row": row_number},
                )
            lot_code = str(value(row, "Lot_Number_Code") or "").strip()
            family_code = value(row, "Family_Code")
            title = value(row, "Family_txt")
            if not family_code:
                warnings.append(f"商品 {lot_code or row_number} 缺少 Family_Code，已保留但不构造详情页")
            optional_fields = {
                "Family_txt": title,
                "List_Price": value(row, "List_Price"),
                "Currency_Code": value(row, "Currency_Code"),
            }
            missing_optional = [name for name, item_value in optional_fields.items() if item_value in (None, "")]
            if missing_optional:
                warnings.append(
                    f"商品 {lot_code or row_number} 缺少非身份字段: {', '.join(missing_optional)}；已保留商品"
                )
            year_raw_1 = value(row, "RL_Date_1")
            year_raw_2 = value(row, "RL_Date_2")

            def usable_year(raw: Any) -> int | None:
                if raw in (None, "", 1900, "1900"):
                    return None
                try:
                    parsed = int(str(raw).strip())
                except (TypeError, ValueError):
                    return None
                return parsed if 1900 <= parsed <= 2200 else None

            parsed_year_1 = usable_year(year_raw_1)
            parsed_year_2 = usable_year(year_raw_2)
            year = parsed_year_1 if parsed_year_1 is not None else parsed_year_2
            year_source = (
                "RL_Date_1"
                if parsed_year_1 is not None
                else "RL_Date_2"
                if parsed_year_2 is not None
                else None
            )
            reference_raw = value(row, "Watch_Reference")
            reference_source = "Watch_Reference" if reference_raw not in (None, "") else None
            if reference_raw in (None, ""):
                reference_raw = value(row, "IF_RL_Watch_Reference_ID")
                if reference_raw not in (None, ""):
                    reference_source = "IF_RL_Watch_Reference_ID"
            detail_url = None
            if lot_code and family_code:
                detail_url = f"https://www.orientalwatch.com/zh-hant/rolex-certified-pre-owned/watches/{family_code}/{lot_code}/"
            image_url = None
            if lot_code:
                image_url = f"{self.image_base}/{lot_code}/{lot_code}_SOLDIER_BLACK_01.jpg"
            price_value = value(row, "List_Price")
            try:
                price = Decimal(str(price_value)) if price_value not in (None, "") else None
            except Exception:
                price = None
                warnings.append(f"商品 {lot_code or row_number} 的 List_Price 无法解析；已保留商品")
            items.append(
                InventoryItem(
                    stable_id=lot_code,
                    source_id=lot_code,
                    title=str(title) if title else None,
                    family_code=str(family_code) if family_code else None,
                    year=year,
                    price=price,
                    currency=value(row, "Currency_Code"),
                    diameter=value(row, "Diameter_txt"),
                    material=value(row, "Material_txt"),
                    bracelet=value(row, "Bracelet_txt"),
                    reference=str(reference_raw).strip() if reference_raw not in (None, "") else None,
                    detail_url=detail_url,
                    image_url=image_url,
                    attributes={
                        "lot_number_id": value(row, "Lot_Number_ID"),
                        "sku_id": value(row, "SKU_ID"),
                        "formatted_list_price": value(row, "Formatted_List_Price"),
                        "year_raw_1": year_raw_1,
                        "year_raw_2": year_raw_2,
                        "year_source": year_source,
                        "reference_raw": reference_raw,
                        "reference_source": reference_source,
                    },
                )
            )
        result = FetchResult(
            items=items,
            warnings=warnings,
            diagnostics={
                "source": self.name,
                "api_url": self.api_url,
                "raw_count": len(rows),
                "normalized_count": len(items),
                "column_count": len(columns),
            },
            raw_payload=payload,
        )
        validate_fetch(result)
        return result

    def close(self) -> None:
        if self._owns_client:
            self.client.close()
