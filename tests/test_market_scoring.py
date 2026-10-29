"""Market opportunity scoring regressions: analysis date, snapshot and safe output."""
from tests import support

from contextlib import redirect_stdout
import datetime as dt
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/欧洲市场规划/机会得分.py'
COLUMNS = ['ASIN', '小类目', '小类BSR', '月销量', '月销售额(€)', '价格(€)',
           '评分数', '月新增评分数', '评分', '上架时间']


def category_workbook(path, launches, name='测试类目'):
    """One synthetic category file; launches are ISO date strings per ASIN."""
    rows = []
    for i, launch in enumerate(launches):
        rows.append([f'A{i}', name, i + 1, 100 * (len(launches) - i),
                     1000.0 * (len(launches) - i), 19.99, 50 + i, 5 + i, 4.5, launch])
    frame = pd.DataFrame(rows, columns=COLUMNS)
    with pd.ExcelWriter(path, engine='openpyxl') as writer:
        frame.to_excel(writer, sheet_name='DE', index=False)
    return path


class MarketScoringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data_dir = self.root / 'data'
        self.data_dir.mkdir()
        self.output = self.root / 'summary.xlsx'
        self.log = io.StringIO()

    def execute(self, launches=('2024-01-15', '2025-06-01'), analysis_date=None,
                output=None, data_dir=None):
        source = category_workbook(self.data_dir / 'cat_12345.xlsx', list(launches))
        self.original = {source: hashlib.sha256(source.read_bytes()).hexdigest()}
        if output is not None:
            self.output = Path(output)
        env = {'MARKET_DATA_DIR': str(data_dir or self.data_dir),
               'MARKET_OUTPUT_FILE': str(self.output)}
        if analysis_date is not None:
            env['MARKET_ANALYSIS_DATE'] = analysis_date
        with patch.dict(os.environ, env, clear=False), redirect_stdout(self.log):
            if analysis_date is None:
                os.environ.pop('MARKET_ANALYSIS_DATE', None)
            try:
                runpy.run_path(str(SCRIPT), run_name='__main__')
            except SystemExit as exc:
                return exc.code or 0
            except Exception as exc:
                self.log.write(f'{type(exc).__name__}: {exc}')
                return 1
        return 0

    def raw(self):
        return pd.read_excel(self.output, sheet_name='原始Top100汇总')

    def summary(self):
        return pd.read_excel(self.output, sheet_name='类目汇总评分')

    def sheets(self):
        return list(pd.read_excel(self.output, sheet_name=None))

    def test_import_does_not_scan_directories_or_write_files(self):
        with patch.dict('os.environ', {'MARKET_DATA_DIR': str(self.root / 'absent'),
                                       'MARKET_OUTPUT_FILE': str(self.root / 'absent.xlsx')}):
            spec = importlib.util.spec_from_file_location('market_scoring_test', SCRIPT)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        self.assertFalse((self.root / 'absent.xlsx').exists())
        self.assertTrue(hasattr(module, 'main'))

    def test_explicit_analysis_date_drives_launch_age(self):
        code = self.execute(('2026-07-01', '2024-01-15'), analysis_date='2026-07-31')
        self.assertEqual(code, 0, self.log.getvalue())
        frame = self.raw().set_index('ASIN')
        self.assertEqual(int(frame.loc['A0', '上架天数']), 30)
        self.assertTrue(bool(frame.loc['A0', '是否新品']))

    def test_default_analysis_date_is_run_day_not_stale_constant(self):
        recent = (dt.date.today() - dt.timedelta(days=30)).isoformat()
        code = self.execute((recent, '2024-01-15'))
        self.assertEqual(code, 0, self.log.getvalue())
        frame = self.raw().set_index('ASIN')
        self.assertIn(int(frame.loc['A0', '上架天数']), (29, 30, 31))
        self.assertTrue(bool(frame.loc['A0', '是否新品']))

    def test_invalid_analysis_date_fails_with_clear_message(self):
        for bad in ('not-a-date', '2026-13-45', '31/07/2026', '2026年7月31日', '15'):
            with self.subTest(bad=bad):
                self.log = io.StringIO()
                self.output = self.root / f'summary-{abs(hash(bad))}.xlsx'
                code = self.execute(analysis_date=bad)
                self.assertNotEqual(code, 0)
                self.assertFalse(self.output.exists())
                self.assertIn('MARKET_ANALYSIS_DATE', self.log.getvalue())

    def test_accepted_analysis_date_formats(self):
        for text, expected in (('2026-07-31', '2026-07-31'), ('2026/07/31', '2026-07-31'),
                               ('2026.07.31', '2026-07-31'), ('2026-7-1', '2026-07-01')):
            with self.subTest(text=text):
                spec = importlib.util.spec_from_file_location(f'scoring_{abs(hash(text))}', SCRIPT)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                resolved, source = module.resolve_analysis_date(text)
                self.assertEqual(f'{resolved:%Y-%m-%d}', expected)
                self.assertIn(text, source)

    def test_blank_analysis_date_falls_back_to_run_day(self):
        spec = importlib.util.spec_from_file_location('scoring_default', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for raw in ('', '   ', None):
            with self.subTest(raw=repr(raw)):
                resolved, source = module.resolve_analysis_date(raw, today=dt.date(2026, 10, 28))
                self.assertEqual(f'{resolved:%Y-%m-%d}', '2026-10-28')
                self.assertIn('默认', source)

    def test_launch_after_analysis_date_is_flagged_not_counted_as_new(self):
        code = self.execute(('2026-09-01', '2024-01-15'), analysis_date='2026-07-31')
        self.assertEqual(code, 0, self.log.getvalue())
        frame = self.raw().set_index('ASIN')
        self.assertLess(int(frame.loc['A0', '上架天数']), 0)
        self.assertFalse(bool(frame.loc['A0', '是否新品']))
        self.assertIn('晚于分析基准日', self.log.getvalue())
        self.assertEqual(int(self.summary().iloc[0]['近一年新品数']), 0)

    def test_parameter_snapshot_records_basis_files_and_thresholds(self):
        code = self.execute(analysis_date='2026-07-31')
        self.assertEqual(code, 0, self.log.getvalue())
        self.assertIn('参数快照', self.sheets())
        snapshot = pd.read_excel(self.output, sheet_name='参数快照')
        values = dict(zip(snapshot['参数'].astype(str), snapshot['值'].astype(str)))
        self.assertEqual(values['分析基准日'], '2026-07-31')
        self.assertIn('基准日来源', values)
        self.assertEqual(values['新品天数阈值'], '365')
        self.assertEqual(values['参与类目文件数'], '1')
        self.assertIn('cat_12345.xlsx', values['参与文件'])

    def test_score_guide_states_relative_quantile_scope(self):
        code = self.execute(analysis_date='2026-07-31')
        self.assertEqual(code, 0, self.log.getvalue())
        guide = pd.read_excel(self.output, sheet_name='评分说明').astype(str)
        text = ' '.join(guide.values.ravel().tolist())
        self.assertIn('相对', text)
        self.assertIn('分位', text)

    def test_output_inside_data_dir_is_not_ingested_as_a_category(self):
        inside = self.data_dir / 'summary.xlsx'
        first = self.execute(analysis_date='2026-07-31', output=inside)
        self.assertEqual(first, 0, self.log.getvalue())
        self.log = io.StringIO()
        second = self.execute(analysis_date='2026-07-31', output=inside)
        self.assertEqual(second, 0, self.log.getvalue())
        self.assertEqual(len(self.summary()), 1)
        self.assertIn('排除', self.log.getvalue())

    def test_output_cannot_overwrite_a_source_category(self):
        category_workbook(self.data_dir / 'cat_67890.xlsx', ['2024-01-15'])
        original_path = self.data_dir / 'cat_12345.xlsx'
        code = self.execute(analysis_date='2026-07-31', output=original_path)
        self.assertNotEqual(code, 0, self.log.getvalue())
        self.assertEqual(hashlib.sha256(original_path.read_bytes()).hexdigest(),
                         self.original[original_path])
        self.assertIn('禁止覆盖输入原件', self.log.getvalue())

    def test_output_hardlink_cannot_hide_a_source_category(self):
        source = category_workbook(self.data_dir / 'cat_67890.xlsx', ['2024-01-15'])
        original = source.read_bytes()
        alias = self.root / 'alias.xlsx'
        os.link(source, alias)
        code = self.execute(analysis_date='2026-07-31', output=alias)
        self.assertNotEqual(code, 0, self.log.getvalue())
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(alias.read_bytes(), original)

    def test_source_files_are_never_modified(self):
        code = self.execute(analysis_date='2026-07-31', output=self.data_dir / 'out.xlsx')
        self.assertEqual(code, 0, self.log.getvalue())
        for path, digest in self.original.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)

    def test_missing_data_dir_fails_without_traceback_noise(self):
        env = {'MARKET_DATA_DIR': str(self.root / 'absent'),
               'MARKET_OUTPUT_FILE': str(self.output)}
        with patch.dict('os.environ', env, clear=False), redirect_stdout(self.log):
            try:
                runpy.run_path(str(SCRIPT), run_name='__main__')
            except SystemExit as exc:
                code = exc.code or 0
            except Exception:
                code = 1
            else:
                code = 0
        self.assertNotEqual(code, 0)
        self.assertFalse(self.output.exists())
        self.assertIn('未找到', self.log.getvalue())

    def test_scoring_structure_and_weights_are_preserved(self):
        code = self.execute(analysis_date='2026-07-31')
        self.assertEqual(code, 0, self.log.getvalue())
        row = self.summary().iloc[0]
        for column in ('市场体量分', '竞争结构分', '价格环境分', '新品成长机会分',
                       '门槛与热度分', '市场机会总分', '类目标签', '建议动作'):
            self.assertIn(column, row.index)
        parts = sum(float(row[c]) for c in ('市场体量分', '竞争结构分', '价格环境分',
                                            '新品成长机会分', '门槛与热度分'))
        self.assertAlmostEqual(float(row['市场机会总分']), parts, places=6)
        self.assertGreaterEqual(float(row['市场机会总分']), 0)
        self.assertLessEqual(float(row['市场机会总分']), 100)
        self.assertIn(row['类目标签'], {'A', 'B', 'C', 'D'})


