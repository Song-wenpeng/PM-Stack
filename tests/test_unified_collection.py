from tests import support

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from PyQt6.QtWidgets import QApplication
from core.reviews.panel import ReviewCollectionPanel
from core.reviews.extension_bridge import ExtensionBridge

CLIENT = "unified-test-client-123456"

class UnifiedCollectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = support.qt_app()

    def setUp(self):
        self.addCleanup(support.cleanup_qt_widgets)
        self.temp = tempfile.TemporaryDirectory()
        with patch.object(ReviewCollectionPanel, "_load_cloud_settings"):
            self.panel = ReviewCollectionPanel(Mock(), Mock())
        self.panel.refresh_products = Mock()
        self.bridge = ExtensionBridge(str(Path(self.temp.name) / "test.db"), port=0)
        self.bridge.handle("/poll", {"client":CLIENT})
        self.panel.extension_panel.bridge = self.bridge

    def tearDown(self):
        self.panel._extension_timer.stop()
        self.panel.extension_panel.timer.stop()
        self.panel.extension_panel.disconnect()
        self.panel.close()
        self.panel.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def start(self):
        self.panel.collect_asins.setPlainText("B0DDG2KQQ9")
        self.panel._start_collection(False)
        return self.bridge.snapshot()["job"]

    def test_one_entry_and_capability_specific_controls(self):
        p = self.panel
        self.assertEqual([p.inner_tabs.tabText(i) for i in range(p.inner_tabs.count())],
                         ["评论采集", "评论库", "云端与备份"])
        self.assertEqual(p.collect_engine.currentData(), "extension")
        self.assertTrue(p.advanced_options.isHidden())
        self.assertTrue(p.collect_update_btn.isHidden())
        p.collect_asins.setPlainText("B0DDG2KQQ9")
        p.collect_engine.setCurrentIndex(1)
        p.collect_pages.setValue(7)
        self.assertTrue(p.extension_panel.isHidden())
        self.assertFalse(p.advanced_options.isHidden())
        p.collect_engine.setCurrentIndex(0)
        p.collect_engine.setCurrentIndex(1)
        self.assertEqual(p.collect_pages.value(), 7)
        self.assertEqual(p.collect_asins.toPlainText(), "B0DDG2KQQ9")

    def test_extension_completion_updates_shared_controls_and_library(self):
        p = self.panel
        job = self.start()
        self.assertIsNotNone(job)
        self.assertFalse(p.collect_engine.isEnabled())
        self.assertTrue(p.collect_stop_btn.isEnabled())
        self.bridge.handle("/poll", {"client":CLIENT})
        self.bridge.handle("/result", {"client":CLIENT,"id":job["id"],"status":"ready",
            "url":job["url"],"title":"Test","reviews":[{"review_id":"RTEST0001",
            "rating":5,"content":"Synthetic unified UI test"}]})
        p._poll_extension_job()
        self.assertFalse(p._collection_running)
        self.assertTrue(p.collect_engine.isEnabled())
        self.assertFalse(p.collect_stop_btn.isEnabled())
        p.refresh_products.assert_called_once()
        p._poll_extension_job()
        p.refresh_products.assert_called_once()

    def test_shared_stop_and_disconnect_release_busy_state(self):
        self.start()
        self.panel._stop_collection()
        self.assertEqual(self.bridge.snapshot()["job"]["status"], "cancelled")
        self.assertFalse(self.panel._collection_running)
        self.start()
        self.panel.extension_panel.disconnect()
        self.panel._poll_extension_job()
        self.assertFalse(self.panel._collection_running)
        self.assertTrue(self.panel.collect_new_btn.isEnabled())

    def test_invalid_extension_input_does_not_start(self):
        self.panel.collect_asins.setPlainText("B0DDG2KQQ9 B012345678")
        self.panel._start_collection(False)
        self.assertIsNone(self.bridge.snapshot()["job"])
        self.panel.collect_asins.setPlainText("https://www.amazon.de/dp/B0DDG2KQQ9")
        self.panel._start_collection(False)
        self.assertIsNone(self.bridge.snapshot()["job"])
        self.assertFalse(self.panel._collection_running)

    def test_dedicated_mode_dispatches_existing_worker(self):
        self.panel.collect_engine.setCurrentIndex(1)
        self.panel.collect_asins.setPlainText("B0DDG2KQQ9")
        self.panel._start_task = Mock(return_value=True)
        self.panel._start_collection(True)
        self.panel._start_task.assert_called_once()
        self.assertEqual(self.panel._start_task.call_args.args[0], "collect")
        self.assertIsNone(self.bridge.snapshot()["job"])


    def test_worker_dispatch_rejection_does_not_leave_controls_locked(self):
        self.panel.collect_engine.setCurrentIndex(1)
        self.panel.collect_asins.setPlainText("B0DDG2KQQ9")
        self.panel._start_task = Mock(return_value=False)
        self.panel._start_collection(False)
        self.assertFalse(self.panel._collection_running)
        self.assertTrue(self.panel.collect_engine.isEnabled())

    def test_excel_controls_and_dispatch_share_collection_entry(self):
        p=self.panel
        p.collect_engine.setCurrentIndex(p.collect_engine.findData("excel"))
        self.assertFalse(p.excel_options.isHidden())
        self.assertTrue(p.extension_panel.isHidden())
        self.assertTrue(p.advanced_options.isHidden())
        p.excel_options.path.setText("B0DDG2KQQ9-US-Reviews.xlsx")
        self.assertEqual(p.collect_asins.toPlainText(),"B0DDG2KQQ9")
        p.excel_options.ai.setChecked(False)
        p._start_task=Mock(return_value=False)
        p._start_collection(False)
        p._start_task.assert_called_once()
        self.assertFalse(p._collection_running)
        self.assertTrue(p.excel_options.isEnabled())

    def test_switch_file_replaces_previous_asin(self):
        p=self.panel
        p.collect_asins.setPlainText("B0DDG2KQQ9")
        p.excel_options.path.setText("B0FB2SFD5X-US-Reviews.xlsx")
        self.assertEqual(p.collect_asins.toPlainText(),"B0FB2SFD5X")
