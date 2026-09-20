from tests import support

import unittest

from core.reviews.normalizer import (
    extract_asin,
    normalize_categories,
    normalize_review,
    normalize_reviews,
)


class NormalizerTests(unittest.TestCase):
    def test_extracts_asin_from_url(self):
        self.assertEqual(
            extract_asin("https://www.amazon.com/dp/B0CBJ6QHKT?th=1"),
            "B0CBJ6QHKT",
        )

    def test_official_id_and_localized_fields(self):
        row = normalize_review(
            "B0CBJ6QHKT",
            "https://www.amazon.de/",
            {
                "element_id": "customer_review-R123456789",
                "rating": "4,0 von 5 Sternen",
                "date": "Rezension aus Deutschland vom 3. August 2026",
                "verified_purchase": "true",
                "helpful_votes": "2 Personen fanden diese Informationen hilfreich",
            },
        )
        self.assertEqual(row["review_id"], "R123456789")
        self.assertEqual(row["marketplace"], "amazon.de")
        self.assertEqual(row["rating"], 4.0)
        self.assertEqual(row["review_date"], "2026-08-03")
        self.assertEqual(row["helpful_votes"], 2)
        self.assertTrue(row["verified_purchase"])

    def test_fallback_id_is_stable_across_variants(self):
        raw = {
            "reviewer_name": "Alice", "date": "August 20, 2026",
            "rating": 5, "title": "Good", "content": "Same review",
        }
        first = normalize_review("B012345678", "amazon.com", raw)
        second = normalize_review("B087654321", "amazon.com", raw)
        self.assertEqual(first["review_id"], second["review_id"])

    def test_batch_removes_same_product_duplicates(self):
        rows = normalize_reviews(
            "B012345678", "amazon.com",
            [{"review_id": "R123456789"}, {"review_id": "R123456789"}],
        )
        self.assertEqual(len(rows), 1)

    def test_normalization_is_idempotent(self):
        raw = {
            "review_id": "R123456789",
            "date": "Reviewed in the United States on August 20, 2026",
            "content": "Stable",
        }
        first = normalize_review("B012345678", "amazon.com", raw)
        second = normalize_review("B012345678", "amazon.com", first)
        self.assertEqual(second["review_id"], first["review_id"])
        self.assertEqual(second["review_date_raw"], first["review_date_raw"])
        self.assertEqual(second["raw_payload"], raw)

    def test_category_normalization_prefers_node_id_and_keeps_path(self):
        rows = normalize_categories(
            "https://www.amazon.com/",
            [{
                "category_id": "10967801",
                "category_name": "Power Strips",
                "category_path": [
                    {"id": "172282", "name": "Electronics"},
                    {"id": "10967801", "name": "Power Strips"},
                ],
                "source": "breadcrumb",
            }],
        )
        self.assertEqual(rows[0]["marketplace"], "amazon.com")
        self.assertEqual(rows[0]["category_id"], "10967801")
        self.assertEqual(rows[0]["category_path"][-1]["name"], "Power Strips")
        self.assertTrue(rows[0]["is_primary"])

    def test_category_without_node_id_gets_stable_fallback(self):
        raw = [{"category_name": "Power Strips", "category_path": ["Electronics", "Power Strips"]}]
        first = normalize_categories("amazon.com", raw)
        second = normalize_categories("amazon.com", raw)
        self.assertTrue(first[0]["category_id"].startswith("h_"))
        self.assertEqual(first[0]["category_id"], second[0]["category_id"])


if __name__ == "__main__":
    unittest.main()
