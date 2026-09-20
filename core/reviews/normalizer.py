"""Amazon 评论标准化与稳定标识生成。"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse


_ELEMENT_ID_PATTERNS = [
    re.compile(r"customer_review[_-]([A-Za-z0-9]+)"),
]
_URL_ID_PATTERNS = [
    re.compile(r"customer-reviews/([A-Z0-9]{8,})", re.I),
    re.compile(r"[?&]reviewId=([A-Z0-9]{8,})", re.I),
]

_MONTHS = {
    "january": 1, "jan": 1, "januar": 1,
    "february": 2, "feb": 2, "februar": 2,
    "march": 3, "mar": 3, "märz": 3, "maerz": 3,
    "april": 4, "apr": 4,
    "may": 5, "mai": 5,
    "june": 6, "jun": 6, "juni": 6,
    "july": 7, "jul": 7, "juli": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9,
    "october": 10, "oct": 10, "oktober": 10, "okt": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12, "dezember": 12, "dez": 12,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def extract_review_id(element_id: str = "", review_url: str = "") -> str:
    for pattern in _ELEMENT_ID_PATTERNS:
        match = pattern.search(element_id or "")
        if match:
            return match.group(1).upper()
    for pattern in _URL_ID_PATTERNS:
        match = pattern.search(review_url or "")
        if match:
            return match.group(1).upper()
    return ""


def extract_asin(value: str) -> str:
    text = str(value or "").strip().upper()
    patterns = (
        r"/DP/([A-Z0-9]{10})",
        r"/GP/PRODUCT/([A-Z0-9]{10})",
        r"/PRODUCT-REVIEWS/([A-Z0-9]{10})",
        r"[?&]ASIN=([A-Z0-9]{10})",
        r"\b([A-Z0-9]{10})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return text


def normalize_marketplace(value: str) -> str:
    text = str(value or "").strip().lower()
    if "://" in text:
        text = urlparse(text).netloc.lower()
    if text.startswith("www."):
        text = text[4:]
    text = text.strip("/")
    return text


def normalize_categories(
    marketplace: str,
    categories: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Normalize Amazon leaf categories and their breadcrumb paths.

    Browse node IDs are preferred.  Some localized/product layouts expose only
    breadcrumb text, so a stable hash is used as a non-empty fallback ID.
    """
    marketplace = normalize_marketplace(marketplace)
    result: List[Dict[str, Any]] = []
    seen = set()
    for index, raw_category in enumerate(categories or []):
        raw = dict(raw_category or {})
        name = str(raw.get("category_name") or raw.get("name") or "").strip()
        raw_path = raw.get("category_path") or raw.get("path") or []
        path: List[Dict[str, str]] = []
        for node in raw_path if isinstance(raw_path, list) else []:
            if isinstance(node, dict):
                node_name = str(node.get("name") or node.get("category_name") or "").strip()
                node_id = str(node.get("id") or node.get("category_id") or "").strip()
            else:
                node_name = str(node or "").strip()
                node_id = ""
            if node_name:
                path.append({"id": node_id, "name": node_name})

        if not name and path:
            name = path[-1]["name"]
        if not name:
            continue
        category_id = str(raw.get("category_id") or raw.get("id") or "").strip()
        if not category_id and path:
            category_id = path[-1].get("id", "")
        if not category_id:
            basis = marketplace + "|" + ">".join(
                node["name"].casefold() for node in path or [{"name": name}]
            )
            category_id = "h_" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]

        key = (marketplace, category_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(
            {
                "marketplace": marketplace,
                "category_id": category_id,
                "category_name": name,
                "category_path": path or [{"id": category_id, "name": name}],
                "is_primary": _as_bool(raw.get("is_primary")) if "is_primary" in raw else index == 0,
                "source": str(raw.get("source") or "breadcrumb").strip() or "breadcrumb",
            }
        )

    if result and not any(item["is_primary"] for item in result):
        result[0]["is_primary"] = True
    elif sum(bool(item["is_primary"]) for item in result) > 1:
        primary_seen = False
        for item in result:
            if item["is_primary"] and not primary_seen:
                primary_seen = True
            elif item["is_primary"]:
                item["is_primary"] = False
    return result


def normalize_review_date(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None

    iso_match = re.search(r"\b(20\d{2}|19\d{2})-(\d{1,2})-(\d{1,2})\b", text)
    if iso_match:
        year, month, day = map(int, iso_match.groups())
        try:
            return datetime(year, month, day).date().isoformat()
        except ValueError:
            return None

    jp_match = re.search(r"(20\d{2}|19\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", text)
    if jp_match:
        year, month, day = map(int, jp_match.groups())
        try:
            return datetime(year, month, day).date().isoformat()
        except ValueError:
            return None

    normalized = text.lower().replace(".", " ").replace(",", " ")
    tokens = re.findall(r"[a-zäöüß]+|\d+", normalized)
    year = next((int(token) for token in tokens if token.isdigit() and len(token) == 4), None)
    month = next((_MONTHS[token] for token in tokens if token in _MONTHS), None)
    day = next(
        (
            int(token)
            for token in tokens
            if token.isdigit() and len(token) <= 2 and 1 <= int(token) <= 31
        ),
        None,
    )
    if year and month and day:
        try:
            return datetime(year, month, day).date().isoformat()
        except ValueError:
            return None
    return None


def _as_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"(\d+(?:[.,]\d+)?)", str(value))
    return float(match.group(1).replace(",", ".")) if match else None


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {
        "1", "true", "yes", "y", "是", "verified", "verified purchase",
    }


def _as_helpful_votes(value: Any) -> int:
    if isinstance(value, int):
        return max(0, value)
    text = str(value or "").strip().lower()
    if not text:
        return 0
    if any(token in text for token in ("one person", "one customer", "eine person", "1 person")):
        return 1
    match = re.search(r"([\d.,]+)", text)
    return int(match.group(1).replace(".", "").replace(",", "")) if match else 0


def _as_image_urls(value: Any) -> List[str]:
    if isinstance(value, (list, tuple, set)):
        items = value
    else:
        text = str(value or "")
        items = text.split("|") if text else []
    result: List[str] = []
    for item in items:
        url = str(item or "").strip()
        if url and url not in result:
            result.append(url)
    return result


def fallback_review_id(marketplace: str, review: Dict[str, Any]) -> str:
    """没有官方 ID 时生成跨 ASIN 稳定指纹，避免变体间重复正文。"""
    basis = "|".join(
        [
            normalize_marketplace(marketplace),
            str(review.get("reviewer_name", "")).strip(),
            str(review.get("review_date") or review.get("date") or "").strip(),
            str(review.get("rating", "")).strip(),
            str(review.get("title", "")).strip(),
            str(review.get("content", "")).strip(),
        ]
    )
    return "h_" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]


