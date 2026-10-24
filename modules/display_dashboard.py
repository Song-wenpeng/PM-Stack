"""Interactive, workbook-backed market dashboard."""
from dataclasses import asdict
import json
from pathlib import Path
import uuid

import pandas as pd
from PyQt6.QtCore import (Qt, QObject, QRunnable, QThreadPool, pyqtSignal,
                          QSortFilterProxyModel)
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit, QTabWidget,
    QScrollArea, QFileDialog, QMessageBox, QDialog, QTableView, QAbstractItemView,
    QHeaderView, QListWidget, QListWidgetItem, QDialogButtonBox, QTextEdit, QToolButton, QFrame)

from core.dashboard_data import (normalize, from_history, analyze, Query,
                                 METRICS, product_snapshot, export_report)
from core.dashboard_widgets import Chart, FrameModel, DetailProxy, ImportDialog, number
from core.dashboard_import import load_workbook
from core.dashboard_filters import AttributeCombo
from core.dashboard_combo import DashboardCombo
from core.widgets import make_button
from core.theme import THEME

MODULE_INFO = {'name': '展示看板', 'icon': '▥', 'order': 6,
               'description': '工作簿驱动的市场分析 · 样本份额、趋势、属性筛选与商品明细'}


class LoadSignals(QObject):
    done = pyqtSignal(object)
    failed = pyqtSignal(str)
    needs_config = pyqtSignal(str, object)


class LoadWorkbook(QRunnable):
    def __init__(self, path, options=None):
        super().__init__()
        self.path, self.options = path, options
        self.signals = LoadSignals()

    def run(self):
        try:
            result, detected = load_workbook(self.path, self.options)
            if result is None:
                self.signals.needs_config.emit(self.path, detected)
            else:
                self.signals.done.emit(result)
        except Exception as exc:
            self.signals.failed.emit(str(exc))


