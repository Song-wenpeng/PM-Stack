from tests import support

import json
import os
import sqlite3
import tempfile
import unittest

from core.reviews.store import ReviewStore


class ReviewStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, "reviews.db")

    def tearDown(self):
        self.temp.cleanup()

    def test_canonical_review_with_two_product_relations(self):
        store = ReviewStore(self.path)
        try:
            review = {
                "review_id": "R123456789", "rating": 5,
                "reviewer_name": "Alice", "content": "Useful",
            }
            self.assertEqual(store.add_reviews("B012345678", "amazon.com", [review]), (1, 0))
            self.assertEqual(store.add_reviews("B087654321", "amazon.com", [review]), (0, 1))
            self.assertEqual(store.total_reviews(), 1)
            relations = store.conn.execute("select count(*) from product_reviews").fetchone()[0]
            self.assertEqual(relations, 2)
        finally:
            store.close()

    def test_outbox_contains_normalized_payload_and_is_idempotent(self):
        store = ReviewStore(self.path)
        try:
            review = {"review_id": "R123456789", "rating": "5 out of 5"}
            run = {"started_at": "2026-08-29T00:00:00+00:00", "status": "ok"}
            first = store.enqueue_collection("B012345678", "amazon.com", "Title", [review], run=run)
            second = store.enqueue_collection("B012345678", "amazon.com", "Title", [review], run=run)
            self.assertEqual(first, second)
            rows = store.pending_outbox()
            self.assertEqual(len(rows), 1)
            payload = json.loads(rows[0]["payload_json"])
            self.assertEqual(payload["reviews"][0]["rating"], 5.0)
            self.assertEqual(payload["product"]["asin"], "B012345678")
        finally:
            store.close()

    def test_product_category_is_cached_and_added_to_outbox(self):
        store = ReviewStore(self.path)
        categories = [{
            "category_id": "10967801",
            "category_name": "Power Strips",
            "category_path": [
                {"id": "172282", "name": "Electronics"},
                {"id": "10967801", "name": "Power Strips"},
            ],
            "is_primary": True,
            "source": "breadcrumb",
        }]
        try:
            store.upsert_product(
                "B012345678", "amazon.com", title="Title", categories=categories,
            )
            stats = store.product_stats()
            self.assertEqual(stats[0]["category_id"], "10967801")
            self.assertEqual(stats[0]["category_name"], "Power Strips")

            store.enqueue_collection(
                "B012345678", "amazon.com", "Title", [], categories=categories,
                run={"started_at": "2026-09-10T00:00:00+00:00", "status": "ok"},
            )
            payload = json.loads(store.pending_outbox()[0]["payload_json"])
            self.assertEqual(payload["product"]["categories"][0]["category_id"], "10967801")
        finally:
            store.close()

    def test_imports_legacy_reviews_without_deleting_legacy_table(self):
        conn = sqlite3.connect(self.path)
        conn.execute(
            """create table reviews (
                review_id text, asin text, marketplace text, rating real,
                title text, content text, reviewer_name text, review_date text,
                verified_purchase integer, helpful_votes integer,
                star_filter text, review_url text, image_urls text
            )"""
        )
        conn.execute(
            "insert into reviews values (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("R123456789", "B012345678", "amazon.com", 5, "T", "C", "A",
             "August 20, 2026", 1, 2, "5 star", "", ""),
        )
        conn.commit()
        conn.close()

        store = ReviewStore(self.path)
        try:
            self.assertEqual(store.total_reviews(), 1)
            self.assertTrue(store._table_exists("reviews_legacy_v1"))
            self.assertEqual(store.integrity_check(), "ok")
        finally:
            store.close()

    def test_rebuilds_legacy_product_primary_key(self):
        conn = sqlite3.connect(self.path)
        conn.execute(
            "create table products (asin text primary key, marketplace text, title text)"
        )
        conn.execute(
            "insert into products values ('B012345678', 'amazon.com', 'Legacy title')"
        )
        conn.execute(
            """create table reviews (
                review_id text, asin text, marketplace text, rating real,
                title text, content text, reviewer_name text, review_date text,
                verified_purchase integer, helpful_votes integer,
                star_filter text, review_url text, image_urls text
            )"""
        )
        conn.commit()
        conn.close()

        store = ReviewStore(self.path)
        try:
            self.assertTrue(store._table_exists("products_legacy_v1"))
            products = store.product_stats()
            self.assertEqual(products[0]["title"], "Legacy title")
            self.assertEqual(store._primary_key_columns("products"), ["asin", "marketplace"])
        finally:
            store.close()

    def test_recovers_expired_sync_lease(self):
        store = ReviewStore(self.path)
        try:
            outbox_id = store.enqueue_collection("B012345678", "amazon.com", "", [])
            store.mark_outbox_syncing(outbox_id)
            store.conn.execute(
                "update outbox set updated_at='2000-01-01T00:00:00+00:00' where id=?",
                (outbox_id,),
            )
            store.conn.commit()
            rows = store.pending_outbox()
            self.assertEqual([row["id"] for row in rows], [outbox_id])
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
