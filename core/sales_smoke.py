"""Exercise real button signals and the bundled sales script on disposable data."""
import json
import tempfile
from pathlib import Path

import pandas as pd
from PyQt6.QtCore import QEventLoop, QTimer


def check_sales_split(window, report_path):
    sales = next(module for _, module in window._modules if hasattr(module, 'split_input'))
    report = {'app_version': window.windowTitle(), 'checks': []}
    with tempfile.TemporaryDirectory(prefix='pm-stack-sales-check-') as temp:
        root = Path(temp)
        source = root / 'Competitor-2026.10.xlsx'
        frame = pd.DataFrame({'ASIN': ['A', 'B'], '父ASIN': ['P', 'P'],
                              '月销量': [100, 100], '子体销量': [1, 3],
                              '价格(€)': [2.5, 7.25],
                              '子体销售额(€)': [1000, 2000]})
        frame.to_excel(source, index=False)
        original = source.read_bytes()
        for name, path, expected_code in (('file_click', source, 0),
                                          ('folder_click', root, 0),
                                          ('invalid_price_click', root / 'bad.xlsx', 1)):
            if expected_code:
                frame['价格(€)'] = [None, 7.25]
                frame.to_excel(path, index=False)
            sales.split_input.setText(str(path))
            codes = []
            # The click method exercises the clicked(bool) signal, unlike a
            # direct call to _run_split, which missed the original crash.
            sales.run_btn1.click()
            sales.runner.finished_signal.connect(codes.append)
            loop = QEventLoop()
            poll = QTimer()
            poll.setInterval(10)
            poll.timeout.connect(lambda: loop.quit() if not sales.clean_actions.running else None)
            timeout = QTimer()
            timeout.setSingleShot(True)
            timeout.timeout.connect(loop.quit)
            poll.start()
            timeout.start(30000)
            loop.exec()
            poll.stop()
            timeout.stop()
            sales.runner.finished_signal.disconnect(codes.append)
            assert codes == [expected_code], (name, codes, sales.log1.text.toPlainText())
            assert not sales.clean_actions.running
            assert sales.run_btn1.isEnabled()
            assert source.read_bytes() == original
            if expected_code == 0:
                result = Path(sales.clean_actions.result_path)
                output = pd.read_excel(result)
                assert output['子体销量_矫正'].tolist() == [25, 75]
                assert output['子体销售额_矫正'].tolist() == [62.5, 543.75]
                assert output['子体销售额(€)'].tolist() == [1000, 2000]
            else:
                assert not sales.clean_actions.result_path
                assert 'Excel 行' in sales.log1.text.toPlainText()
            report['checks'].append(name)
        from openpyxl import Workbook
        list_path = root / '商品名单.xlsx'
        book = Workbook()
        sheet = book.active
        sheet.title = '商品属性'
        sheet.append(['图片', 'ASIN'])
        sheet.append([None, ' b '])
        sheet.append([None, 'B'])
        sheet.append([None, 'MISSING'])
        sheet.row_dimensions[2].hidden = True
        book.save(list_path)
        book.close()
        destination = root / '历史数据.xlsx'
        sales.trend_folder.setText(str(root))
        sales.trend_asin_file.setText(str(list_path))
        sales.trend_asin_sheet.setText('商品属性')
        sales.trend_output.setText(str(destination))
        codes = []
        sales.run_btn2.click()
        sales.runner.finished_signal.connect(codes.append)
        loop = QEventLoop()
        poll = QTimer()
        poll.setInterval(10)
        poll.timeout.connect(lambda: loop.quit() if not sales.run_btn2._task_bar.running else None)
        timeout = QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(loop.quit)
        poll.start()
        timeout.start(30000)
        loop.exec()
        poll.stop()
        timeout.stop()
        sales.runner.finished_signal.disconnect(codes.append)
        assert codes == [0], (codes, sales.log2.text.toPlainText())
        volume = pd.read_excel(destination, sheet_name='历史销量')
        revenue = pd.read_excel(destination, sheet_name='历史销额')
        assert volume['ASIN'].tolist() == ['B', 'MISSING']
        assert revenue['ASIN'].tolist() == ['B', 'MISSING']
        assert volume.iloc[0, 1] == 75
        assert revenue.iloc[0, 1] == 543.75
        assert pd.isna(volume.iloc[1, 1])
        assert '未找到 1 个' in sales.log2.text.toPlainText()
        report['checks'].append('asin_list_extraction_click')
        report['asin_list_extraction'] = 'ok'
        report['sales_split'] = 'ok'
        report['log'] = sales.log1.text.toPlainText()
    Path(report_path).write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
