from tests import support

import os
import tempfile
import unittest

from core.reviews.repository import ReviewRepository
from core.reviews.store import ReviewStore


class FakeCloud:
    def __init__(self):
        self.calls = []

    def ingest_batch(self, payload, key):
        self.calls.append((payload, key))
        return {"reviews": len(payload.get("reviews", []))}


class RepositoryTests(unittest.TestCase):
    def test_syncs_outbox_and_marks_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ReviewStore(os.path.join(folder, "r.db"))
            try:
                store.enqueue_collection(
                    "B012345678", "amazon.com", "Title",
                    [{"review_id": "R123456789", "content": "Hello"}],
                )
                repository = ReviewRepository(store)
                repository.cloud = FakeCloud()
                result = repository.sync_pending()
                self.assertEqual(result["synced"], 1)
                self.assertEqual(store.outbox_stats()["synced"], 1)
                self.assertEqual(len(repository.cloud.calls), 1)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
