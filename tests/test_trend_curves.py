"""Cross-attribute curve data fidelity and exported chart regressions."""
from tests import support
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
from scripts import trend_by_attribute as charts


class TrendCurveTests(unittest.TestCase):
    def test_month_values_and_no_overshoot(self):
        rng = np.random.default_rng(25)
        for y in ([1, 9, 2, 2, 5, 0], [0, 0, 0], *rng.uniform(0, 100, (50, 12))):
            x = np.cumsum(rng.uniform(.1, 3, len(y)))
            xx, yy, markers = charts.smooth_monthly_points(x, y)
            np.testing.assert_array_equal(xx[markers], x)
            np.testing.assert_array_equal(yy[markers], y)
            for i in range(len(y)-1):
                part = yy[(xx >= x[i]) & (xx <= x[i+1])]
                self.assertGreaterEqual(part.min(), min(y[i:i+2]) - 1e-10)
                self.assertLessEqual(part.max(), max(y[i:i+2]) + 1e-10)

    def test_gaps_and_short_series(self):
        for y in ([], [3], [2, 5], [np.nan, 2, 9, np.nan, 7, np.nan], [np.nan, np.nan]):
            x = np.arange(len(y))
            xx, yy, markers = charts.smooth_monthly_points(x, y)
            finite = np.isfinite(y)
            np.testing.assert_array_equal(xx[markers], x[finite])
            np.testing.assert_array_equal(yy[markers], np.array(y)[finite])
            for gap in x[~finite]:
                self.assertTrue(np.isnan(yy[xx == gap]).all())
        xx, yy, _ = charts.smooth_monthly_points([0, 1], [2, 5])
        np.testing.assert_allclose(yy, 2 + 3 * xx)

    def test_all_chart_modes_keep_original_markers_and_dates(self):
        dates = ['2026-01', '2026-02', '2026-03', '2026-04']
        volume = pd.DataFrame([[10, 60, 20, 30]], index=['A'], columns=dates)
        revenue = volume * [2, 3, 4, 5]
        groups = {'测试': ['A']}
        charts.setup_font()
        with tempfile.TemporaryDirectory() as tmp:
            for mode in ('single', 'dual', 'price', 'triple'):
                path = str(Path(tmp) / (mode + '.png'))
                with patch.object(charts.plt, 'close'):
                    if mode == 'single':
                        charts.make_chart(groups, volume, '分组', 'sum', 3, path, 60, False, None)
                    else:
                        charts.make_dual_chart(groups, volume, revenue, '', 'sum', 3, path, 60, False, None,
                                              avg_price_only=mode == 'price', show_avg_price=mode == 'triple')
                    fig = charts.plt.gcf()
                    lines = [line for ax in fig.axes for line in ax.lines]
                    self.assertEqual(len(lines), {'single': 1, 'dual': 2, 'price': 2, 'triple': 3}[mode])
                    for line in lines:
                        np.testing.assert_array_equal(line.get_xdata()[line.get_markevery()], np.arange(4))
                        self.assertEqual(len(line.get_xdata()), 61)
                    np.testing.assert_array_equal(lines[0].get_ydata()[lines[0].get_markevery()], volume.iloc[0])
                    self.assertEqual([t.get_text() for t in fig.axes[0].get_xticklabels()], dates)
                    self.assertGreater(Path(path).stat().st_size, 1000)
                charts.plt.close(fig)