class MarketScoringUITests(unittest.TestCase):
    """The scoring tab must surface the reference date and reject bad input early."""

    def setUp(self):
        from core.config_manager import ConfigManager
        from modules.market_planning import ModuleWidget
        self.app = support.qt_app()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(support.cleanup_qt_widgets)
        self.root = Path(self.tmp.name)
        self.runner = MagicMock()
        self.runner.is_running.return_value = False
        self.runner.is_any_running.return_value = False
        self.widget = ModuleWidget(ConfigManager(str(self.root / 'config.json')), self.runner)
        self.widget.score_dir.setText(str(self.root))

    def tearDown(self):
        from PyQt6.QtCore import QThreadPool
        QThreadPool.globalInstance().waitForDone(5000)

    def test_hint_shows_run_day_default_and_relative_scope(self):
        hint = self.widget.score_hint.text()
        self.assertIn(dt.date.today().strftime('%Y-%m-%d'), hint)
        self.assertIn('相对分位', hint)
        self.assertIn('脚本默认输出路径', hint)
        self.widget.score_output.setText(str(self.root / 'summary.xlsx'))
        self.assertIn('summary.xlsx', self.widget.score_hint.text())

    def test_explicit_date_is_forwarded_to_the_script(self):
        with patch.object(self.widget, '_run', return_value=True) as run:
            self.widget.score_date.setText('2026-07-31')
            self.widget._run_scoring()
        env = run.call_args.args[2]
        self.assertEqual(env['MARKET_ANALYSIS_DATE'], '2026-07-31')
        self.assertEqual(env['MARKET_DATA_DIR'], str(self.root))
        self.assertIn('显式指定', self.widget.score_hint.text())

    def test_blank_date_is_forwarded_as_empty_so_script_uses_run_day(self):
        with patch.object(self.widget, '_run', return_value=True) as run:
            self.widget.score_date.setText('   ')
            self.widget._run_scoring()
        self.assertEqual(run.call_args.args[2]['MARKET_ANALYSIS_DATE'], '')

    def test_invalid_date_does_not_start_runner(self):
        for bad in ('2026年7月31日', 'not-a-date', '31/07/2026'):
            with self.subTest(bad=bad), patch.object(self.widget, '_run') as run:
                self.widget.score_date.setText(bad)
                self.assertFalse(self.widget._run_scoring())
                run.assert_not_called()
                self.assertIn('无法解析', self.widget.score_hint.text())
        self.runner.run_script.assert_not_called()


if __name__ == '__main__':
    unittest.main()
