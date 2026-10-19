import os
import unittest
from unittest.mock import patch

import pandas as pd

from core.field_row_filter import select_field_rows


class FieldRowFilterTests(unittest.TestCase):
    def select(self, frame, **env):
        with patch.dict(os.environ, env, clear=True):
            return select_field_rows(frame)

    def test_default_selects_all_without_tag_column(self):
        self.assertEqual(self.select(pd.DataFrame({'ASIN': ['a', 'b']})), ([0, 1], None))

    def test_numeric_text_whitespace_and_original_indices(self):
        frame = pd.DataFrame({' 打标 ': [0, 1, ' 1 ', 1.0, None, '11']}, index=range(10, 16))
        indices, rule = self.select(frame, EXTRACT_FILTER_ENABLED='1',
                                    EXTRACT_FILTER_COLUMN='打标', EXTRACT_FILTER_VALUE='1')
        self.assertEqual(indices, [11, 12, 13])
        self.assertEqual(rule, {'column': ' 打标 ', 'value': '1'})

    def test_text_labels_use_exact_match(self):
        frame = pd.DataFrame({'分类': ['普通排插', '普通排插套装', None]})
        indices, _ = self.select(frame, EXTRACT_FILTER_ENABLED='1',
                                  EXTRACT_FILTER_COLUMN='分类', EXTRACT_FILTER_VALUE='普通排插')
        self.assertEqual(indices, [0])

    def test_disabled_ignores_stale_filter(self):
        self.assertEqual(self.select(pd.DataFrame({'ASIN': ['a']}),
                                    EXTRACT_FILTER_ENABLED='0', EXTRACT_FILTER_COLUMN='不存在'), ([0], None))

    def test_missing_column_and_empty_rule_fail(self):
        for column, value in [('不存在', '1'), ('', '1'), ('打标', '')]:
            with self.subTest(column=column, value=value), self.assertRaises(ValueError):
                self.select(pd.DataFrame({'打标': [1]}), EXTRACT_FILTER_ENABLED='1',
                            EXTRACT_FILTER_COLUMN=column, EXTRACT_FILTER_VALUE=value)
