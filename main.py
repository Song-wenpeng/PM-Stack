# -*- coding: utf-8 -*-
"""PM Stack v1.11.8 — 自动关联商品特征与历史销量"""

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
    from core.config_manager import ConfigManager
    from core.reviews.backup import BackupManager
    from PyQt6.QtCore import QLockFile
    from PyQt6.QtWidgets import QMessageBox
    config = ConfigManager()
    session_lock = QLockFile(os.path.join(os.path.dirname(config.get_path()), 'pmstack-session.lock'))
    session_lock.setStaleLockTime(0)
    os.makedirs(os.path.dirname(config.get_path()), exist_ok=True)
    if not session_lock.tryLock(0):
        QMessageBox.information(None, 'PM Stack 已运行', '请先关闭其他 PM Stack 窗口，再启动软件。')
        return
    try:
        BackupManager(config).apply_pending()
    except Exception as exc:
        QMessageBox.warning(None, '本地备份恢复失败', f'恢复未完成，继续使用原数据。可在数据与备份中取消待恢复。\n{exc}')
    # 主题 QSS 由 MainWindow 按配置应用（明/暗双主题）
    window = MainWindow(startup_warnings=config.get_warnings())
    if '--dashboard-research-check' in sys.argv:
        from core.dashboard_research_check import verify_research
        position = sys.argv.index('--dashboard-research-check')
        verify_research(window, sys.argv[position + 1], sys.argv[position + 2])
        window.close()
        return
    if '--dashboard-check' in sys.argv:
        from core.dashboard_smoke import check_dashboard
        check_dashboard(window, sys.argv[sys.argv.index('--dashboard-check') + 1])
        window.close()
        return
    if '--sales-split-check' in sys.argv:
        from core.sales_smoke import check_sales_split
        check_sales_split(window, sys.argv[sys.argv.index('--sales-split-check') + 1])
        window.close()
        return
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
        comments = next(module for _, module in window._modules if hasattr(module, 'review_collection'))
        review_tabs = [comments.tabs.tabText(i) for i in range(comments.tabs.count())]
        assert review_tabs == ['开始分析', '评论库', '分析记录']
        assert comments.tabs.currentWidget() is comments.start_tab
        assert comments.product_combo.findData('general') >= 0
        from core.reviews.prompt_editor import PromptEditorDialog
        editor = PromptEditorDialog(window.config_mgr, comments, 'general')
        assert editor.system.toPlainText() and editor.tasks.toPlainText()
        assert '用户评论：' in editor.preview.toPlainText()
        editor.close()
        Path(target).write_text(json.dumps({'startup': 'ok', 'matrix_preview': 'ok',
                                            'review_categories': categories,
                                            'app_version': window.windowTitle(), 'prompt_editor': 'ok',
                                            'review_workflow': {'tabs': review_tabs, 'default': '开始分析',
                                                                'persistent_history': True}}, ensure_ascii=False), encoding='utf-8')
        window.close()
        return
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
