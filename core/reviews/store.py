"""SQLite 离线缓存与 Supabase outbox。

Supabase 是业务主库；SQLite 只负责抓取期间落盘、离线查询缓存、可重试
同步队列，以及本机设置和恢复令牌。
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .paths import DATA_DIR
from .metadata import merge_payload
from .normalizer import (
    extract_review_id,
    fallback_review_id,
    json_dumps,
    normalize_categories,
    normalize_reviews,
    utc_now,
)


DEFAULT_DB_PATH = str(DATA_DIR / "reviews.db")
DB_DIR = str(DATA_DIR)  # 兼容旧代码
SCHEMA_VERSION = 3


class ReviewStore:
    """本地缓存和可靠 outbox；不再作为最终业务数据源。"""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA busy_timeout = 30000")
        self._migrate()

    def _table_exists(self, name: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        return bool(row)

    def _table_columns(self, name: str) -> set:
        return {row["name"] for row in self.conn.execute(f"PRAGMA table_info({name})")}

    def _primary_key_columns(self, name: str) -> List[str]:
        rows = self.conn.execute(f"PRAGMA table_info({name})").fetchall()
        return [row["name"] for row in sorted(rows, key=lambda item: item["pk"]) if row["pk"]]

    def _create_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS products (
                asin TEXT NOT NULL,
                marketplace TEXT NOT NULL,
                parent_asin TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                added_at TEXT NOT NULL,
                last_scraped_at TEXT NOT NULL,
                PRIMARY KEY (asin, marketplace)
            );

            CREATE TABLE IF NOT EXISTS reviews (
                marketplace TEXT NOT NULL,
                review_id TEXT NOT NULL,
                rating REAL,
                title TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                reviewer_name TEXT NOT NULL DEFAULT '',
                review_date TEXT,
                review_date_raw TEXT NOT NULL DEFAULT '',
                verified_purchase INTEGER NOT NULL DEFAULT 0,
                helpful_votes INTEGER NOT NULL DEFAULT 0,
                review_url TEXT NOT NULL DEFAULT '',
                image_urls TEXT NOT NULL DEFAULT '[]',
                language TEXT,
                raw_json TEXT NOT NULL DEFAULT '{}',
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                PRIMARY KEY (marketplace, review_id)
            );

            CREATE TABLE IF NOT EXISTS product_reviews (
                marketplace TEXT NOT NULL,
                asin TEXT NOT NULL,
                review_id TEXT NOT NULL,
                star_filter TEXT NOT NULL DEFAULT '',
                page_number INTEGER,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                PRIMARY KEY (marketplace, asin, review_id),
                FOREIGN KEY (asin, marketplace)
                    REFERENCES products(asin, marketplace) ON DELETE CASCADE,
                FOREIGN KEY (marketplace, review_id)
                    REFERENCES reviews(marketplace, review_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_product_reviews_asin
                ON product_reviews(marketplace, asin);
            CREATE INDEX IF NOT EXISTS idx_reviews_rating
                ON reviews(marketplace, rating);
            CREATE INDEX IF NOT EXISTS idx_reviews_date
                ON reviews(marketplace, review_date DESC);

            CREATE TABLE IF NOT EXISTS categories (
                marketplace TEXT NOT NULL,
                category_id TEXT NOT NULL,
                category_name TEXT NOT NULL DEFAULT '',
                category_path TEXT NOT NULL DEFAULT '[]',
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                PRIMARY KEY (marketplace, category_id)
            );

            CREATE TABLE IF NOT EXISTS product_categories (
                marketplace TEXT NOT NULL,
                asin TEXT NOT NULL,
                category_id TEXT NOT NULL,
                is_primary INTEGER NOT NULL DEFAULT 0,
                is_current INTEGER NOT NULL DEFAULT 1,
                source TEXT NOT NULL DEFAULT 'breadcrumb',
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                PRIMARY KEY (marketplace, asin, category_id),
                FOREIGN KEY (asin, marketplace)
                    REFERENCES products(asin, marketplace) ON DELETE CASCADE,
                FOREIGN KEY (marketplace, category_id)
                    REFERENCES categories(marketplace, category_id) ON DELETE CASCADE
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_product_categories_primary
                ON product_categories(marketplace, asin)
                WHERE is_primary = 1 AND is_current = 1;

            CREATE TABLE IF NOT EXISTS collection_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asin TEXT NOT NULL,
                marketplace TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL,
                new_reviews INTEGER NOT NULL DEFAULT 0,
                duplicate_reviews INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                error TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                idempotency_key TEXT NOT NULL UNIQUE,
                entity_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'syncing', 'synced', 'failed')),
                retry_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT '',
                next_retry_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                synced_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_outbox_pending
                ON outbox(status, next_retry_at, id);

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )

    def _migrate(self) -> None:
        legacy_products = False
        if self._table_exists("products"):
            columns = self._table_columns("products")
            primary_key = self._primary_key_columns("products")
            compatible = (
                {"asin", "marketplace", "parent_asin", "title", "note"} <= columns
                and primary_key == ["asin", "marketplace"]
            )
            if not compatible:
                if self._table_exists("products_legacy_v1"):
                    raise RuntimeError(
                        "检测到两个不兼容的旧 products 表，请先备份数据库并人工核对"
                    )
                self.conn.execute("ALTER TABLE products RENAME TO products_legacy_v1")
                legacy_products = True

        legacy_reviews = self._table_exists("reviews") and not self._table_exists("product_reviews")
        if legacy_reviews and not self._table_exists("reviews_legacy_v1"):
            # 保留完整旧表，出现异常时仍可人工回退。
            self.conn.execute("ALTER TABLE reviews RENAME TO reviews_legacy_v1")

        self._create_schema()
        if legacy_products:
            self._import_legacy_products()
        if legacy_reviews and self._table_exists("reviews_legacy_v1"):
            self._import_legacy_reviews()

        self.conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self.conn.commit()

    def _import_legacy_products(self) -> None:
        if self.get_setting("legacy_products_v1_imported", ""):
            return
        for row in self.conn.execute("SELECT * FROM products_legacy_v1").fetchall():
            item = dict(row)
            asin = item.get("asin") or ""
            marketplace = item.get("marketplace") or "amazon.com"
            if asin:
                self.upsert_product(
                    asin,
                    marketplace,
                    title=item.get("title") or "",
                    parent_asin=item.get("parent_asin") or "",
                    note=item.get("note") or "",
                )
        self.set_setting("legacy_products_v1_imported", utc_now())

    def _import_legacy_reviews(self) -> None:
        if self.get_setting("legacy_v1_imported", ""):
            return
        rows = self.conn.execute("SELECT * FROM reviews_legacy_v1").fetchall()
        by_product: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for row in rows:
            raw = dict(row)
            raw.update(
                {
                    "date": raw.get("review_date", ""),
                    "review_image_urls": raw.get("image_urls", ""),
                    "review_image_count": raw.get("image_count", 0),
                }
            )
            key = (raw.get("asin", ""), raw.get("marketplace", ""))
            by_product.setdefault(key, []).append(raw)
        for (asin, marketplace), items in by_product.items():
            self.upsert_product(asin, marketplace)
            self.add_reviews(asin, marketplace, items)
        self.set_setting("legacy_v1_imported", utc_now())

    def close(self) -> None:
        self.conn.close()

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: Any) -> None:
        self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, "" if value is None else str(value)),
        )
        self.conn.commit()

    def delete_setting(self, key: str) -> None:
        self.conn.execute("DELETE FROM settings WHERE key = ?", (key,))
        self.conn.commit()

    def backup_to(self, dest_path: str) -> int:
        os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)
        dest_conn = sqlite3.connect(dest_path)
        try:
            self.conn.backup(dest_conn)
        finally:
            dest_conn.close()
        return os.path.getsize(dest_path)

    def integrity_check(self) -> str:
        return self.conn.execute("PRAGMA integrity_check").fetchone()[0]

    def upsert_product(
        self,
        asin: str,
        marketplace: str,
        title: str = "",
        parent_asin: str = "",
        note: str = "",
        categories: Optional[Iterable[Dict[str, Any]]] = None,
    ) -> None:
        now = utc_now()
        self.conn.execute(
            """
            INSERT INTO products
                (asin, marketplace, parent_asin, title, note, added_at, last_scraped_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(asin, marketplace) DO UPDATE SET
                title = CASE WHEN excluded.title != '' THEN excluded.title ELSE products.title END,
                parent_asin = CASE WHEN excluded.parent_asin != '' THEN excluded.parent_asin ELSE products.parent_asin END,
                note = CASE WHEN excluded.note != '' THEN excluded.note ELSE products.note END,
                last_scraped_at = excluded.last_scraped_at
            """,
            (asin, marketplace, parent_asin, title, note, now, now),
        )
        normalized_categories = normalize_categories(marketplace, categories or [])
        if normalized_categories:
            self.conn.execute(
                """UPDATE product_categories
                   SET is_primary=0, is_current=0
                   WHERE marketplace=? AND asin=?""",
                (marketplace, asin),
            )
            for category in normalized_categories:
                self.conn.execute(
                    """INSERT INTO categories (
                           marketplace, category_id, category_name, category_path,
                           first_seen_at, last_seen_at
                       ) VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(marketplace, category_id) DO UPDATE SET
                           category_name=CASE WHEN excluded.category_name!='' THEN excluded.category_name ELSE categories.category_name END,
                           category_path=CASE WHEN excluded.category_path!='[]' THEN excluded.category_path ELSE categories.category_path END,
                           last_seen_at=excluded.last_seen_at""",
                    (
                        marketplace, category["category_id"], category["category_name"],
                        json_dumps(category["category_path"]), now, now,
                    ),
                )
                self.conn.execute(
                    """INSERT INTO product_categories (
                           marketplace, asin, category_id, is_primary, is_current,
                           source, first_seen_at, last_seen_at
                       ) VALUES (?, ?, ?, ?, 1, ?, ?, ?)
                       ON CONFLICT(marketplace, asin, category_id) DO UPDATE SET
                           is_primary=excluded.is_primary,
                           is_current=1,
                           source=excluded.source,
                           last_seen_at=excluded.last_seen_at""",
                    (
                        marketplace, asin, category["category_id"],
                        int(category["is_primary"]), category["source"], now, now,
                    ),
                )
        self.conn.commit()

    def known_review_ids(self, asin: Optional[str] = None, marketplace: Optional[str] = None):
        clauses: List[str] = []
        params: List[Any] = []
        if asin:
            clauses.append("pr.asin = ?")
            params.append(asin)
        if marketplace:
            clauses.append("pr.marketplace = ?")
            params.append(marketplace)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.conn.execute(
            f"SELECT pr.review_id FROM product_reviews pr {where}", params
        ).fetchall()
        return {row["review_id"] for row in rows}

    def add_reviews(
        self,
        asin: str,
        marketplace: str,
        reviews: Iterable[Dict[str, Any]],
    ) -> Tuple[int, int]:
        normalized = normalize_reviews(asin, marketplace, reviews)
        if not normalized:
            return 0, 0

        self.upsert_product(asin, marketplace)
        new_count = 0
        duplicate_count = 0
        for item in normalized:
            exists = self.conn.execute(
                "SELECT raw_json FROM reviews WHERE marketplace=? AND review_id=?",
                (item["marketplace"], item["review_id"]),
            ).fetchone()
            if exists:
                item["raw_payload"] = merge_payload(exists["raw_json"], item["raw_payload"])
                duplicate_count += 1
            else:
                new_count += 1

            self.conn.execute(
                """
                INSERT INTO reviews (
                    marketplace, review_id, rating, title, content, reviewer_name,
                    review_date, review_date_raw, verified_purchase, helpful_votes,
                    review_url, image_urls, language, raw_json, first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(marketplace, review_id) DO UPDATE SET
                    rating=COALESCE(excluded.rating, reviews.rating),
                    title=CASE WHEN excluded.title!='' THEN excluded.title ELSE reviews.title END,
                    content=CASE WHEN excluded.content!='' THEN excluded.content ELSE reviews.content END,
                    reviewer_name=CASE WHEN excluded.reviewer_name!='' THEN excluded.reviewer_name ELSE reviews.reviewer_name END,
                    review_date=COALESCE(excluded.review_date, reviews.review_date),
                    review_date_raw=CASE WHEN excluded.review_date_raw!='' THEN excluded.review_date_raw ELSE reviews.review_date_raw END,
                    verified_purchase=MAX(reviews.verified_purchase, excluded.verified_purchase),
                    helpful_votes=MAX(reviews.helpful_votes, excluded.helpful_votes),
                    review_url=CASE WHEN excluded.review_url!='' THEN excluded.review_url ELSE reviews.review_url END,
                    image_urls=CASE WHEN excluded.image_urls!='[]' THEN excluded.image_urls ELSE reviews.image_urls END,
                    raw_json=excluded.raw_json,
                    last_seen_at=excluded.last_seen_at
                """,
                (
                    item["marketplace"], item["review_id"], item["rating"], item["title"],
                    item["content"], item["reviewer_name"], item["review_date"],
                    item["review_date_raw"], int(item["verified_purchase"]),
                    item["helpful_votes"], item["review_url"], json_dumps(item["image_urls"]),
                    item["language"], json_dumps(item["raw_payload"]),
                    item["first_seen_at"], item["last_seen_at"],
                ),
            )
            self.conn.execute(
                """
                INSERT INTO product_reviews (
                    marketplace, asin, review_id, star_filter, page_number,
                    first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(marketplace, asin, review_id) DO UPDATE SET
                    star_filter=CASE WHEN excluded.star_filter!='' THEN excluded.star_filter ELSE product_reviews.star_filter END,
                    page_number=COALESCE(excluded.page_number, product_reviews.page_number),
                    last_seen_at=excluded.last_seen_at
                """,
                (
                    item["marketplace"], item["asin"], item["review_id"],
                    item["star_filter"], item["page_number"],
                    item["first_seen_at"], item["last_seen_at"],
                ),
            )
        self.conn.commit()
        return new_count, duplicate_count

    def enqueue_collection(
        self,
        asin: str,
        marketplace: str,
        product_title: str,
        reviews: Iterable[Dict[str, Any]],
        *,
        parent_asin: str = "",
        note: str = "",
        categories: Optional[Iterable[Dict[str, Any]]] = None,
        run: Optional[Dict[str, Any]] = None,
    ) -> Optional[int]:
        normalized = normalize_reviews(asin, marketplace, reviews)
        for item in normalized:
            current = self.conn.execute("SELECT raw_json FROM reviews WHERE marketplace=? AND review_id=?",
                                       (item["marketplace"],item["review_id"])).fetchone()
            if current:
                item["raw_payload"] = merge_payload(item["raw_payload"], current["raw_json"])
        normalized_categories = normalize_categories(marketplace, categories or [])
        payload = {
            "product": {
                "asin": asin,
                "marketplace": marketplace,
                "parent_asin": parent_asin,
                "title": product_title,
                "note": note,
                "categories": normalized_categories,
            },
            "reviews": normalized,
            "run": run or {},
        }
        review_ids = sorted(item["review_id"] for item in normalized)
        basis = json_dumps(
            {
                "marketplace": marketplace,
                "asin": asin,
                "review_ids": review_ids,
                "started_at": (run or {}).get("started_at", ""),
            }
        )
        key = hashlib.sha256(basis.encode("utf-8")).hexdigest()
        now = utc_now()
        self.conn.execute(
            """
            INSERT INTO outbox
                (idempotency_key, entity_type, payload_json, status, created_at, updated_at)
            VALUES (?, 'review_batch', ?, 'pending', ?, ?)
            ON CONFLICT(idempotency_key) DO NOTHING
            """,
            (key, json_dumps(payload), now, now),
        )
        row = self.conn.execute(
            "SELECT id FROM outbox WHERE idempotency_key=?", (key,)
        ).fetchone()
        self.conn.commit()
        return row["id"] if row else None

    def pending_outbox(self, limit: int = 20, *, include_deferred: bool = False, max_id: Optional[int] = None) -> List[Dict[str, Any]]:
        now = utc_now()
        lease_cutoff = datetime.fromtimestamp(
            datetime.now(timezone.utc).timestamp() - 300, timezone.utc
        ).isoformat(timespec="seconds")
        self.conn.execute(
            """UPDATE outbox SET status='pending', updated_at=?
               WHERE status='syncing' AND updated_at <= ?""",
            (now, lease_cutoff),
        )
        retry_clause = "" if include_deferred else "AND (next_retry_at IS NULL OR next_retry_at <= ?)"
        params: List[Any] = []
        if not include_deferred:
            params.append(now)
        if max_id is not None:
            retry_clause += " AND id <= ?"
            params.append(max_id)
        params.append(max(1, int(limit)))
        rows = self.conn.execute(
            f"""
            SELECT * FROM outbox
            WHERE status IN ('pending', 'failed')
              {retry_clause}
            ORDER BY id LIMIT ?
            """,
            params,
        ).fetchall()
        self.conn.commit()
        return [dict(row) for row in rows]

    def mark_outbox_syncing(self, outbox_id: int) -> None:
        self.conn.execute(
            "UPDATE outbox SET status='syncing', updated_at=? WHERE id=?",
            (utc_now(), outbox_id),
        )
        self.conn.commit()

    def mark_outbox_synced(self, outbox_id: int) -> None:
        now = utc_now()
        self.conn.execute(
            "UPDATE outbox SET status='synced', last_error='', synced_at=?, updated_at=? WHERE id=?",
            (now, now, outbox_id),
        )
        self.conn.commit()

    def mark_outbox_failed(self, outbox_id: int, error: str) -> None:
        now = datetime.now(timezone.utc)
        row = self.conn.execute("SELECT retry_count FROM outbox WHERE id=?", (outbox_id,)).fetchone()
        retry_count = (row["retry_count"] if row else 0) + 1
        delay_seconds = min(3600, 60 * (2 ** min(retry_count - 1, 6)))
        next_retry = datetime.fromtimestamp(now.timestamp() + delay_seconds, timezone.utc)
        self.conn.execute(
            """
            UPDATE outbox SET status='failed', retry_count=?, last_error=?,
                next_retry_at=?, updated_at=? WHERE id=?
            """,
            (
                retry_count, str(error)[:2000], next_retry.isoformat(timespec="seconds"),
                now.isoformat(timespec="seconds"), outbox_id,
            ),
        )
        self.conn.commit()

    def outbox_stats(self) -> Dict[str, int]:
        rows = self.conn.execute(
            "SELECT status, COUNT(*) AS c FROM outbox GROUP BY status"
        ).fetchall()
        result = {"pending": 0, "syncing": 0, "synced": 0, "failed": 0}
        result.update({row["status"]: row["c"] for row in rows})
        return result

    def log_run(
        self,
        asin: str,
        marketplace: str,
        new_count: int,
        dup_count: int,
        status: str,
        error: str = "",
        started_at: str = "",
    ) -> None:
        now = utc_now()
        self.conn.execute(
            """
            INSERT INTO collection_runs
                (asin, marketplace, started_at, finished_at,
                 new_reviews, duplicate_reviews, status, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (asin, marketplace, started_at or now, now, new_count, dup_count, status, error),
        )
        self.conn.commit()

    def product_stats(self) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT p.asin, p.marketplace, p.title, p.last_scraped_at,
                   COUNT(pr.review_id) AS review_count,
                   AVG(r.rating) AS avg_rating,
                   (
                       SELECT c.category_id
                       FROM product_categories pc
                       JOIN categories c
                         ON c.marketplace=pc.marketplace AND c.category_id=pc.category_id
                       WHERE pc.marketplace=p.marketplace AND pc.asin=p.asin
                         AND pc.is_current=1
                       ORDER BY pc.is_primary DESC, pc.first_seen_at
                       LIMIT 1
                   ) AS category_id,
                   (
                       SELECT c.category_name
                       FROM product_categories pc
                       JOIN categories c
                         ON c.marketplace=pc.marketplace AND c.category_id=pc.category_id
                       WHERE pc.marketplace=p.marketplace AND pc.asin=p.asin
                         AND pc.is_current=1
                       ORDER BY pc.is_primary DESC, pc.first_seen_at
                       LIMIT 1
                   ) AS category_name
            FROM products p
            LEFT JOIN product_reviews pr
              ON pr.asin=p.asin AND pr.marketplace=p.marketplace
            LEFT JOIN reviews r
              ON r.marketplace=pr.marketplace AND r.review_id=pr.review_id
            GROUP BY p.asin, p.marketplace
            ORDER BY p.added_at
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def query_reviews(
        self,
        *,
        asin: Optional[str] = None,
        rating: Optional[int] = None,
        keyword: str = "",
        limit: int = 500,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        clauses: List[str] = []
        params: List[Any] = []
        if asin:
            clauses.append("pr.asin=?")
            params.append(asin)
        if rating is not None:
            clauses.append("CAST(ROUND(r.rating) AS INTEGER)=?")
            params.append(int(rating))
        if keyword:
            clauses.append("(r.title LIKE ? OR r.content LIKE ?)")
            params.extend([f"%{keyword}%", f"%{keyword}%"])
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.conn.execute(
            f"""
            SELECT pr.asin, r.marketplace, r.raw_json, r.review_id, r.rating, pr.star_filter,
                   r.review_date, r.review_date_raw, r.reviewer_name,
                   r.title, r.content, r.verified_purchase,
                   r.helpful_votes, r.review_url, r.image_urls,
                   r.first_seen_at, r.last_seen_at
            FROM product_reviews pr
            JOIN reviews r
              ON r.marketplace=pr.marketplace AND r.review_id=pr.review_id
            {where}
            ORDER BY COALESCE(r.review_date, r.first_seen_at) DESC
            LIMIT ? OFFSET ?
            """,
            params + [max(1, int(limit)), max(0, int(offset))],
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["verified_purchase"] = bool(item["verified_purchase"])
            try:
                item["image_urls"] = json.loads(item["image_urls"] or "[]")
            except json.JSONDecodeError:
                item["image_urls"] = []
            result.append(item)
        return result

    def recent_runs(self, limit: int = 10) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT asin, marketplace, started_at, finished_at,
                   new_reviews, duplicate_reviews, status, error
            FROM collection_runs ORDER BY id DESC LIMIT ?
            """,
            (max(1, int(limit)),),
        ).fetchall()
        return [dict(row) for row in rows]

    def total_reviews(self) -> int:
        return self.conn.execute("SELECT COUNT(*) AS c FROM reviews").fetchone()["c"]


__all__ = [
    "ReviewStore", "DEFAULT_DB_PATH", "DB_DIR",
    "extract_review_id", "fallback_review_id",
]
