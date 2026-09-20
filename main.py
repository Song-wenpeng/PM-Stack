# -*- coding: utf-8 -*-
"""PM Stack V1.10.2 — 内置评论分析并发测试子模块"""

import sys
import os

# Qt 高 DPI 适配（必须在 QApplication 创建之前设置）
os.environ['QT_ENABLE_HIGHDPI_SCALING'] = '1'
os.environ['QT_AUTO_SCREEN_SCALE_FACTOR'] = '1'
# 防止中文用户名路径导致 matplotlib 缓存崩溃
os.environ['MPLCONFIGDIR'] = os.path.join(os.environ.get('TEMP', 'C:\\Temp'), 'mpl_config')

# 确保 APP 目录在 sys.path 中
APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont
from core.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    # 主题 QSS 由 MainWindow 按配置应用（明/暗双主题）
    window = MainWindow()
    if '--review-backend-check' in sys.argv:
        import json
        import tempfile
        from pathlib import Path
        from core.reviews.scraper import AmazonReviewScraper
        from core.reviews.store import ReviewStore

        target = sys.argv[sys.argv.index('--review-backend-check') + 1]
        report = {
            'review_ui': any(
                hasattr(widget, 'review_collection') for _, widget in window._modules
            ),
            'sqlite': 'pending',
            'edge': 'pending',
            'python': sys.version.split()[0],
        }
        with tempfile.TemporaryDirectory(prefix='pm-stack-review-check-') as temp_dir:
            store = ReviewStore(os.path.join(temp_dir, 'reviews.db'))
            try:
                report['sqlite'] = store.integrity_check()
            finally:
                store.close()
        # Exercise the same background-thread lifecycle used by collection.
        from concurrent.futures import ThreadPoolExecutor
        def check_edge():
            scraper = AmazonReviewScraper(headless=True)
            try:
                scraper._init_driver()
                return 'ok'
            finally:
                scraper.close()
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                report['edge'] = executor.submit(check_edge).result()
        except Exception as exc:
            report['edge'] = str(exc)
        Path(target).write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
        window.close()
        return
    if '--startup-check' in sys.argv:
        import json
        from pathlib import Path
        import pandas as pd
        from core.matrix_workspace import prepare_data
        target = sys.argv[sys.argv.index('--startup-check') + 1]
        matrices = [widget for _, widget in window._modules
                    if hasattr(widget, 'free_matrix')]
        if not matrices:
            raise RuntimeError('自由组合矩阵未加载')
        workspace = matrices[0].free_matrix
        workspace.frame = prepare_data(pd.DataFrame({
            'ASIN': ['TEST'], '品牌': ['测试'], '上架时间': ['2025-01-01']}))
        for combo in (workspace.horizontal, workspace.vertical, workspace.sort):
            combo.addItems(['不分组'] + list(workspace.frame.columns))
        workspace.render()
        assert len(workspace.row_names) == 1 and workspace.table.rowCount() == workspace.header_rows + 1
        categories = {}
        for _, module in window._modules:
            for name in ('s1_product', 's2_product', 's12_product', 'batch_product', 'product_combo'):
                combo = getattr(module, name, None)
                if combo is not None:
                    categories[name] = [combo.itemData(i) for i in range(combo.count())]
            if hasattr(module, 'review_collection'):
                combo = module.review_collection.excel_options.category
                categories['excel_import'] = [combo.itemData(i) for i in range(combo.count())]
        Path(target).write_text(json.dumps({'startup': 'ok', 'matrix_preview': 'ok',
                                            'review_categories': categories}), encoding='utf-8')
        window.close()
        return
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
