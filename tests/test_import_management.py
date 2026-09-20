from tests import support

import json
from pathlib import Path
from unittest.mock import patch
from tests import test_excel_import as fixture
from core.reviews.excel_import import read_import,import_reviews,extract_labels
from core.reviews.import_management import batches,change_batch
from core.reviews.metadata import latest_analysis,KEY

class ImportManagementTests(fixture.ExcelImportTests):
    def test_file_mismatch_is_blocked(self):
        path=self.path.with_name("B0FB2SFD5X-US-Reviews.xlsx")
        path.write_bytes(self.path.read_bytes())
        with self.assertRaisesRegex(ValueError,"B0FB2SFD5X"):read_import(path,fixture.ASIN,"amazon.com")
        self.assertEqual(self.store.total_reviews(),0)

    def test_move_dedupes_target_keeps_labels_and_prunes_queue(self):
        data=self.data();import_reviews(self.store,data)
        extract_labels(self.store,data,"power strip",fixture.CONFIG,{},gateway=lambda _: '{"positive":["good"],"negative":[]}')
        batch=batches(self.store)[0]
        result=change_batch(self.store,batch,"B0FB2SFD5X")
        self.assertEqual(result["removed"],1)
        self.assertTrue(Path(result["backup"]).exists())
        self.assertEqual(self.store.query_reviews(asin=fixture.ASIN),[])
        rows=self.store.query_reviews(asin="B0FB2SFD5X")
        self.assertEqual(len(rows),1);self.assertIsNotNone(latest_analysis(rows[0]))
        for row in self.store.pending_outbox(100):
            self.assertNotEqual(json.loads(row["payload_json"])["product"]["asin"],fixture.ASIN)
        self.assertEqual(batches(self.store)[0]["asin"],"B0FB2SFD5X")
        self.assertEqual(self.store.conn.execute("SELECT COUNT(*) FROM import_corrections").fetchone()[0],1)

    def test_remove_one_source_retains_other_source(self):
        data=self.data();import_reviews(self.store,data)
        other=self.data()
        for v in other["rows"][0]["raw_payload"][KEY]["imports"].values():
            v["file_sha256"]="different";v["file"]="other.xlsx"
        sources=other["rows"][0]["raw_payload"][KEY]["imports"]
        other["rows"][0]["raw_payload"][KEY]["imports"]={k+"other":v for k,v in sources.items()}
        import_reviews(self.store,other)
        first=next(b for b in batches(self.store) if b["sha256"]==data["sha256"])
        result=change_batch(self.store,first)
        self.assertEqual((result["removed"],result["retained"]),(0,1))
        self.assertEqual(len(self.store.query_reviews()),1)

    def test_remove_preserves_preexisting_browser_link(self):
        data=self.data()
        self.store.add_reviews(fixture.ASIN,"amazon.com",[{**data["rows"][0],"raw_payload":{"browser":True}}])
        import_reviews(self.store,data)
        result=change_batch(self.store,batches(self.store)[0])
        self.assertEqual(result["retained"],1)
        self.assertEqual(len(self.store.query_reviews()),1)

    def test_synced_and_cloud_configured_are_blocked(self):
        data=self.data();import_reviews(self.store,data)
        batch=batches(self.store)[0]
        with patch("core.reviews.import_management.SupabaseStore.is_configured",return_value=True):
            with self.assertRaises(ValueError):change_batch(self.store,batch)
        self.store.conn.execute("UPDATE outbox SET status='synced'");self.store.conn.commit()
        with self.assertRaises(ValueError):change_batch(self.store,batch)
        self.assertEqual(len(self.store.query_reviews()),1)

    def test_remove_only_association_keeps_recoverable_raw(self):
        data=self.data();import_reviews(self.store,data)
        result=change_batch(self.store,batches(self.store)[0])
        self.assertEqual(result["removed"],1)
        self.assertEqual(self.store.query_reviews(),[])
        self.assertEqual(self.store.total_reviews(),1)
        self.assertEqual(self.store.outbox_stats()["pending"],0)

    def test_failure_rolls_back_links_metadata_and_queue(self):
        import uuid
        data=self.data();import_reviews(self.store,data)
        batch=batches(self.store)[0]
        before=self.store.query_reviews()[0]["raw_json"]
        queued=[dict(r) for r in self.store.conn.execute("SELECT * FROM outbox")]
        with patch("core.reviews.import_management.uuid.uuid4",side_effect=[uuid.uuid4(),RuntimeError("simulated failure")]):
            with self.assertRaises(RuntimeError):change_batch(self.store,batch)
        self.assertEqual(self.store.query_reviews()[0]["raw_json"],before)
        self.assertEqual([dict(r) for r in self.store.conn.execute("SELECT * FROM outbox")],queued)
        self.assertEqual(len(batches(self.store)),1)

    def test_sheet_mismatch_is_blocked(self):
        from openpyxl import load_workbook
        w=load_workbook(self.path)
        w.active.title="B0FB2SFD5X-Review(1)"
        w.save(self.path);w.close()
        with self.assertRaisesRegex(ValueError,"B0FB2SFD5X"):self.data()
