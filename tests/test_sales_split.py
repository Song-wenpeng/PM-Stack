"""Sales allocation regression and unified file/folder revenue workflow."""
from tests import support

import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

from scripts import batch_sales_split as split
from scripts import sales_number
from scripts.extract_history_data import read_source_folder


class SalesSplitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def source(self, name='Competitor-US-2024.04-437681.xlsx', **changes):
        data = {'ASIN': ['A', 'B'], '父ASIN': ['P', 'P'],
                '月销量': [100, 100], '子体销量': [1, 3],
                '月销售额($)': [9999, 9999], '子体销售额($)': [800, 200],
                '价格($)': ['$2.50', '$7.25'], '品牌': ['one', 'two']}
        data.update(changes)
        path = self.folder / name
        pd.DataFrame(data).to_excel(path, index=False)
        return path

    def test_corrected_revenue_uses_each_child_price_and_preserves_raw_columns(self):
        path = self.source()
        result = split.process_file(path)
        self.assertEqual(result['子体销量_矫正'].tolist(), [25, 75])
        self.assertEqual(result['子体销售额_矫正'].tolist(), [62.5, 543.75])
        self.assertEqual(result['月销售额($)'].tolist(), [9999, 9999])
        self.assertEqual(result['子体销售额($)'].tolist(), [800, 200])
        self.assertEqual(result['品牌'].tolist(), ['one', 'two'])
        self.assertEqual(result['ASIN'].tolist(), ['A', 'B'])

    def test_volume_edge_cases_remain_unchanged(self):
        cases = [(100, [0, 0, 0], [34, 33, 33]),
                 (10, [1, 1, 1], [4, 3, 3]),
                 (0, [2, 3, 4], [2, 3, 4]),
                 (None, [2, 3, 4], [2, 3, 4]),
                 (5, [2, 3, 4], [2, 3, 4])]
        for parent, children, expected in cases:
            with self.subTest(parent=parent, children=children):
                path = self.source(**{'ASIN': ['A', 'B', 'C'], '父ASIN': ['P'] * 3,
                    '月销量': [parent] * 3, '子体销量': children, '价格($)': [2, 3, 4],
                    '月销售额($)': [99] * 3, '子体销售额($)': [10] * 3,
                    '品牌': ['one'] * 3})
                result = split.process_file(path)
                self.assertEqual(result['子体销量_矫正'].tolist(), expected)
                self.assertEqual(result['子体销售额_矫正'].tolist(),
                                 [value * price for value, price in zip(expected, [2, 3, 4])])

    def test_standard_volume_still_comes_from_largest_child(self):
        result = split.process_file(self.source(**{'月销量': [500, 100]}))
        self.assertEqual(result['子体销量_矫正'].tolist(), [25, 75])

    def test_price_is_read_separately_for_each_month_and_revenue_columns_optional(self):
        first = self.source()
        second = self.source('Competitor-2024.05.xlsx', **{'价格($)': [4, 8]})
        frame = pd.read_excel(second).drop(columns=['月销售额($)', '子体销售额($)'])
        frame.to_excel(second, index=False)
        self.assertEqual(split.process_file(first)['子体销售额_矫正'].tolist(), [62.5, 543.75])
        self.assertEqual(split.process_file(second)['子体销售额_矫正'].tolist(), [100, 600])

    def test_missing_invalid_and_ambiguous_prices_fail_with_actionable_error(self):
        for prices in ([None, 2], ['--', 2], [-1, 2], [float('inf'), 2]):
            with self.subTest(prices=prices):
                with self.assertRaisesRegex(ValueError, 'Excel 行：2'):
                    split.process_file(self.source(**{'价格($)': prices}))
        path = self.source(**{'售价': [2, 3]})
        with self.assertRaisesRegex(ValueError, '唯一'):
            split.process_file(path)
        frame = pd.read_excel(path).drop(columns=['价格($)', '售价'])
        frame.to_excel(path, index=False)
        with self.assertRaisesRegex(ValueError, '无'):
            split.process_file(path)

    def run_cli(self, *args):
        with patch.object(sys, 'argv', ['batch_sales_split.py', *map(str, args)]), contextlib.redirect_stdout(io.StringIO()):
            return split.main()

    def test_single_folder_and_legacy_entry_match_and_feed_history_extraction(self):
        path = self.source()
        single_out = self.folder / 'single'
        folder_out = self.folder / 'batch'
        self.assertEqual(self.run_cli(path, '--output-dir', single_out), 0)
        self.assertEqual(self.run_cli(self.folder, '--output-dir', folder_out), 0)
        a = pd.read_excel(split.output_path(path, single_out))
        b = pd.read_excel(split.output_path(path, folder_out))
        pd.testing.assert_frame_equal(a, b)
        legacy = self.folder / 'legacy.xlsx'
        with patch.object(sys, 'argv', ['sales_number.py', str(path), str(legacy)]), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(sales_number.main(), 0)
        pd.testing.assert_frame_equal(a, pd.read_excel(legacy))
        volume, revenue = read_source_folder(str(folder_out), '子体销量_矫正', '子体销售额_矫正')
        self.assertEqual(volume['2024-04'].tolist(), [25, 75])
        self.assertEqual(revenue['2024-04'].tolist(), [62.5, 543.75])

    def test_batch_continues_after_failure_and_reports_nonzero(self):
        good = self.source()
        bad = self.source('bad.xlsx', **{'价格($)': [None, 4]})
        self.assertEqual(self.run_cli(self.folder), 1)
        self.assertTrue(Path(split.output_path(good)).exists())
        self.assertFalse(Path(split.output_path(bad)).exists())

    def test_rerun_updates_result_with_backup_and_skips_generated_files(self):
        path = self.source()
        self.assertEqual(self.run_cli(self.folder), 0)
        previous = Path(split.output_path(path)).read_bytes()
        self.source(**{'价格($)': [4, 8]})
        self.assertEqual(self.run_cli(self.folder), 0)
        backup = list(self.folder.glob('*.backup'))
        self.assertEqual(len(backup), 1)
        self.assertEqual(backup[0].read_bytes(), previous)
        self.assertEqual(pd.read_excel(split.output_path(path))['子体销售额_矫正'].tolist(), [100, 600])
        pending, skipped = split.scan_directory(self.folder)
        self.assertEqual([name for name, _ in pending], [path.name])
        self.assertEqual(len(skipped), 1)


if __name__ == '__main__':
    unittest.main()