class ModuleWidget(QWidget):
    matrix_requested = pyqtSignal(str)

    def __init__(self, config_mgr, runner):
        super().__init__()
        self.setProperty('workspacePage', True)
        self.config_mgr = config_mgr
        self.runner = runner
        self.dataset = self.result = None
        self.loading = False
        self.filters = {}
        self.attribute_controls = {}
        self.attribute_cells = {}
        self.base_cells = []
        self.focus = None
        self._reload_state = None
        self.build_ui()

    def build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 12, 20, 14)
        toolbar = QHBoxLayout()
        self.import_btn = make_button('导入工作簿', 'primary')
        self.import_btn.clicked.connect(self.import_file)
        toolbar.addWidget(self.import_btn)
        self.source_label = QLabel('选择工作簿，自动关联商品特征与历史销量、销额')
        self.source_label.setWordWrap(True)
        toolbar.addWidget(self.source_label, 1)
        self.reload_btn = make_button('重新加载数据源')
        self.reload_btn.setToolTip('重新读取当前文件，保留仍然有效的筛选；结束月份原为最新月时自动跟随新增月份。')
        self.reload_btn.clicked.connect(self.reload_source)
        toolbar.addWidget(self.reload_btn)
        layout.addLayout(toolbar)
        info_row = QHBoxLayout()
        self.import_summary = QLabel('')
        self.import_summary.setWordWrap(True)
        info_row.addWidget(self.import_summary, 1)
        layout.addLayout(info_row)
        self.controls = QWidget()
        grid = self.control_grid = QGridLayout(self.controls)
        grid.setContentsMargins(0, 0, 0, 0)
        self.start, self.end, self.site, self.currency, self.category, self.brand, self.group, self.metric = [DashboardCombo() for _ in range(8)]
        for i, (title, control) in enumerate([('开始月份', self.start), ('结束月份', self.end),
                ('站点', self.site), ('品类', self.category),
                ('关注品牌', self.brand), ('排名维度', self.group), ('统计指标', self.metric)]):
            cell = QWidget()
            box = QVBoxLayout(cell)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(3)
            box.addWidget(QLabel(title))
            control.setMinimumWidth(80)
            box.addWidget(control)
            grid.addWidget(cell, i // 4, i % 4)
            self.base_cells.append(cell)
        self.currency.setParent(self)
        self.currency.hide()
        for col in range(4):
            grid.setColumnStretch(col, 1)
        self.metric.addItems(METRICS[::-1])
        for combo in (self.start, self.end):
            combo.set_all_action('全部月份', self.all_months)
        for combo in (self.brand, self.category):
            combo.set_all_action('全部', lambda control=combo: control.setCurrentIndex(0))
        self.site.currentIndexChanged.connect(self.site_changed)
        for combo in (self.start, self.end, self.currency, self.category, self.brand, self.group, self.metric):
            combo.currentIndexChanged.connect(self.refresh)
        self.filter_panel = QWidget()
        panel_layout = QVBoxLayout(self.filter_panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        self.controls_scroll = QScrollArea()
        self.controls_scroll.setWidgetResizable(True)
        self.controls_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.controls_scroll.setWidget(self.controls)
        panel_layout.addWidget(self.controls_scroll)
        self.arrange_controls()
        layout.addWidget(self.filter_panel)
        extra = QHBoxLayout()
        self.filter_btn = make_button('添加属性筛选')
        self.filter_btn.clicked.connect(self.add_filter)
        extra.addWidget(self.filter_btn)
        extra.addStretch(1)
        self.reset_btn = make_button('重置筛选')
        self.reset_btn.clicked.connect(self.reset_filters)
        extra.addWidget(self.reset_btn)
        self.top = QSpinBox()
        self.top.setRange(3, 20)
        self.top.setValue(10)
        self.top.setPrefix('Top ')
        self.top.valueChanged.connect(self.refresh)
        extra.addWidget(self.top)
        self.price_min, self.price_max = QDoubleSpinBox(), QDoubleSpinBox()
        for spin, label in [(self.price_min, '最低均价'), (self.price_max, '最高均价')]:
            spin.setRange(-1, 1_000_000_000)
            spin.setDecimals(2)
            spin.setSpecialValueText(label + '不限')
            spin.setValue(-1)
            spin.setToolTip(label + '，按每个 ASIN 当月销售额 ÷ 销量计算；-1 表示不限')
            spin.setMaximumWidth(145)
            spin.editingFinished.connect(self.refresh)
            extra.addWidget(spin)
        panel_layout.addLayout(extra)
        self.scope = QLabel('导入后可筛选市场范围，点击排名或月份追溯商品。')
        self.scope.setWordWrap(True)
        self.tabs = QTabWidget()
        dashboard = QWidget()
        body = QVBoxLayout(dashboard)
        kpis = QGridLayout()
        self.kpis = {}
        for i, name in enumerate(['销售额', '销量', '加权均价', '活跃ASIN', '样本份额', '同比', '上期比', '数据覆盖率']):
            label = QLabel(name + '\n—')
            label.setObjectName('DashboardKPI')
            label.setMinimumHeight(64)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.kpis[name] = label
            kpis.addWidget(label, i // 4, i % 4)
        body.addLayout(kpis)
        charts = QGridLayout()
        self.ranking = Chart('样本份额排名 · 点击查看商品', 'bar')
        self.trend = Chart('市场规模趋势 · 点击月份查看明细')
        self.shares = Chart('主要分组的月度份额')
        self.ranking.setMinimumHeight(360)
        self.trend.enable_trend_controls()
        charts.addWidget(self.ranking, 0, 0)
        charts.addWidget(self.trend, 0, 1)
        charts.addWidget(self.shares, 1, 0, 1, 2)
        charts.setColumnStretch(0, 1)
        charts.setColumnStretch(1, 1)
        body.addLayout(charts)
        self.ranking.clicked.connect(self.drill_group)
        self.trend.clicked.connect(self.drill_month)
        self.shares.clicked.connect(self.drill_month)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(dashboard)
        self.tabs.addTab(scroll, '分析看板')
        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索 ASIN、品牌或任意属性（只筛明细，不改变市场分母）')
        row.addWidget(self.search, 1)
        clear_focus = make_button('清除图表定位')
        clear_focus.clicked.connect(self.clear_focus)
        row.addWidget(clear_focus)
        detail_layout.addLayout(row)
        self.detail_hint = QLabel()
        self.detail_hint.setWordWrap(True)
        detail_layout.addWidget(self.detail_hint)
        self.model = FrameModel(parent=self)
        self.proxy = DetailProxy(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortRole(Qt.ItemDataRole.UserRole)
        self.proxy.setFilterKeyColumn(-1)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.search.textChanged.connect(self.search_changed)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.proxy.sort(-1)  # Keep input order until the user explicitly sorts a column.
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setDefaultSectionSize(125)
        detail_layout.addWidget(self.table)
        self.tabs.addTab(detail, '商品明细')
        layout.addWidget(self.tabs, 1)
        footer = QHBoxLayout()
        self.status = QLabel('尚未导入数据')
        self.status.setWordWrap(True)
        footer_text = QVBoxLayout()
        footer_text.setSpacing(4)
        footer_text.addWidget(self.status)
        footer_text.addWidget(self.scope)
        footer.addLayout(footer_text, 1)
        self.export_btn = make_button('导出看板与明细')
        self.export_btn.clicked.connect(self.export)
        footer.addWidget(self.export_btn)
        self.matrix_btn = make_button('发送到产品矩阵', 'primary')
        self.matrix_btn.setToolTip('有选中行时发送所选 ASIN；否则发送当前明细中的全部 ASIN。按期间汇总销量/销额，属性取最新月。')
        self.matrix_btn.clicked.connect(self.send_matrix)
        footer.addWidget(self.matrix_btn)
        layout.addLayout(footer)
        self.enable_data(False)
        THEME.changed.connect(self.apply_theme)
        self.apply_theme()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.arrange_controls()

    def all_months(self):
        self.loading = True
        self.start.setCurrentIndex(0)
        self.end.setCurrentIndex(self.end.count() - 1)
        self.loading = False
        self.refresh()

    def apply_theme(self):
        t = THEME.tokens()
        for label in self.kpis.values():
            label.setStyleSheet(f"QLabel {{ background: {t['card']}; color: {t['text']}; border: 1px solid {t['border']}; border-radius: 8px; padding: 8px; font-size: 14px; }}")

    def enable_data(self, enabled):
        for widget in (self.controls, self.filter_btn, self.reset_btn, self.top, self.price_min,
                       self.price_max, self.export_btn, self.matrix_btn, self.reload_btn):
            widget.setEnabled(enabled)

    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择含商品特征和历史数据的工作簿', '', 'Excel (*.xlsx *.xlsm)')
        if path:
            self.start_load(path)

    def reload_source(self):
        if self.dataset is not None:
            self.start_load(self.dataset.source, self.dataset.import_options or None, preserve=True)

    def start_load(self, path, options=None, preserve=False):
        self._reload_state = None
        if preserve and self.dataset is not None:
            self._reload_state = {'query': self.query(), 'latest': self.end.itemText(self.end.count() - 1),
                                  'fields': list(self.attribute_controls), 'search': self.search.text()}
        self.import_btn.setEnabled(False)
        self.enable_data(False)
        self.status.setText('正在自动识别并按 ASIN 关联历史数据…')
        self.worker = LoadWorkbook(path, options)
        self.worker.signals.done.connect(self.set_dataset)
        self.worker.signals.failed.connect(self.import_failed)
        self.worker.signals.needs_config.connect(self.configure_source)
        QThreadPool.globalInstance().start(self.worker)

    def configure_source(self, path, detected):
        self.import_btn.setEnabled(True)
        self.enable_data(self.dataset is not None)
        try:
            dialog = ImportDialog(path, self, detected=detected)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.start_load(path, dialog.options())
            else:
                self._reload_state = None
                self.status.setText('已取消调整；当前看板保持不变')
        except Exception as exc:
            self.import_failed(str(exc))

    def adjust_source(self):
        if self.dataset:
            self.configure_source(self.dataset.source, self.dataset.import_options)

    def show_notes(self):
        if not self.dataset:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('数据来源与关联说明')
        dialog.resize(760, 540)
        box = QVBoxLayout(dialog)
        text = QTextEdit()
        text.setReadOnly(True)
        opts = self.dataset.import_options
        lines = [self.dataset.source, '', *self.dataset.notes, '', '数据来源：']
        lines += [f'{label}：{opts.get(key, "")}' for key, label in [('sheet', '商品属性表'), ('units', '历史销量'), ('revenue', '历史销额'), ('site', '默认站点'), ('currency', '默认币种')]]
        lines += ['', '属性关联处理（仅用于看板，未改写源文件）：']
        lines += [f'{issue["ASIN"]} · 原表第 {issue["原表行"]} 行 · {issue["处理"]}' for issue in self.dataset.issues] or ['无关联问题']
        text.setPlainText('\n'.join(lines))
        box.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        box.addWidget(buttons)
        dialog.exec()

    def import_failed(self, error):
        self.import_btn.setEnabled(True)
        self.enable_data(self.dataset is not None)
        self._reload_state = None
        self.status.setText('加载失败；原看板数据和筛选保持不变')
        QMessageBox.warning(self, '看板导入失败', error)

    @staticmethod
    def fill(combo, values, all_item=False):
        combo.clear()
        if all_item:
            combo.addItem('全部', '')
        for value in values:
            combo.addItem(str(value), str(value))

    def set_dataset(self, dataset):
        self.loading = True
        self.dataset = dataset
        frame = dataset.frame
        months = sorted(frame['月份'].unique())
        self.fill(self.start, months)
        self.fill(self.end, months)
        self.end.setCurrentIndex(len(months) - 1)
        if dataset.available_history:
            self.start.setCurrentIndex(max(0, len(months) - 12))
        self.fill_markets()
        self.fill(self.category, sorted(frame['品类'].unique()), True)
        self.fill(self.brand, sorted(frame['品牌'].unique()), True)
        excluded = {'ASIN', '月份', '站点', '币种', '均价', *METRICS}
        excluded.update(c for c in frame.columns if c.startswith('image_') or any(part in c for part in ('链接', '描述', '主图', '详细参数', '卖家信息', '标题')) or c == '图片')
        self.dimensions = list(dict.fromkeys(['品牌', '品类', *dataset.feature_fields, *[c for c in frame.columns if c not in excluded]]))
        self.fill(self.group, self.dimensions)
        self.group.setCurrentText('品牌')
        self.filters = {}
        pinned = list(self.attribute_controls) or self.config_mgr.get('dashboard_filter_fields', [])
        self.restore_attribute_fields(pinned)
        self.focus = None
        self.search.clear()
        self.price_min.setValue(-1)
        self.price_max.setValue(-1)
        self.source_label.setText(f'{Path(dataset.source).name} · {frame["ASIN"].nunique():,} 个商品')
        self.import_summary.setText(('已关联商品特征、历史销量、历史销额' if dataset.available_history else '已读取月度明细') + f' · {months[0]} 至 {months[-1]}' + (f' · {len(dataset.issues)} 项关联提示' if dataset.issues else ''))
        self.source_label.setToolTip(dataset.source + '\n' + '\n'.join(dataset.notes))
        self.import_summary.setToolTip('\n'.join(dataset.notes + [str(issue) for issue in dataset.issues]))
        self.import_btn.setEnabled(True)
        self.enable_data(True)
        notices = []
        if self._reload_state:
            notices = self.restore_reload_state(self._reload_state)
        self._reload_state = None
        self.loading = False
        self.refresh()
        if notices:
            self.status.setText(self.status.text() + ' ' + '；'.join(notices))

    def restore_reload_state(self, state):
        q = state['query']
        frame = self.dataset.frame
        notices = ['已重新加载数据源']
        missing = []
        markets = [self.site.itemData(i) for i in range(self.site.count())]
        if (q.site, q.currency) in markets:
            self.site.setCurrentIndex(markets.index((q.site, q.currency)))
            self.fill(self.currency, [q.currency])
        else:
            missing.append('站点')
        months = [self.start.itemText(i) for i in range(self.start.count())]
        start = next((m for m in months if m >= q.start), months[-1])
        end = months[-1] if q.end == state['latest'] else next((m for m in reversed(months) if m <= q.end), months[0])
        self.start.setCurrentText(min(start, end))
        self.end.setCurrentText(end)
        if end != q.end:
            notices.append('结束月份已更新为 ' + end)
        self.brand.setCurrentIndex(max(0, self.brand.findData(q.brand)))
        if q.brand and self.brand.currentData() != q.brand:
            missing.append('关注品牌')
        self.filters = {}
        for field, values in q.filters.items():
            kept = [v for v in values if field in frame and v in set(frame[field])]
            if kept != values:
                missing.append(field)
            if kept:
                if field == '品类':
                    self.category.setCurrentIndex(self.category.findData(kept[0]))
                else:
                    self.filters[field] = kept
        for field in state['fields']:
            if field not in self.dimensions:
                missing.append(field)
        self.restore_attribute_fields(state['fields'])
        self.group.setCurrentText(q.group if q.group in self.dimensions else '品牌')
        self.metric.setCurrentText(q.metric)
        self.top.setValue(q.top)
        self.price_min.setValue(q.price_min if q.price_min is not None else -1)
        self.price_max.setValue(q.price_max if q.price_max is not None else -1)
        self.search.setText(state['search'])
        if missing:
            notices.append('已移除失效筛选：' + '、'.join(dict.fromkeys(missing)))
        return notices

    def fill_markets(self):
        self.site.clear()
        frame = self.dataset.frame
        for site in sorted(frame['站点'].unique()):
            currencies = sorted(frame.loc[frame['站点'] == site, '币种'].unique())
            for currency in currencies:
                label = site if len(currencies) == 1 else f'{site} ({currency})'
                self.site.addItem(label, (site, currency))
        self.fill(self.currency, [self.site.currentData()[1]])

    def site_changed(self):
        if self.loading or self.dataset is None:
            return
        self.loading = True
        self.fill(self.currency, [self.site.currentData()[1]])
        self.loading = False
        self.refresh()

    def query(self):
        filters = dict(self.filters)
        if self.category.currentData():
            filters['品类'] = [self.category.currentData()]
        return Query(self.start.currentText(), self.end.currentText(), self.site.currentData()[0],
                     self.currency.currentText(), filters, self.brand.currentData() or '',
                     self.group.currentText(), self.metric.currentText(), self.top.value(),
                     None if self.price_min.value() < 0 else self.price_min.value(),
                     None if self.price_max.value() < 0 else self.price_max.value())

    def refresh(self, *_):
        if self.loading or self.dataset is None:
            return
        self.sync_attribute_controls()
        try:
            query = self.query()
            result = analyze(self.dataset, query)
        except Exception as exc:
            self.result = None
            self.export_btn.setEnabled(False)
            self.matrix_btn.setEnabled(False)
            self.scope.setText(str(exc))
            for label in self.kpis.values():
                label.setText('—')
            for chart in (self.ranking, self.trend, self.shares):
                chart.set_data([], [])
            self.model.replace(pd.DataFrame())
            return
        self.result = result
        self.focus = None
        for name, label in self.kpis.items():
            label.setText(f'{name}\n{number(result["kpi"][name], name in ("样本份额", "同比", "上期比", "数据覆盖率"))}')
        self.kpis['同比'].setToolTip(f'{query.metric}与去年相同月份比较；数据不足或基期为 0 时不计算。')
        self.kpis['上期比'].setToolTip(f'{query.metric}与紧邻的前一个等长时间段比较；单月即环比。')
        top = result['top']
        self.ranking.title = f'{query.group}样本份额 · {query.metric}'
        self.ranking.set_data(top['分组'], [(query.metric, top['份额'].tolist())], True)
        trend = result['trend']
        series = [('市场样本', trend['市场数值'].tolist())]
        if query.brand:
            series.append((query.brand, trend['所选品牌数值'].tolist()))
        self.trend.title = f'{query.metric}趋势 · {query.currency if query.metric == "销售额" else "件"}'
        self.trend.set_data(trend['月份'], series)
        shares = result['shares']
        names = result['ranking']['分组'].head(5).tolist()
        self.shares.title = f'{query.group}月度份额 · 期间排名前 5（完整数据可导出）'
        self.shares.set_data(shares['月份'], [(name, shares[name].tolist()) for name in names if name in shares], True)
        notes = f'样本范围：{query.site} / {query.currency} · {query.start} 至 {query.end} · {result["market"]["ASIN"].nunique():,} 个 ASIN。'
        notes += f' 指标：{query.brand or "全部品牌"}；份额分母保留当前市场样本。'
        if result['missing_months']:
            notes += ' 缺失月份：' + '、'.join(result['missing_months']) + '。'
        if self.dataset.available_history:
            coverage = result['coverage']
            notes += f' 已知{query.metric}记录 {coverage["known"]:,}/{coverage["total"]:,}；同比/上期比也受数据覆盖变化影响。'
        self.scope.setText(notes)
        self.scope.setToolTip('\n'.join(self.dataset.notes))
        self.status.setText('按历史已知记录汇总；缺失月份不补零，属性采用主表当前特征。' if self.dataset.available_history else '空白为缺失；同比/上期比需具备对应月份。')
        self.status.setToolTip('\n'.join(self.dataset.notes))
        self.kpis['数据覆盖率'].setToolTip('当前关注范围中，所选指标有数值的 ASIN×月份记录数 ÷ 全部记录数；不代表全市场覆盖率。')
        self.update_detail()
        self.export_btn.setEnabled(True)

    def update_detail(self):
        if self.result is None:
            return
        frame = self.result['detail']
        if self.focus:
            col, values = self.focus
            frame = frame[frame[col].isin(values)]
        columns = list(dict.fromkeys(['月份', 'ASIN', '品牌', '销量', '销售额', '均价', *self.dataset.feature_fields, '品类', '站点', '币种']))
        columns += [c for c in frame.columns if c not in columns]
        self.model.replace(frame[columns])
        self.search_changed(self.search.text())

    def search_changed(self, text):
        self.proxy.setFilterFixedString(text)
        focus = f' · 图表定位：{self.focus[0]}={"、".join(self.focus[1])}' if self.focus else ''
        self.detail_hint.setText(f'当前明细 {self.proxy.rowCount():,} 条（ASIN × 月份）{focus}；搜索和定位只影响明细及矩阵发送。')
        self.matrix_btn.setEnabled(self.proxy.rowCount() > 0 and self.result is not None)

    def drill_group(self, value):
        if self.result is None:
            return
        query = self.query()
        values = [value]
        if value == self.result['others_label'] and len(self.result['ranking']) > query.top:
            values = self.result['ranking'].iloc[query.top:]['分组'].tolist()
            if query.group == '品牌':
                self.brand.setCurrentIndex(0)
        if query.group == '品牌' and len(values) == 1:
            self.brand.setCurrentIndex(self.brand.findData(values[0]))
        self.focus = (query.group, values)
        self.update_detail()
        self.tabs.setCurrentIndex(1)

    def drill_month(self, value):
        self.focus = ('月份', [value])
        self.update_detail()
        self.tabs.setCurrentIndex(1)

    def clear_focus(self):
        self.focus = None
        self.update_detail()

    def reset_filters(self):
        self.loading = True
        self.filters = {}
        self.category.setCurrentIndex(0)
        self.brand.setCurrentIndex(0)
        self.start.setCurrentIndex(0)
        self.end.setCurrentIndex(self.end.count() - 1)
        self.price_min.setValue(-1)
        self.price_max.setValue(-1)
        self.search.clear()
        self.loading = False
        self.refresh()

    def arrange_controls(self):
        cells = self.base_cells + list(self.attribute_cells.values())
        for cell in cells:
            self.control_grid.removeWidget(cell)
        for i, cell in enumerate(cells):
            self.control_grid.addWidget(cell, i // 4, i % 4)
        rows = (len(cells) + 3) // 4
        limit = 62 if self.height() < 550 else 190 if self.height() < 700 else 260
        self.controls_scroll.setFixedHeight(min(limit, rows * 62))

    def remember_attribute_fields(self):
        try:
            self.config_mgr.set('dashboard_filter_fields', list(self.attribute_controls))
        except Exception:
            self.status.setText('属性框已添加；暂时无法保存到本机配置。')

    def restore_attribute_fields(self, fields):
        for cell in self.attribute_cells.values():
            self.control_grid.removeWidget(cell)
            cell.hide()
            cell.deleteLater()
        self.attribute_controls = {}
        self.attribute_cells = {}
        self.add_attribute_fields(fields, remember=False)
        self.arrange_controls()

    def add_attribute_fields(self, fields, remember=True):
        for field in fields:
            if field not in self.dimensions or field in self.attribute_controls or field in ('品牌', '品类'):
                continue
            cell = QWidget()
            box = QVBoxLayout(cell)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(3)
            heading = QHBoxLayout()
            heading.setContentsMargins(0, 0, 0, 0)
            heading.addWidget(QLabel(field), 1)
            remove = QToolButton()
            remove.setText('×')
            remove.setFixedSize(18, 18)
            remove.setAccessibleName('移除' + field)
            remove.setToolTip('移除此属性筛选框')
            remove.clicked.connect(lambda checked=False, key=field: self.remove_attribute_field(key))
            heading.addWidget(remove)
            box.addLayout(heading)
            combo = AttributeCombo(field, sorted(self.dataset.frame[field].unique()))
            combo.set_selected(self.filters.get(field, []))
            combo.selection_changed.connect(lambda values, key=field: self.attribute_changed(key, values))
            box.addWidget(combo)
            self.attribute_controls[field] = combo
            self.attribute_cells[field] = cell
        self.arrange_controls()
        if remember:
            self.remember_attribute_fields()

    def sync_attribute_controls(self):
        missing = [field for field in self.filters if field not in self.attribute_controls]
        if missing:
            self.add_attribute_fields(missing, remember=False)
        for field, combo in self.attribute_controls.items():
            combo.set_selected(self.filters.get(field, []))

    def attribute_changed(self, field, values):
        if values:
            self.filters[field] = values
        else:
            self.filters.pop(field, None)
        self.refresh()

    def remove_attribute_field(self, field):
        cell = self.attribute_cells.pop(field)
        self.control_grid.removeWidget(cell)
        cell.hide()
        cell.deleteLater()
        self.attribute_controls.pop(field)
        self.filters.pop(field, None)
        self.arrange_controls()
        self.refresh()
        self.remember_attribute_fields()

    def add_filter(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('添加属性筛选')
        dialog.resize(440, 480)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel('勾选需要常驻的属性，可一次添加多个。'))
        search = QLineEdit()
        search.setPlaceholderText('搜索属性名称')
        layout.addWidget(search)
        fields = QListWidget()
        for field in self.dimensions:
            if field in ('品牌', '品类') or field in self.attribute_controls:
                continue
            item = QListWidgetItem(field)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            fields.addItem(item)
        layout.addWidget(fields)
        if not fields.count():
            layout.addWidget(QLabel('所有可用属性均已添加，可直接在上方筛选框中修改。'))
        search.textChanged.connect(lambda text: [fields.item(i).setHidden(text.casefold() not in fields.item(i).text().casefold()) for i in range(fields.count())])
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('添加')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            chosen = [fields.item(i).text() for i in range(fields.count()) if fields.item(i).checkState() == Qt.CheckState.Checked]
            self.add_attribute_fields(chosen)

    def visible_frame(self, selected=False):
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()}) if selected else []
        if not rows:
            rows = range(self.proxy.rowCount())
        source = [self.proxy.mapToSource(self.proxy.index(i, 0)).row() for i in rows]
        return self.model.frame.iloc[source].copy()

    def export(self):
        if self.result is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, '导出看板与当前明细', '市场分析看板.xlsx', 'Excel (*.xlsx)')
        if not path:
            return
        if Path(path).resolve() == Path(self.dataset.source).resolve():
            QMessageBox.warning(self, '请选择其他文件', '导出不可覆盖当前源工作簿。')
            return
        try:
            export_report(path, self.dataset, self.query(), self.result, self.visible_frame(),
                          {'明细搜索': self.search.text(), '图表定位': str(self.focus or '无')})
            self.status.setText('已导出：' + Path(path).name)
            self.status.setToolTip(path)
        except Exception as exc:
            QMessageBox.warning(self, '导出失败', str(exc))

    def send_matrix(self):
        if self.result is None:
            return
        try:
            selected = self.visible_frame(selected=True)
            if selected.empty:
                return
            # Selected rows choose ASINs; include every visible month of those ASINs.
            detail = self.visible_frame()
            detail = detail[detail['ASIN'].isin(selected['ASIN'])]
            frame = product_snapshot(detail, self.dataset.available_history)
            directory = Path(self.config_mgr.get_path()).parent / 'dashboard' / 'matrix-inputs'
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f'看板商品-{uuid.uuid4().hex[:12]}.xlsx'
            with pd.ExcelWriter(path, engine='xlsxwriter', engine_kwargs={'options': {'strings_to_formulas': False, 'strings_to_urls': False}}) as writer:
                frame.to_excel(writer, sheet_name='看板商品', index=False)
            self.matrix_requested.emit(str(path))
            self.status.setText(f'已发送 {len(frame)} 个 ASIN 到产品矩阵')
            self.status.setToolTip(str(path))
        except Exception as exc:
            QMessageBox.warning(self, '发送失败', str(exc))

    def save_plan(self):
        path, _ = QFileDialog.getSaveFileName(self, '保存分析方案', '看板方案.json', 'JSON (*.json)')
        if path:
            try:
                Path(path).write_text(json.dumps({'version': 1, 'query': asdict(self.query()), 'attribute_fields': list(self.attribute_controls)}, ensure_ascii=False, indent=2), encoding='utf-8')
                self.status.setText('方案已保存；不包含源数据。')
            except Exception as exc:
                QMessageBox.warning(self, '保存失败', str(exc))

    def load_plan(self):
        path, _ = QFileDialog.getOpenFileName(self, '加载分析方案（先导入工作簿）', '', 'JSON (*.json)')
        if not path:
            return
        try:
            saved = json.loads(Path(path).read_text(encoding='utf-8'))
            if saved.get('version') != 1:
                raise ValueError('不支持的方案版本。')
            q = Query(**saved['query'])
            data = self.dataset.frame
            for column, value in [('月份', q.start), ('月份', q.end), ('站点', q.site), ('币种', q.currency), ('品牌', q.brand)]:
                if value and value not in set(data[column]):
                    raise ValueError(f'当前数据不包含方案中的 {column}={value}')
            for column, values in q.filters.items():
                if column not in data or not set(values).issubset(set(data[column])):
                    raise ValueError(f'方案中的属性筛选与当前数据不匹配：{column}')
            if q.group not in self.dimensions or not 3 <= q.top <= 20:
                raise ValueError('方案分组或 Top N 无效。')
            if q.currency not in set(data.loc[data['站点'] == q.site, '币种']):
                raise ValueError('方案站点下没有该币种。')
            fields = saved.get('attribute_fields', list(q.filters))
            if not isinstance(fields, list) or any(not isinstance(f, str) or f not in self.dimensions for f in fields):
                raise ValueError('方案中的常驻属性与当前数据不匹配。')
            analyze(self.dataset, q)  # Validate everything before changing the UI.
            self.loading = True
            self.site.setCurrentIndex(next(i for i in range(self.site.count()) if self.site.itemData(i) == (q.site, q.currency)))
            self.fill(self.currency, [q.currency])
            for control, value in [(self.start, q.start), (self.end, q.end), (self.currency, q.currency), (self.group, q.group), (self.metric, q.metric)]:
                control.setCurrentText(value)
            self.brand.setCurrentIndex(max(0, self.brand.findData(q.brand)))
            self.category.setCurrentIndex(0)
            self.filters = dict(q.filters)
            categories = self.filters.get('品类', [])
            if len(categories) == 1:
                self.category.setCurrentIndex(self.category.findData(categories[0]))
                self.filters.pop('品类')
            self.restore_attribute_fields(list(dict.fromkeys([*fields, *self.filters])))
            self.top.setValue(q.top)
            self.price_min.setValue(q.price_min if q.price_min is not None else -1)
            self.price_max.setValue(q.price_max if q.price_max is not None else -1)
            self.search.clear()
            self.loading = False
            self.refresh()
            self.remember_attribute_fields()
        except Exception as exc:
            self.loading = False
            QMessageBox.warning(self, '加载方案失败', str(exc))
