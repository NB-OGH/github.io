#!/usr/bin/env python3
"""BVLS World Meet 2026 Shopify export and dashboard sync engine."""

from __future__ import annotations

import csv
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

API_VERSION = os.getenv("SHOPIFY_API_VERSION", "2025-10")
DEFAULT_SINCE_DATE = "2026-01-01"
DEFAULT_OUTPUT_DIR = "bvls_worldmeet_results"

ADULT_PACKAGES = {
    "Beaver Bronze",
    "Moose Silver",
    "Cobra Chicken Gold",
    "Lion VIP Diamond",
}
SHIRT_PACKAGES = {"Cobra Chicken Gold", "Lion VIP Diamond"}
VIP_PACKAGE = "Lion VIP Diamond"
LUAU_TITLE = "Lakeshore Luau - Pre BVWM 2026 Mini Event"
LUAU_PACKAGE = "Lakeshore Luau Mini Event"
COUNTABLE_FINANCIAL_STATUSES = {"PAID", "PARTIALLY_REFUNDED"}


def clean(value: Any) -> str:
    return str(value or "").strip()


def norm(value: Any) -> str:
    return clean(value).lower()


def http_post_json(url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout: int = 90) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}\n{body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error calling {url}: {exc}") from exc


def http_post_form(url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout: int = 90) -> Dict[str, Any]:
    data = urllib.parse.urlencode(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}\n{body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error calling {url}: {exc}") from exc


def graphql(shop_domain: str, token: str, query: str, variables: Dict[str, Any]) -> Dict[str, Any]:
    body = http_post_json(
        f"https://{shop_domain}/admin/api/{API_VERSION}/graphql.json",
        {"Content-Type": "application/json", "X-Shopify-Access-Token": token},
        {"query": query, "variables": variables},
    )
    if body.get("errors"):
        raise RuntimeError("GraphQL errors:\n" + json.dumps(body["errors"], indent=2))
    if "data" not in body:
        raise RuntimeError("GraphQL response did not contain data")
    return body["data"]


ORDER_QUERY = """
query WorldMeetOrders($cursor: String, $searchQuery: String!) {
  orders(first: 50, after: $cursor, query: $searchQuery, sortKey: CREATED_AT) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      name
      createdAt
      displayFinancialStatus
      displayFulfillmentStatus
      cancelledAt
      lineItems(first: 250) {
        nodes {
          title
          quantity
          currentQuantity
          sku
          variantTitle
          customAttributes { key value }
          product { title }
        }
      }
    }
  }
}
"""


def fetch_orders(shop_domain: str, token: str, since_date: str) -> List[Dict[str, Any]]:
    search_query = f"created_at:>={since_date}"
    orders: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    while True:
        data = graphql(shop_domain, token, ORDER_QUERY, {"cursor": cursor, "searchQuery": search_query})
        connection = data.get("orders") or {}
        orders.extend(connection.get("nodes", []))
        page_info = connection.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")
        time.sleep(0.15)
    return orders


def attr_map(custom_attrs: Iterable[Dict[str, Any]]) -> Dict[str, str]:
    mapped: Dict[str, str] = {}
    for attr in custom_attrs or []:
        key = clean(attr.get("key"))
        value = clean(attr.get("value"))
        if key:
            mapped[key.lower()] = value
            mapped[key] = value
    return mapped


def is_world_meet_line(product_title: str, line_title: str) -> bool:
    text = norm(f"{product_title} {line_title}")
    return "world meet" in text or "bvwm" in text


def detect_package(product_title: str, line_title: str) -> str:
    text = norm(f"{product_title} {line_title}")
    if norm(product_title) == norm(LUAU_TITLE):
        return LUAU_PACKAGE
    if "beaver" in text or "bronze" in text:
        return "Beaver Bronze"
    if "moose" in text or "silver" in text:
        return "Moose Silver"
    if "cobra" in text or "goose" in text or "gold" in text:
        return "Cobra Chicken Gold"
    if "lion" in text or "vip" in text or "diamond" in text:
        return "Lion VIP Diamond"
    if "cub" in text or "kid" in text or "kids" in text:
        return "Cubs Kids Menu"
    return "Unknown"


def int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def should_count_order(order: Dict[str, Any]) -> Tuple[bool, str]:
    status = clean(order.get("displayFinancialStatus")).upper().replace(" ", "_")
    if order.get("cancelledAt"):
        return False, "Order cancelled"
    if status not in COUNTABLE_FINANCIAL_STATUSES:
        return False, f"Financial status not counted: {status or 'blank'}"
    return True, ""


def extract_lines(orders: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for order in orders:
        count_order, exclusion_reason = should_count_order(order)
        for item in (order.get("lineItems") or {}).get("nodes", []):
            product_title = clean((item.get("product") or {}).get("title"))
            line_title = clean(item.get("title"))
            if not is_world_meet_line(product_title, line_title):
                continue
            attrs = attr_map(item.get("customAttributes") or [])
            current_qty = int_value(item.get("currentQuantity"))
            original_qty = int_value(item.get("quantity"))
            rows.append({
                "Order": clean(order.get("name")),
                "Created At": clean(order.get("createdAt")),
                "Financial Status": clean(order.get("displayFinancialStatus")),
                "Fulfillment Status": clean(order.get("displayFulfillmentStatus")),
                "Cancelled At": clean(order.get("cancelledAt")),
                "Counted": "Yes" if count_order and current_qty > 0 else "No",
                "Not Counted Reason": exclusion_reason if not count_order else ("Zero current quantity" if current_qty <= 0 else ""),
                "Package": detect_package(product_title, line_title),
                "Product Title": product_title,
                "Line Item Title": line_title,
                "Variant Title": clean(item.get("variantTitle")),
                "SKU": clean(item.get("sku")),
                "Original Quantity": original_qty,
                "Current Quantity": current_qty,
                "Orderable Quantity": current_qty if count_order else 0,
                "Attendee Names": attrs.get("attendee names", ""),
                "Food Choice": attrs.get("food choice", ""),
                "T-Shirt Size": attrs.get("t-shirt size", "") or attrs.get("tshirt size", "") or attrs.get("shirt size", ""),
                "Hat Choice": attrs.get("hat choice", ""),
                "All Properties JSON": json.dumps(item.get("customAttributes") or [], ensure_ascii=False),
            })
    return rows


def add_count(counts: Dict[str, int], key: str, qty: int) -> None:
    key = clean(key) or "Not Specified"
    counts[key] = counts.get(key, 0) + qty


def aggregate(rows: List[Dict[str, Any]]) -> Tuple[Dict[str, int], Dict[str, int], Dict[str, int], Dict[str, int], List[Dict[str, Any]]]:
    package_counts: Dict[str, int] = {}
    meal_counts: Dict[str, int] = {}
    shirt_counts: Dict[str, int] = {}
    hat_counts: Dict[str, int] = {}
    exceptions: List[Dict[str, Any]] = []
    for row in rows:
        qty = int_value(row.get("Orderable Quantity"))
        package = clean(row.get("Package"))
        issues: List[str] = []
        if clean(row.get("Counted")) != "Yes":
            issues.append(clean(row.get("Not Counted Reason")) or "Not counted")
        if qty > 0:
            add_count(package_counts, package, qty)
            if package in ADULT_PACKAGES:
                add_count(meal_counts, row.get("Food Choice", ""), qty)
                if not clean(row.get("Food Choice")):
                    issues.append("Missing Food Choice")
            if package in SHIRT_PACKAGES:
                add_count(shirt_counts, row.get("T-Shirt Size", ""), qty)
                if not clean(row.get("T-Shirt Size")):
                    issues.append("Missing T-Shirt Size")
            if package == VIP_PACKAGE:
                add_count(hat_counts, row.get("Hat Choice", ""), qty)
                if not clean(row.get("Hat Choice")):
                    issues.append("Missing Hat Choice")
        if package == "Unknown":
            issues.append("Unknown World Meet package")
        if int_value(row.get("Original Quantity")) > 1:
            issues.append("Quantity > 1, verify line-item properties apply to all attendees")
        if issues:
            copy = dict(row)
            copy["Issues"] = "; ".join(dict.fromkeys(i for i in issues if i))
            exceptions.append(copy)
    return package_counts, meal_counts, shirt_counts, hat_counts, exceptions


def write_csv(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def counts_to_rows(counts: Dict[str, int], label: str) -> List[Dict[str, Any]]:
    return [{label: key, "Quantity": qty} for key, qty in sorted(counts.items())]


def fixed_items(package_counts: Dict[str, int]) -> List[Dict[str, Any]]:
    bronze = package_counts.get("Beaver Bronze", 0)
    silver = package_counts.get("Moose Silver", 0)
    gold = package_counts.get("Cobra Chicken Gold", 0)
    vip = package_counts.get("Lion VIP Diamond", 0)
    kids = package_counts.get("Cubs Kids Menu", 0)
    adult_total = bronze + silver + gold + vip
    patch_total = silver + gold + vip
    shirt_total = gold + vip
    return [
        {"Item": "Adult meals", "Quantity": adult_total, "Source": "Bronze + Silver + Gold + VIP"},
        {"Item": "Kids meals", "Quantity": kids, "Source": "Kids package"},
        {"Item": "World Meet TPU patches", "Quantity": patch_total, "Source": "Silver + Gold + VIP"},
        {"Item": "T-shirts", "Quantity": shirt_total, "Source": "Gold + VIP"},
        {"Item": "Beard oil", "Quantity": shirt_total, "Source": "Gold + VIP"},
        {"Item": "Beard balm", "Quantity": shirt_total, "Source": "Gold + VIP"},
        {"Item": "VIP Lakeshore patch", "Quantity": vip, "Source": "VIP"},
        {"Item": "Hockey puck bottle opener", "Quantity": vip, "Source": "VIP"},
        {"Item": "Drawstring bag", "Quantity": vip, "Source": "VIP"},
        {"Item": "VIP hats", "Quantity": vip, "Source": "VIP"},
    ]


def attendee_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{
        "Order": row.get("Order", ""),
        "Package": row.get("Package", ""),
        "Quantity": row.get("Orderable Quantity", 0),
        "Attendee Names": row.get("Attendee Names", ""),
        "Food Choice": row.get("Food Choice", ""),
        "T-Shirt Size": row.get("T-Shirt Size", ""),
        "Hat Choice": row.get("Hat Choice", ""),
    } for row in rows if int_value(row.get("Orderable Quantity")) > 0]


def export_orders(shop_domain: str, token: str, since_date: str = DEFAULT_SINCE_DATE, expected_total: int = 114, output_dir: Path | str = DEFAULT_OUTPUT_DIR) -> Dict[str, Any]:
    output_dir = Path(output_dir)
    orders = fetch_orders(shop_domain, token, since_date)
    rows = extract_lines(orders)
    package_counts, meal_counts, shirt_counts, hat_counts, exceptions = aggregate(rows)
    adult_total = sum(package_counts.get(package, 0) for package in ADULT_PACKAGES)
    raw_fields = [
        "Order", "Created At", "Financial Status", "Fulfillment Status", "Cancelled At", "Counted", "Not Counted Reason",
        "Package", "Product Title", "Line Item Title", "Variant Title", "SKU", "Original Quantity", "Current Quantity",
        "Orderable Quantity", "Attendee Names", "Food Choice", "T-Shirt Size", "Hat Choice", "All Properties JSON",
    ]
    write_csv(output_dir / "01_raw_order_lines.csv", rows, raw_fields)
    write_csv(output_dir / "02_package_totals.csv", counts_to_rows(package_counts, "Package"), ["Package", "Quantity"])
    write_csv(output_dir / "03_fixed_items_to_order.csv", fixed_items(package_counts), ["Item", "Quantity", "Source"])
    write_csv(output_dir / "04_meal_counts.csv", counts_to_rows(meal_counts, "Meal Option"), ["Meal Option", "Quantity"])
    write_csv(output_dir / "05_shirt_size_counts.csv", counts_to_rows(shirt_counts, "T-Shirt Size"), ["T-Shirt Size", "Quantity"])
    write_csv(output_dir / "06_hat_choice_counts.csv", counts_to_rows(hat_counts, "Hat Choice"), ["Hat Choice", "Quantity"])
    write_csv(output_dir / "07_exceptions_review.csv", exceptions, raw_fields + ["Issues"])
    write_csv(output_dir / "08_attendee_order_detail.csv", attendee_rows(rows), ["Order", "Package", "Quantity", "Attendee Names", "Food Choice", "T-Shirt Size", "Hat Choice"])
    summary_rows = [
        {"Metric": "Shop Domain", "Value": shop_domain},
        {"Metric": "API Version", "Value": API_VERSION},
        {"Metric": "Since Date", "Value": since_date},
        {"Metric": "Orders fetched", "Value": len(orders)},
        {"Metric": "World Meet line rows", "Value": len(rows)},
        {"Metric": "Adult packages counted", "Value": adult_total},
        {"Metric": "Expected adult packages", "Value": expected_total},
        {"Metric": "Difference", "Value": adult_total - expected_total},
        {"Metric": "Exceptions", "Value": len(exceptions)},
        {"Metric": "Last Shopify Sync", "Value": time.strftime("%Y-%m-%d %H:%M:%S")},
        {"Metric": "Output Folder", "Value": str(output_dir.resolve())},
    ]
    write_csv(output_dir / "00_run_summary.csv", summary_rows, ["Metric", "Value"])
    return {
        "orders_fetched": len(orders),
        "line_rows": len(rows),
        "adult_total": adult_total,
        "exceptions": len(exceptions),
        "output_dir": str(output_dir.resolve()),
    }
