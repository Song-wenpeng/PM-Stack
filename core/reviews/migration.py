"""Explicit, recoverable import from the former standalone ReviewCollector."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Dict

from .normalizer import normalize_reviews, utc_now
from .paths import LEGACY_DB_PATH
from .store import ReviewStore


IMPORT_MARKER = "reviewcollector_v3_imported_at"


def import_legacy_database(
    destination: ReviewStore,
    source_path: str | Path = LEGACY_DB_PATH,
) -> Dict[str, Any]:
    """Merge a read-only snapshot into PM Stack without altering the source DB."""
    source = Path(source_path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"未找到旧评论库：{source}")
    if destination.get_setting(IMPORT_MARKER, ""):
        raise RuntimeError("旧 ReviewCollector 评论库已经导入过")

    with tempfile.TemporaryDirectory(prefix="pm-stack-review-import-") as temp_dir:
        snapshot = Path(temp_dir) / "reviews.db"
        source_uri = f"file:{source.as_posix()}?mode=ro"
        source_conn = sqlite3.connect(source_uri, uri=True, timeout=30)
        snapshot_conn = sqlite3.connect(snapshot)
        try:
            source_conn.backup(snapshot_conn)
        finally:
            snapshot_conn.close()
            source_conn.close()

        legacy = ReviewStore(str(snapshot))
        products_imported = 0
        reviews_imported = 0
        try:
            products = legacy.conn.execute("SELECT * FROM products").fetchall()
            for product_row in products:
                product = dict(product_row)
                asin = product.get("asin") or ""
                marketplace = product.get("marketplace") or "amazon.com"
                if not asin:
                    continue

                categories = []
                category_rows = legacy.conn.execute(
                    """
                    SELECT c.category_id, c.category_name, c.category_path,
                           pc.is_primary, pc.source
                    FROM product_categories pc
                    JOIN categories c
                      ON c.marketplace=pc.marketplace AND c.category_id=pc.category_id
                    WHERE pc.marketplace=? AND pc.asin=? AND pc.is_current=1
                    ORDER BY pc.is_primary DESC, pc.first_seen_at
                    """,
                    (marketplace, asin),
                ).fetchall()
                for row in category_rows:
                    category = dict(row)
                    try:
                        category["category_path"] = json.loads(category.get("category_path") or "[]")
                    except json.JSONDecodeError:
                        category["category_path"] = []
                    categories.append(category)

                destination.upsert_product(
                    asin,
                    marketplace,
                    title=product.get("title") or "",
                    parent_asin=product.get("parent_asin") or "",
                    note=product.get("note") or "",
                    categories=categories,
                )
                rows = legacy.conn.execute(
                    """
                    SELECT r.*, pr.star_filter, pr.page_number
                    FROM product_reviews pr
                    JOIN reviews r
                      ON r.marketplace=pr.marketplace AND r.review_id=pr.review_id
                    WHERE pr.marketplace=? AND pr.asin=?
                    """,
                    (marketplace, asin),
                ).fetchall()
                raw_reviews = []
                for row in rows:
                    item = dict(row)
                    try:
                        item["image_urls"] = json.loads(item.get("image_urls") or "[]")
                    except json.JSONDecodeError:
                        item["image_urls"] = []
                    try:
                        item["raw_payload"] = json.loads(item.get("raw_json") or "{}")
                    except json.JSONDecodeError:
                        item["raw_payload"] = {}
                    raw_reviews.append(item)

                normalized = normalize_reviews(asin, marketplace, raw_reviews)
                new_count, _ = destination.add_reviews(asin, marketplace, normalized)
                reviews_imported += new_count
                if normalized:
                    now = utc_now()
                    destination.enqueue_collection(
                        asin,
                        marketplace,
                        product.get("title") or "",
                        normalized,
                        parent_asin=product.get("parent_asin") or "",
                        categories=categories,
                        run={
                            "started_at": now,
                            "finished_at": now,
                            "new_reviews": new_count,
                            "duplicate_reviews": len(normalized) - new_count,
                            "status": "ok",
                            "error": "imported from ReviewCollector",
                        },
                    )
                products_imported += 1
        finally:
            legacy.close()

    destination.set_setting(IMPORT_MARKER, utc_now())
    return {
        "products": products_imported,
        "reviews": reviews_imported,
        "source": str(source),
    }


__all__ = ["IMPORT_MARKER", "import_legacy_database"]

