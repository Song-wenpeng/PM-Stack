from tests import support

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from openpyxl import load_workbook
from core.reviews.store import ReviewStore
from core.reviews.repository import ReviewRepository
from core.reviews.metadata import KEY,content_hash
from core.reviews.detail_export import export_review_details
from core.secure_storage import unprotect_secret

class RoundOneTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=ReviewStore(str(Path(self.temp.name)/"r.db"))
    def tearDown(self):
        self.store.close();self.temp.cleanup()
    def row(self):
        a={"status":"success","content_hash":content_hash("hello<br>world"),"created_at":"2026-09-15",
           "category":"power strip","model":"test","template_hash":"v1",
           "labels":{"positive":["sturdy"],"translation":"=HYPERLINK(1)"},"field_labels":{"positive":"优点","translation":"翻译"}}
        return {"marketplace":"amazon.com","asin":"B0DDG2KQQ9","review_id":"R1","content":"hello<br>world","rating":5,"title":"=1+1",
                "review_url":"https://www.amazon.com/gp/customer-reviews/R1","raw_payload":{KEY:{"analyses":{"a":a}}}}
    def test_single_sheet_exports_ai_safe_text_and_bounded_layout(self):
        row=self.row();path=Path(self.temp.name)/"details.xlsx"
        export_review_details([row],str(path))
        w=load_workbook(path);s=w.active
        self.assertEqual(w.sheetnames,["评论明细"])
        headers=[c.value for c in s[1]]
        values={h:s.cell(2,i+1) for i,h in enumerate(headers)}
        self.assertEqual(values["AI · 优点"].value,"sturdy")
        self.assertEqual(values["AI · 翻译"].data_type,"s")
        self.assertEqual(values["标题"].data_type,"s")
        self.assertEqual(values["内容"].value,"hello\nworld")
        self.assertEqual(values["评论链接"].hyperlink.target,row["review_url"])
        self.assertEqual(s.row_dimensions[2].height,72)
        self.assertEqual(s.freeze_panes,"A2");w.close()
    def test_empty_analysis_differs_from_unanalysed(self):
        row=self.row()
        row["raw_payload"][KEY]["analyses"]["a"]["labels"]={"positive":[]}
        other={**row,"review_id":"R2","raw_payload":{}}
        path=Path(self.temp.name)/"details.xlsx";export_review_details([row,other],str(path))
        w=load_workbook(path);s=w.active
        column=[c.value for c in s[1]].index("分析状态")+1
        self.assertNotEqual(s.cell(2,column).value,s.cell(3,column).value);w.close()
    def test_export_snapshot_includes_local_labels_and_new_rows(self):
        row=self.row();self.store.add_reviews(row["asin"],row["marketplace"],[row])
        remote={**row,"raw_payload":{}}
        r=ReviewRepository(self.store)
        rows,source=r.export_snapshot()
        self.assertEqual(len(rows),1)
        self.assertTrue(json.loads(rows[0]["raw_json"])[KEY]["analyses"])
    def test_export_snapshot_cloud_failure_restarts_local(self):
        row=self.row();self.store.add_reviews(row["asin"],row["marketplace"],[row])
        r=ReviewRepository(self.store)
        rows,source=r.export_snapshot()
        self.assertEqual(len(rows),1);self.assertIn("本地",source)
