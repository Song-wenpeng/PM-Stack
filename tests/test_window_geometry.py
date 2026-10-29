"""The initial window must fit the available screen area, including its origin."""
from tests import support

import tempfile
import unittest
from unittest.mock import MagicMock, patch

from PyQt6.QtCore import QRect


class WindowGeometryTests(unittest.TestCase):
    def setUp(self):
        from core.main_window import MainWindow
        self.app = support.qt_app()
        self.addCleanup(support.cleanup_qt_widgets)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        with patch.object(MainWindow, '_show_startup_issues'), \
                patch.object(MainWindow, '_set_initial_geometry'):
            self.window = MainWindow()
        self.addCleanup(self.window.deleteLater)

    def apply(self, area):
        screen = MagicMock()
        screen.availableGeometry.return_value = area
        with patch('core.main_window.QScreen', screen), \
                patch('core.main_window.QApplication') as app:
            app.primaryScreen.return_value = object()
            self.window._set_initial_geometry()
        return self.window.geometry()

    def assert_inside(self, geometry, area):
        self.assertGreaterEqual(geometry.left(), area.left())
        self.assertGreaterEqual(geometry.top(), area.top())
        self.assertLessEqual(geometry.right(), area.right())
        self.assertLessEqual(geometry.bottom(), area.bottom())

    def test_small_screen_does_not_overflow(self):
        area = QRect(0, 0, 1024, 600)
        geometry = self.apply(area)
        self.assert_inside(geometry, area)
        self.assertEqual((geometry.width(), geometry.height()), (1024, 600))
        self.assertEqual((geometry.x(), geometry.y()), (0, 0))
        self.assertLessEqual(self.window.minimumWidth(), area.width())
        self.assertLessEqual(self.window.minimumHeight(), area.height())

    def test_old_formula_would_have_missed_the_small_screen(self):
        """Regression guard: the pre-fix formula produced x=-28 y=-50 1080x700."""
        area = QRect(0, 0, 1024, 600)
        legacy_w = max(1080, min(int(area.width() * 0.82), 1440))
        legacy_h = max(700, min(int(area.height() * 0.85), 900))
        legacy = QRect((area.width() - legacy_w) // 2, (area.height() - legacy_h) // 2,
                       legacy_w, legacy_h)
        self.assertEqual((legacy.x(), legacy.y()), (-28, -50))
        geometry = self.apply(area)
        self.assertNotEqual((geometry.x(), geometry.y()), (-28, -50))

    def test_secondary_screen_origin_is_included(self):
        area = QRect(1920, 0, 1600, 900)
        geometry = self.apply(area)
        self.assert_inside(geometry, area)
        self.assertGreaterEqual(geometry.x(), 1920)

    def test_negative_origin_screen_stays_on_screen(self):
        area = QRect(-1920, -200, 1600, 900)
        geometry = self.apply(area)
        self.assert_inside(geometry, area)
        self.assertLess(geometry.x(), 0)
        self.assertLess(geometry.y(), 0)

    def test_large_screen_keeps_the_preferred_size_and_centering(self):
        area = QRect(0, 0, 2560, 1440)
        geometry = self.apply(area)
        self.assertEqual((geometry.width(), geometry.height()), (1440, 900))
        self.assertEqual((geometry.x(), geometry.y()), (560, 270))

    def test_taskbar_reduces_available_area_not_the_full_screen(self):
        area = QRect(0, 0, 1920, 1040)  # 1080p minus a 40px taskbar
        geometry = self.apply(area)
        self.assert_inside(geometry, area)
        self.assertLessEqual(geometry.bottom(), 1039)


if __name__ == '__main__':
    unittest.main()