def normalize_review(
    asin: str,
    marketplace: str,
    review: Dict[str, Any],
    *,
    seen_at: Optional[str] = None,
) -> Dict[str, Any]:
    raw = dict(review or {})
    marketplace = normalize_marketplace(marketplace)
    asin = extract_asin(asin)
    seen_at = seen_at or utc_now()
    review_url = str(raw.get("review_url") or "").strip()
    review_id = str(raw.get("review_id") or "").strip().upper()
    if not review_id:
        review_id = extract_review_id(str(raw.get("element_id") or ""), review_url)

    date_raw = str(
        raw.get("review_date_raw") or raw.get("review_date") or raw.get("date") or ""
    ).strip()
    image_urls = _as_image_urls(raw.get("image_urls") or raw.get("review_image_urls"))
    original_payload = raw.get("raw_payload")
    if not isinstance(original_payload, dict):
        original_payload = raw
    normalized: Dict[str, Any] = {
        "marketplace": marketplace,
        "asin": asin,
        "parent_asin": extract_asin(str(raw.get("parent_asin") or "")) if raw.get("parent_asin") else "",
        "review_id": review_id,
        "rating": _as_float(raw.get("rating")),
        "title": str(raw.get("title") or "").strip(),
        "content": str(raw.get("content") or "").strip(),
        "reviewer_name": str(raw.get("reviewer_name") or "匿名用户").strip(),
        "review_date": normalize_review_date(date_raw),
        "review_date_raw": date_raw,
        "verified_purchase": _as_bool(raw.get("verified_purchase")),
        "helpful_votes": _as_helpful_votes(raw.get("helpful_votes")),
        "star_filter": str(raw.get("star_filter") or "").strip(),
        "page_number": raw.get("page_number") or None,
        "review_url": review_url,
        "image_urls": image_urls,
        "language": str(raw.get("language") or "").strip() or None,
        "first_seen_at": str(raw.get("first_seen_at") or seen_at),
        "last_seen_at": str(raw.get("last_seen_at") or seen_at),
        "raw_payload": original_payload,
    }
    if not normalized["review_id"]:
        normalized["review_id"] = fallback_review_id(marketplace, normalized)
    return normalized


def normalize_reviews(
    asin: str,
    marketplace: str,
    reviews: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    seen_at = utc_now()
    result: List[Dict[str, Any]] = []
    seen = set()
    for review in reviews or []:
        item = normalize_review(asin, marketplace, review, seen_at=seen_at)
        key = (item["marketplace"], item["review_id"], item["asin"])
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
