"""Regression coverage for failed UI construction and test-process isolation."""

from tests import support

import gc
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from PyQt6 import sip
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QWidget
from core.reviews import paths
from core.reviews.panel import ReviewCollectionPanel


class TestRuntimeTests(unittest.TestCase):
    def setUp(self):
        support.qt_app()
        self.addCleanup(support.cleanup_qt_widgets)

    def test_default_review_database_is_disposable(self):
        self.assertTrue(paths.DATA_DIR.is_relative_to(support.DATA_ROOT))
        self.assertTrue(paths.EXPORT_DIR.is_relative_to(support.DATA_ROOT))
        self.assertEqual(Path(os.environ["LOCALAPPDATA"]), support.DATA_ROOT)

    def test_application_survives_gc_and_deferred_widget_deletion(self):
        app = support.qt_app()
        identity = id(app)
        widget = QWidget()
        timer = QTimer(widget)
        timer.start(1)
        del app
        gc.collect()
        self.assertEqual(id(support.qt_app()), identity)
        support.cleanup_qt_widgets()
        self.assertTrue(sip.isdeleted(widget))
        self.assertTrue(sip.isdeleted(timer))

    def test_constructor_failure_then_next_window_is_safe(self):
        identity = id(support.qt_app())
        for _ in range(3):
            with patch.object(ReviewCollectionPanel, "_load_cloud_settings",
                              side_effect=RuntimeError("simulated database unavailable")):
                with self.assertRaisesRegex(RuntimeError, "simulated database"):
                    ReviewCollectionPanel(Mock(), Mock())
            support.cleanup_qt_widgets()
            gc.collect()
            self.assertEqual(id(support.qt_app()), identity)
            with patch.object(ReviewCollectionPanel, "_load_cloud_settings"):
                panel = ReviewCollectionPanel(Mock(), Mock())
            support.cleanup_qt_widgets()
            self.assertTrue(sip.isdeleted(panel))
