from tests import support
import unittest
from unittest.mock import patch
import math
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog
from core.dashboard_widgets import Chart, line_bounds
from core.theme import THEME

class TrendChartTests(unittest.TestCase):
    def setUp(self):
        self.app = support.qt_app()
        self.addCleanup(support.cleanup_qt_widgets)

    def test_auto_range_includes_values_and_uses_nonzero_lower_bound(self):
        low, high = line_bounds([580000, 610000, 860000])
        self.assertGreater(low, 0)
        self.assertLess(low, 580000)
        self.assertGreater(high, 860000)
        self.assertEqual(line_bounds([580000, 860000], True)[0], 0)

    def test_flat_missing_zero_negative_and_small_changes(self):
        for values in [[100,100], [0,0], [-100,-80], [None,float('nan')], [float('inf')]]:
            low, high = line_bounds(values)
            self.assertTrue(math.isfinite(low) and math.isfinite(high))
            self.assertLess(low, high)
        low, high = line_bounds([100,100.01])
        self.assertGreaterEqual(high-low, 10)
        self.assertEqual(line_bounds([0,100])[0], 0)

    def test_render_modes_keep_missing_gaps_and_clickable_months(self):
        chart = Chart('销售额趋势 · USD')
        chart.enable_trend_controls()
        chart.resize(680,480)
        chart.set_data(['2026-01','2026-02','2026-03'], [('市场样本',[600000,float('nan'),850000])])
        chart.show()
        for theme in ['light','dark']:
            THEME.set_theme(theme)
            for zero in [False,True]:
                chart.zero_button.setChecked(zero)
                self.app.processEvents()
                self.assertFalse(chart.grab().isNull())
                self.assertEqual(len(chart.hits), 3)
        self.assertGreaterEqual(chart.minimumHeight(),480)

    def test_expanded_chart_preserves_values_and_month_drill(self):
        chart = Chart('销售额趋势 · USD')
        chart.enable_trend_controls()
        chart.set_data(['2026-01','2026-02'], [('市场样本',[600000,850000])])
        picked=[]
        chart.clicked.connect(picked.append)
        def inspect(dialog):
            child = dialog.findChild(Chart)
            self.assertEqual(child.series, chart.series)
            self.assertTrue(child.zoom_button.isHidden())
            child.clicked.emit('2026-02')
            return QDialog.DialogCode.Accepted
        with patch.object(QDialog,'exec',inspect):
            chart.open_expanded()
        self.assertEqual(picked,['2026-02'])

if __name__ == '__main__':
    unittest.main()
