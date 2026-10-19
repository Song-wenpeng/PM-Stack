from tests import support
import tempfile
import unittest
from pathlib import Path
from core.reviews.repository import ReviewRepository
from core.reviews.store import ReviewStore

class RepositoryTests(unittest.TestCase):
    def test_local_queries_ignore_legacy_cloud_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            store=ReviewStore(str(Path(folder)/"r.db"))
            try:
                store.set_setting("supabase_url","https://invalid.example")
                store.set_setting("supabase_session","legacy")
                store.add_reviews("B012345678","amazon.com",[{"review_id":"R1","content":"local"}])
                repo=ReviewRepository(store)
                self.assertEqual(repo.total_reviews(),(1,"本地数据库"))
                self.assertEqual(repo.query_reviews()[0][0]["content"],"local")
                self.assertFalse(hasattr(repo,"cloud"))
                self.assertFalse(hasattr(repo,"sync_pending"))
            finally:store.close()
