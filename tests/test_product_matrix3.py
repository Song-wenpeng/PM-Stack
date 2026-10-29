"""Listing-year regressions for the brand/category matrix export."""
from tests import support
from datetime import date, datetime
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd
from openpyxl import load_workbook

from scripts.product_matrix3 import _merge_variants, build_category_brand_matrix, create_workbook, load_data


def merged_products(values):
    frame = pd.DataFrame({
        'ASIN': [f'A{i}' for i in range(len(values))],
        '父ASIN': ['PARENT'] * len(values),
        '销量': list(range(1, len(values) + 1)),
        '图片': [''] * len(values),
        '上架年份': pd.Series(values, dtype=object),
    })
    return _merge_variants(frame, '父ASIN', '销量', 'ASIN', '图片', [], [], '上架年份', '', True)


class ProductMatrix3YearTests(unittest.TestCase):
    def test_mixed_years_and_dates_are_deduplicated_and_keep_sales_representative(self):
        values = [2022, 2023.0, np.int64(2024), np.float64(2024), '2025', '2025.0',
                  ' 2025年 ', pd.Timestamp('2021-07-18'), date(2020, 5, 6),
                  datetime(2026, 1, 2), '2019-09-30', '20201231']
        products = merged_products(values)
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]['asin'], f'A{len(values) - 1}')
        self.assertEqual(products[0]['summary'], '上架时间:2019/2020/2021/2022/2023/2024/2025/2026')

    def test_missing_and_invalid_numbers_do_not_create_a_year(self):
        values = [None, np.nan, pd.NaT, pd.NA, '', '  ', 0, -1, 2024.5, '2024.5',
                  np.inf, -np.inf, True, np.bool_(True), 45000, '45000',
                  1700000000000000000, 'not a date']
        for value in values:
            with self.subTest(value=repr(value)):
                self.assertEqual(merged_products([value])[0]['summary'], '')

    def test_real_1970_date_is_preserved(self):
        self.assertEqual(merged_products([1970, '1970-06-01', date(1970, 2, 3)])[0]['summary'],
                         '上架时间:1970')

    def test_excel_numeric_years_are_correct_in_generated_workbook(self):
        frame = pd.DataFrame({
            '分类': ['扁线'] * 3, '品牌': ['Brand'] * 3,
            'ASIN': ['A1', 'A2', 'A3'], '商品主图': [''] * 3,
            '父ASIN': ['PARENT'] * 3, '销量': [10, 30, 20],
            '上架年份': [2023, 2024, 2025],
            '上架时间': pd.to_datetime(['2023-05-01', '2024-06-01', '2025-07-01']),
        })
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'source.xlsx'
            target = Path(temp) / 'matrix.xlsx'
            frame.to_excel(source, index=False, sheet_name='商品')
            source_bytes = source.read_bytes()
            loaded = load_data(str(source), '商品')
            self.assertTrue(pd.api.types.is_numeric_dtype(loaded['上架年份']))
            matrix, categories, brands = build_category_brand_matrix(
                loaded, '分类', '品牌', 'ASIN', '商品主图', [], '上架时间', True,
                None, ['Brand'], '父ASIN', '销量', [], '上架年份')
            workbook, used_images = create_workbook(matrix, categories, brands, temp, 120,
                                                   '分类', 'ASIN', [])
            workbook.save(target)
            workbook.close()
            exported = load_workbook(target)
            try:
                self.assertEqual(exported['产品矩阵']['B3'].value,
                                 '[无图]\nA2\n上架时间:2023/2024/2025')
            finally:
                exported.close()
            self.assertFalse(used_images)
            self.assertEqual(source.read_bytes(), source_bytes)


if __name__ == '__main__':
    unittest.main()
