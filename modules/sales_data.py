# -*- coding: utf-8 -*-
"""销量数据模块 — 数据清洗、属性分组趋势、市场占比"""

import os
import re
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTabWidget, QFormLayout, QLineEdit,
    QHBoxLayout, QComboBox, QLabel, QCheckBox, QSpinBox, QScrollArea,
    QPlainTextEdit,
)
from PyQt6.QtCore import Qt

from core.widgets import (
    Card, LogConsole, FileDropLineEdit, make_button, configure_combo,
    file_row, set_running_state, make_hint_label,
)

MODULE_INFO = {
    "name": "销量数据",
    "icon": "📊",
    "category": "分析中心",
    "order": 2,
    "description": "数据清洗、属性分组趋势图、市场占比",
}

MAX_CROSS_FILTERS = 10


class ModuleWidget(QWidget):
    def __init__(self, config_mgr, runner):
        super().__init__()
        self.config_mgr = config_mgr
        self.runner = runner
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 20, 28, 24)
        layout.setSpacing(14)
        tabs = QTabWidget()

        # ================= Tab 1: 数据清洗 =================
        tab1 = QWidget()
        t1 = QVBoxLayout(tab1)
        t1.setContentsMargins(0, 0, 0, 0)
        t1.setSpacing(14)

        tab2 = QWidget()
        t2 = QVBoxLayout(tab2)
        t2.setContentsMargins(0, 0, 0, 0)
        t2.setSpacing(14)

        card_split = Card("单文件销量拆分",
                          "选择单个 Excel 文件，按 ASIN/子体拆分销量数据")
        form1 = QFormLayout()
        form1.setSpacing(10)
        self.split_input = FileDropLineEdit(placeholder="选择或拖入销量 Excel 文件")
        form1.addRow("输入文件:", file_row(self.split_input, "open", parent=self))
        self.split_output = FileDropLineEdit(placeholder="留空则使用默认输出路径")
        form1.addRow("输出文件:", file_row(self.split_output, "save", parent=self))
        self.run_btn1 = make_button("执行销量拆分", "primary")
        self.run_btn1.clicked.connect(self._run_split)
        form1.addRow(self.run_btn1)
        card_split.content_layout.addLayout(form1)
        t1.addWidget(card_split)

        card_batch = Card("批量销量拆分",
                          "选择一个文件夹，批量处理其中所有 Excel 文件的销量拆分")
        form1b = QFormLayout()
        form1b.setSpacing(10)
        self.batch_dir = FileDropLineEdit(want_dir=True, placeholder="选择或拖入待处理文件夹")
        form1b.addRow("文件夹:", file_row(self.batch_dir, "dir", parent=self))
        self.run_btn1b = make_button("执行批量拆分", "primary")
        self.run_btn1b.clicked.connect(self._run_batch_split)
        form1b.addRow(self.run_btn1b)
        card_batch.content_layout.addLayout(form1b)
        t1.addWidget(card_batch)

        card_trend = Card(
            "ASIN 历史趋势",
            "直接输入多个 ASIN，跨历史拆分文件生成与交叉属性一致的趋势图和明细数据",
        )
        form2 = QFormLayout()
        form2.setSpacing(10)
        self.trend_folder = FileDropLineEdit(
            want_dir=True, placeholder="选择或拖入历史数据文件夹（含 *_销量拆分.xlsx）")
        form2.addRow("历史数据文件夹:",
                     file_row(self.trend_folder, "dir", parent=self))

        self.trend_second_file = FileDropLineEdit(
            placeholder="可选：补充历史数据的 Excel 文件")
        form2.addRow("第二数据来源:",
                     file_row(self.trend_second_file, "open", parent=self))

        self.trend_volume_sheet = QLineEdit()
        self.trend_volume_sheet.setPlaceholderText("第二数据来源中的销量历史 Sheet")
        form2.addRow("销量数据Sheet:", self.trend_volume_sheet)

        self.trend_revenue_sheet = QLineEdit()
        self.trend_revenue_sheet.setPlaceholderText("第二数据来源中的销额历史 Sheet")
        form2.addRow("销额数据Sheet:", self.trend_revenue_sheet)
        self._trend_volume_sheet_label = form2.labelForField(
            self.trend_volume_sheet)
        self._trend_revenue_sheet_label = form2.labelForField(
            self.trend_revenue_sheet)

        self.trend_asins = QPlainTextEdit()
        self.trend_asins.setPlaceholderText(
            "直接粘贴 ASIN；支持逗号、空格或换行分隔，例如：\n"
            "B00DOMYL24\nB014EKQ5AA\nB09Y8FRMQV")
        self.trend_asins.setFixedHeight(88)
        form2.addRow("ASIN列表:", self.trend_asins)

        self.trend_volume_field = configure_combo(QComboBox())
        self.trend_volume_field.setEditable(True)
        self.trend_volume_field.addItems(["子体销量_矫正", "月销量", "子体销量"])
        form2.addRow("销量字段:", self.trend_volume_field)

        self.trend_revenue_field = configure_combo(QComboBox())
        self.trend_revenue_field.setEditable(True)
        self.trend_revenue_field.addItems(
            ["子体销售额_矫正", "月销售额($)", "子体销售额($)"])
        form2.addRow("销额字段:", self.trend_revenue_field)

        self.trend_mode = configure_combo(QComboBox())
        self.trend_mode.addItems(["销量趋势", "销额趋势", "销量&均价趋势"])
        self.trend_mode.setToolTip(
            "输出逻辑与交叉属性一致；均价按所选 ASIN 的销额合计 ÷ 销量合计计算")
        form2.addRow("趋势模式:", self.trend_mode)
        self.trend_mode_hint = make_hint_label("")
        form2.addRow(self.trend_mode_hint)
        self.trend_mode.currentIndexChanged.connect(self._update_trend_mode_ui)
        self._update_trend_mode_ui(self.trend_mode.currentIndex())

        self.trend_output = FileDropLineEdit(
            placeholder="留空默认：历史数据文件夹同级「规划」文件夹，按 ASIN 组合命名")
        form2.addRow("输出文件:",
                     file_row(self.trend_output, "save", parent=self))

        self.trend_export = FileDropLineEdit(
            placeholder="留空默认：历史数据文件夹同级「规划」文件夹，按 ASIN 组合命名")
        form2.addRow("导出数据:",
                     file_row(self.trend_export, "save", parent=self))

        trend_btn_row = QHBoxLayout()
        trend_btn_row.setSpacing(10)
        self.run_btn2 = make_button("生成趋势图", "primary")
        self.run_btn2.clicked.connect(self._run_trend)
        trend_btn_row.addWidget(self.run_btn2)
        self.export_btn2 = make_button("导出数据")
        self.export_btn2.clicked.connect(self._run_trend_export)
        trend_btn_row.addWidget(self.export_btn2)
        trend_btn_row.addStretch()
        form2.addRow(trend_btn_row)
        card_trend.content_layout.addLayout(form2)
        t2.addWidget(card_trend)
        self.log2 = LogConsole()
        t2.addWidget(self.log2)
        t2.addStretch()

        card_fix = Card(
            "数据修正",
            "修正指定 ASIN + 年月的数据；保存前自动生成时间戳备份，并保留原工作簿结构",
        )
        form_fix = QFormLayout()
        form_fix.setSpacing(10)
        self.fix_folder = FileDropLineEdit(want_dir=True, placeholder="拆分结果所在文件夹")
        form_fix.addRow("拆分文件夹:", file_row(self.fix_folder, "dir", parent=self))

        self.fix_asin = QLineEdit()
        self.fix_asin.setPlaceholderText("如 B00DOMYL24")
        form_fix.addRow("ASIN:", self.fix_asin)

        self.fix_month = QLineEdit()
        self.fix_month.setPlaceholderText("如 2025-03")
        form_fix.addRow("年月:", self.fix_month)

        fix_row = QHBoxLayout()
        fix_row.setSpacing(8)
        self.fix_volume = QLineEdit()
        self.fix_volume.setPlaceholderText("新销量值")
        self.fix_revenue = QLineEdit()
        self.fix_revenue.setPlaceholderText("新销额值（可选）")
        fix_row.addWidget(self.fix_volume)
        fix_row.addWidget(self.fix_revenue)
        form_fix.addRow("修正值:", fix_row)

        self.run_fix = make_button("执行修正", "primary")
        self.run_fix.clicked.connect(self._run_fix)
        form_fix.addRow(self.run_fix)
        card_fix.content_layout.addLayout(form_fix)
        t1.addWidget(card_fix)

        self.log1 = LogConsole()
        t1.addWidget(self.log1)
        t1.addStretch()
        tabs.addTab(tab1, "数据清洗")
        tabs.addTab(tab2, "ASIN趋势")

        # ================= Tab 3: 交叉属性 =================
        tab4 = QWidget()
        t4 = QVBoxLayout(tab4)
        t4.setContentsMargins(0, 0, 0, 0)
        t4.setSpacing(14)

        card4 = Card("交叉属性趋势（多条件筛选）",
                     f"多筛选条件交叉分析，支持 1-{MAX_CROSS_FILTERS} 个条件动态组合，"
                     "可选双轴模式和导出数据")
        form4 = QFormLayout()
        form4.setSpacing(10)

        self.cross_file = FileDropLineEdit(placeholder="选择或拖入 Excel 文件")
        form4.addRow("Excel文件:", file_row(self.cross_file, "open", parent=self))

        self.cross_meta = QLineEdit()
        self.cross_meta.setPlaceholderText("留空默认第一个Sheet")
        form4.addRow("元数据Sheet:", self.cross_meta)

        self.cross_data = QLineEdit()
        self.cross_data.setPlaceholderText("历史数据Sheet名")
        form4.addRow("数据Sheet:", self.cross_data)

        self.cross_data2 = QLineEdit()
        self.cross_data2.setPlaceholderText("如 子体销额（销额模式 / 均价模式 必填）")
        form4.addRow("第二数据Sheet:", self.cross_data2)

        self.cross_trend_mode = configure_combo(QComboBox())
        self.cross_trend_mode.addItems(["销量趋势", "销额趋势", "销量&均价趋势"])
        self.cross_trend_mode.setToolTip(
            "选「销额趋势」或「销量&均价趋势」时需填写第二数据Sheet（销额表），均价=销额/销量")
        form4.addRow("趋势模式:", self.cross_trend_mode)
        self.cross_mode_hint = make_hint_label("")
        form4.addRow(self.cross_mode_hint)
        self._cross_data_label = form4.labelForField(self.cross_data)
        self._cross_data2_label = form4.labelForField(self.cross_data2)
        self.cross_trend_mode.currentIndexChanged.connect(
            self._update_cross_mode_ui)
        self._update_cross_mode_ui(self.cross_trend_mode.currentIndex())

        self.cross_output = FileDropLineEdit(
            placeholder="留空默认: Excel父目录下「规划」文件夹，按筛选值+分组字段命名")
        form4.addRow("输出文件:", file_row(self.cross_output, "save", parent=self))

        self.cross_filter_count = QSpinBox()
        self.cross_filter_count.setRange(1, MAX_CROSS_FILTERS)
        self.cross_filter_count.setValue(2)
        self.cross_filter_count.valueChanged.connect(self._rebuild_filter_rows)
        form4.addRow("筛选条件数:", self.cross_filter_count)

        # 动态筛选条件容器（带滚动条）
        self.cross_filter_container = QWidget()
        self.cross_filter_layout = QFormLayout(self.cross_filter_container)
        self.cross_filter_layout.setContentsMargins(4, 4, 4, 4)
        scroll = QScrollArea()
        scroll.setWidget(self.cross_filter_container)
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(122)
        form4.addRow(scroll)
        self.cross_filter_rows = []
        self._rebuild_filter_rows(2)

        self.cross_export = FileDropLineEdit(
            placeholder="留空默认: Excel父目录下「规划」文件夹，按筛选值+分组字段命名")
        form4.addRow("导出数据:", file_row(self.cross_export, "save", parent=self))

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self.run_btn4 = make_button("生成趋势图", "primary")
        self.run_btn4.clicked.connect(self._run_cross_trend)
        btn_row.addWidget(self.run_btn4)
        self.export_btn4 = make_button("导出数据")
        self.export_btn4.clicked.connect(self._run_cross_export)
        btn_row.addWidget(self.export_btn4)
        btn_row.addStretch()
        form4.addRow(btn_row)
        card4.content_layout.addLayout(form4)
        t4.addWidget(card4)
        self.log4 = LogConsole()
        t4.addWidget(self.log4)
        t4.addStretch()
        tabs.addTab(tab4, "交叉属性")

        # ================= Tab 4: 市场占比 =================
        tab5 = QWidget()
        t5 = QVBoxLayout(tab5)
        t5.setContentsMargins(0, 0, 0, 0)
        t5.setSpacing(14)

        card5 = Card("市场份额趋势图",
                     "按品牌/类别统计月度份额占比趋势，支持 Top N 展示和份额数据导出")
        form5 = QFormLayout()
        form5.setSpacing(10)

        self.share_file = FileDropLineEdit(placeholder="选择或拖入 Excel 文件")
        form5.addRow("Excel文件:", file_row(self.share_file, "open", parent=self))

        self.share_meta = QLineEdit()
        self.share_meta.setPlaceholderText("留空默认第一个Sheet")
        form5.addRow("元数据Sheet:", self.share_meta)

        self.share_data = QLineEdit()
        self.share_data.setPlaceholderText("历史销量Sheet名")
        form5.addRow("数据Sheet:", self.share_data)

        self.share_brand_col = QLineEdit()
        self.share_brand_col.setPlaceholderText("如: 品牌、线长、颜色、使用场景")
        form5.addRow("分组列名:", self.share_brand_col)

        self.share_top = QSpinBox()
        self.share_top.setRange(2, 20)
        self.share_top.setValue(8)
        form5.addRow("展示Top N:", self.share_top)

        self.share_filter = QLineEdit()
        self.share_filter.setPlaceholderText("格式: 列名=值（可选，多个用 ; 分隔）")
        form5.addRow("筛选条件:", self.share_filter)

        self.share_output = FileDropLineEdit(placeholder="输出图片路径（可选）")
        form5.addRow("输出文件:",
                     file_row(self.share_output, "save",
                              filter_str="PNG (*.png)", parent=self))

        self.share_dpi = QSpinBox()
        self.share_dpi.setRange(72, 400)
        self.share_dpi.setValue(200)
        form5.addRow("DPI:", self.share_dpi)

        self.share_export = QCheckBox("同时输出占比数据表（Excel格式）")
        form5.addRow(self.share_export)

        self.run_btn5 = make_button("生成市场占比图", "primary")
        self.run_btn5.clicked.connect(self._run_brand_share)
        form5.addRow(self.run_btn5)
        card5.content_layout.addLayout(form5)
        t5.addWidget(card5)
        self.log5 = LogConsole()
        t5.addWidget(self.log5)
        t5.addStretch()
        tabs.addTab(tab5, "市场占比")

        layout.addWidget(tabs)

    # ================================================================
    # 脚本执行（业务逻辑保持不变）
    # ================================================================

    def _run(self, script, log_area, args=None, run_btn=None):
        """统一执行入口。"""
        if self.runner.is_running() or self.runner.is_any_running():
            log_area.append("[提示] 当前有任务正在运行，请等待完成。")
            return False
        log_area.clear()
        try:
            self.runner.log_signal.disconnect()
        except TypeError:
            pass
        try:
            self.runner.finished_signal.disconnect()
        except TypeError:
            pass
        self.runner.log_signal.connect(log_area.append)

        def _done(code):
            log_area.append(f"\n[完成] 退出码: {code}")
            log_area.set_status("ok" if code == 0 else "error")
            if run_btn is not None:
                set_running_state(run_btn, False)

        self.runner.finished_signal.connect(_done)
        if run_btn is not None:
            set_running_state(run_btn, True)
        log_area.set_status("running")
        script_path = os.path.join(self.config_mgr.get_script_dir(), script)
        return self.runner.run_script(
            script_path, args, self.config_mgr.get_env_dict()
        )

    def _run_split(self):
        inp = self.split_input.text().strip()
        out = self.split_output.text().strip()
        if not inp:
            self.log1.append("[提示] 请先选择「输入文件」")
            return
        args = [inp]
        if out:
            args.append(out)
        self._run("sales_number.py", self.log1, args, run_btn=self.run_btn1)

    def _run_batch_split(self):
        d = self.batch_dir.text().strip()
        if not d:
            self.log1.append("[提示] 请先选择要批量处理的「文件夹」")
            return
        self._run("batch_sales_split.py", self.log1, [d, "--yes"], run_btn=self.run_btn1b)

    @staticmethod
    def _parse_asin_input(text):
        """解析逗号、空格、分号或换行分隔的 ASIN，并按输入顺序去重。"""
        tokens = re.split(r"[\s,，;；]+", text or "")
        result = []
        seen = set()
        for token in tokens:
            token = token.strip()
            if not token:
                continue
            if ":" in token:
                asin, label = token.split(":", 1)
                token = f"{asin.strip().upper()}:{label.strip()}"
                key = asin.strip().upper()
            else:
                token = token.upper()
                key = token
            if key and key not in seen:
                seen.add(key)
                result.append(token)
        return result

    def _trend_default_path(self, ext, folder=None, asins=None):
        """生成与交叉属性一致的 ASIN 组合默认输出路径。"""
        folder = folder or self.trend_folder.text().strip()
        second_file = self.trend_second_file.text().strip()
        if not folder and not second_file:
            return ""
        asin_names = [item.split(":", 1)[0] for item in (asins or [])]
        shown = asin_names[:3]
        source_name = "_".join(shown)
        if len(asin_names) > 3:
            source_name += f"_等{len(asin_names)}个"

        stem = self._sanitize_filename(source_name) or "ASIN趋势"
        if folder:
            base_dir = os.path.dirname(os.path.abspath(folder))
        else:
            base_dir = os.path.dirname(os.path.abspath(second_file))
        output_dir = os.path.join(base_dir, "规划")
        return os.path.join(output_dir, f"{stem}{ext}")

    def _update_trend_mode_ui(self, index):
        if index == 0:
            self._trend_volume_sheet_label.setText("销量数据Sheet *:")
            self._trend_revenue_sheet_label.setText("销额数据Sheet:")
            hint = "销量趋势使用销量字段；启用第二数据来源时需填写销量数据Sheet。"
        elif index == 1:
            self._trend_volume_sheet_label.setText("销量数据Sheet:")
            self._trend_revenue_sheet_label.setText("销额数据Sheet *:")
            hint = "销额趋势使用销额字段；启用第二数据来源时需填写销额数据Sheet。"
        else:
            self._trend_volume_sheet_label.setText("销量数据Sheet *:")
            self._trend_revenue_sheet_label.setText("销额数据Sheet *:")
            hint = ("销量与均价双轴趋势使用两个来源字段；启用第二数据来源时需填写"
                    "两个 Sheet，均价按销额合计 ÷ 销量合计计算。")
        self.trend_mode_hint.setText(hint)

    def _trend_base_args(self, require_both=False):
        """校验 ASIN 历史输入并返回公共脚本参数；失败时返回 None。"""
        folder = self.trend_folder.text().strip()
        second_file = self.trend_second_file.text().strip()
        if not folder and not second_file:
            self.log2.append("[提示] 请至少选择「历史数据文件夹」或「第二数据来源」")
            return None
        asins = self._parse_asin_input(self.trend_asins.toPlainText())
        if not asins:
            self.log2.append("[提示] 请直接输入至少一个 ASIN")
            return None

        volume_field = self.trend_volume_field.currentText().strip()
        revenue_field = self.trend_revenue_field.currentText().strip()
        mode_index = self.trend_mode.currentIndex()
        if (require_both or mode_index in (0, 2)) and not volume_field:
            self.log2.append("[提示] 请选择或填写「销量字段」")
            return None
        if (require_both or mode_index in (1, 2)) and not revenue_field:
            self.log2.append("[提示] 请选择或填写「销额字段」")
            return None

        volume_sheet = self.trend_volume_sheet.text().strip()
        revenue_sheet = self.trend_revenue_sheet.text().strip()
        if second_file:
            if (require_both or mode_index in (0, 2)) and not volume_sheet:
                self.log2.append("[提示] 第二数据来源需要填写「销量数据Sheet」")
                return None
            if (require_both or mode_index in (1, 2)) and not revenue_sheet:
                self.log2.append("[提示] 第二数据来源需要填写「销额数据Sheet」")
                return None

        mode = ("volume", "revenue", "volume-price")[mode_index]
        args = ["--mode", mode,
                "--volume-field", volume_field,
                "--revenue-field", revenue_field]
        if folder:
            args += ["--folder", folder]
        if second_file:
            args += ["--second-file", second_file]
            if volume_sheet:
                args += ["--volume-sheet", volume_sheet]
            if revenue_sheet:
                args += ["--revenue-sheet", revenue_sheet]
        args += ["--asins", ",".join(asins)]
        return args, folder, asins

    def _run_trend(self):
        prepared = self._trend_base_args()
        if not prepared:
            return
        args, folder, asins = prepared
        output_chart = self.trend_output.text().strip() or \
            self._trend_default_path(".png", folder, asins)
        args += ["--chart", output_chart, "--no-table"]
        self._run("extract_asin_trend.py", self.log2, args, run_btn=self.run_btn2)

    def _run_trend_export(self):
        prepared = self._trend_base_args(require_both=True)
        if not prepared:
            return
        args, folder, asins = prepared
        output_xlsx = self.trend_export.text().strip() or \
            self._trend_default_path(".xlsx", folder, asins)
        args += ["--export-data", output_xlsx, "--export-only", "--no-table"]
        self._run("extract_asin_trend.py", self.log2, args,
                  run_btn=self.export_btn2)

    def _rebuild_filter_rows(self, count):
        """根据筛选条件数量重建输入行。"""
        previous_values = [
            (col_edit.text(), val_edit.text())
            for col_edit, val_edit in getattr(self, "cross_filter_rows", [])
        ]
        for row_widget, _, _ in getattr(self, '_cross_row_widgets', []):
            row_widget.setParent(None)
            row_widget.deleteLater()
        self.cross_filter_rows = []
        self._cross_row_widgets = []
        for i in range(count):
            col_edit = QLineEdit()
            col_edit.setPlaceholderText("属性列名")
            eq_label = QLabel("=")
            eq_label.setFixedWidth(16)
            eq_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            val_edit = QLineEdit()
            val_edit.setPlaceholderText("具体值，多值用英文逗号分隔（留空=按此分组）")
            if i < len(previous_values):
                col_edit.setText(previous_values[i][0])
                val_edit.setText(previous_values[i][1])
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 2, 0, 2)
            row_layout.setSpacing(6)
            row_layout.addWidget(QLabel(f"条件 {i+1}:"))
            row_layout.addWidget(col_edit, stretch=1)
            row_layout.addWidget(eq_label)
            row_layout.addWidget(val_edit, stretch=1)
            self.cross_filter_layout.addRow(row_widget)
            self.cross_filter_rows.append((col_edit, val_edit))
            self._cross_row_widgets.append((row_widget, col_edit, val_edit))

    def _update_cross_mode_ui(self, index):
        """按趋势模式标明必填 Sheet，同时保留两字段供数据导出使用。"""
        if index == 0:
            self._cross_data_label.setText("数据Sheet *:")
            self._cross_data2_label.setText("第二数据Sheet:")
            self.cross_data.setPlaceholderText("销量历史数据 Sheet（必填）")
            self.cross_data2.setPlaceholderText("销额 Sheet（导出数据时需要）")
            hint = "销量趋势使用数据Sheet；第二数据Sheet仅在导出组合数据时需要。"
        elif index == 1:
            self._cross_data_label.setText("数据Sheet:")
            self._cross_data2_label.setText("第二数据Sheet *:")
            self.cross_data.setPlaceholderText("销量 Sheet（导出数据时需要）")
            self.cross_data2.setPlaceholderText("销额历史数据 Sheet（必填）")
            hint = "销额趋势使用第二数据Sheet；数据Sheet仅在导出组合数据时需要。"
        else:
            self._cross_data_label.setText("数据Sheet *:")
            self._cross_data2_label.setText("第二数据Sheet *:")
            self.cross_data.setPlaceholderText("销量历史数据 Sheet（必填）")
            self.cross_data2.setPlaceholderText("销额历史数据 Sheet（必填）")
            hint = "销量与均价趋势需要两个 Sheet，均价按销额 ÷ 销量计算。"
        self.cross_mode_hint.setText(hint)

    @staticmethod
    def _sanitize_filename(name):
        """清除 Windows 文件名非法字符，避免默认命名无法保存。"""
        for ch in '<>:"/\\|?*':
            name = name.replace(ch, '_')
        return name.strip().strip('.')

    def _cross_default_path(self, ext):
        """默认输出路径: 有值取筛选值，值留空时取分组字段名。"""
        f = self.cross_file.text().strip()
        if not f:
            return ""
        parts = []
        for col_edit, val_edit in self.cross_filter_rows:
            col = col_edit.text().strip()
            if not col:
                continue
            val = val_edit.text().strip()
            if val:
                parts.append(val)
            else:
                # 值留空表示按该列分组；保留列名可避免不同分组图重名覆盖。
                parts.append(col)
        name = self._sanitize_filename("_".join(parts)) or "交叉属性"
        folder = os.path.join(os.path.dirname(os.path.abspath(f)), "规划")
        return os.path.join(folder, f"{name}{ext}")

    def _run_cross_trend(self):
        f = self.cross_file.text().strip()
        ds = self.cross_data.text().strip()
        ds2 = self.cross_data2.text().strip()
        mode = self.cross_trend_mode.currentIndex()  # 0=销量, 1=销额, 2=销量&销额
        if not f:
            self.log4.append("[提示] 请先选择「Excel文件」")
            return
        if mode == 0:  # 销量趋势
            if not ds:
                self.log4.append("[提示] 请填写「数据Sheet」名称")
                return
            args = ["--file", f, "--data-sheet", ds, "--chart-type", "line"]
        elif mode == 1:  # 销额趋势
            if not ds2:
                self.log4.append("错误: 销额趋势需要填写第二数据Sheet（销额数据表）")
                return
            args = ["--file", f, "--data-sheet", ds2, "--chart-type", "line"]
        else:  # 销量&均价趋势（双轴）
            if not ds or not ds2:
                self.log4.append("错误: 双轴模式需要填写数据Sheet和第二数据Sheet")
                return
            args = ["--file", f, "--data-sheet", ds, "--data-sheet-2", ds2,
                    "--avg-price-only", "--chart-type", "line"]
        ms = self.cross_meta.text().strip()
        if ms:
            args += ["--meta-sheet", ms]
        group_col = ""
        for col_edit, val_edit in self.cross_filter_rows:
            col = col_edit.text().strip()
            val = val_edit.text().strip()
            if col and val:
                args += ["--filter", f"{col}={val}"]
            elif col and not val:
                group_col = col
        if group_col:
            args += ["--group-col", group_col]
        out = self.cross_output.text().strip() or self._cross_default_path(".png")
        if out:
            args += ["--output", out]
        self._run("trend_by_attribute.py", self.log4, args, run_btn=self.run_btn4)

    def _run_cross_export(self):
        """导出交叉属性数据。"""
        f = self.cross_file.text().strip()
        ds = self.cross_data.text().strip()
        ds2 = self.cross_data2.text().strip()
        export_path = self.cross_export.text().strip() or self._cross_default_path(".xlsx")

        if not f or not ds or not ds2 or not export_path:
            self.log4.append("错误: 导出数据需要填写 Excel文件、数据Sheet 和 第二数据Sheet")
            return

        args = ["--file", f, "--data-sheet", ds, "--data-sheet-2", ds2]
        ms = self.cross_meta.text().strip()
        if ms:
            args += ["--meta-sheet", ms]
        group_col = ""
        for col_edit, val_edit in self.cross_filter_rows:
            col = col_edit.text().strip()
            val = val_edit.text().strip()
            if col and val:
                args += ["--filter", f"{col}={val}"]
            elif col and not val:
                group_col = col
        if group_col:
            args += ["--group-col", group_col]
        args += ["--export-data", export_path, "--export-only"]
        self._run("trend_by_attribute.py", self.log4, args, run_btn=self.export_btn4)

    def _run_fix(self):
        folder = self.fix_folder.text().strip()
        asin = self.fix_asin.text().strip()
        month = self.fix_month.text().strip()
        volume = self.fix_volume.text().strip()
        revenue = self.fix_revenue.text().strip()

        if not folder or not asin or not month:
            self.log1.append("[提示] 请填写「拆分文件夹」「ASIN」「年月」")
            return
        if not volume and not revenue:
            self.log1.append("[提示] 请至少填写「新销量值」或「新销额值」")
            return

        args = ["--folder", folder, "--asin", asin, "--month", month]
        if volume:
            args += ["--volume", volume]
        if revenue:
            args += ["--revenue", revenue]
        self._run("fix_sales_data.py", self.log1, args, run_btn=self.run_fix)

    def _run_brand_share(self):
        f = self.share_file.text().strip()
        ms = self.share_meta.text().strip()
        ds = self.share_data.text().strip()
        bc = self.share_brand_col.text().strip()
        if not f or not ds or not bc:
            self.log5.append("[提示] 请完整填写「Excel文件」「数据Sheet」「分组列名」（元数据Sheet留空默认第一个）")
            return
        args = ["--file", f, "--meta-sheet", ms, "--data-sheet", ds, "--brand-col", bc]
        top = self.share_top.value()
        if top != 8:
            args += ["--top", str(top)]
        filter_text = self.share_filter.text().strip()
        if filter_text:
            for expr in filter_text.split(';'):
                expr = expr.strip()
                if expr:
                    args += ["--filter", expr]
        out = self.share_output.text().strip()
        if out:
            args += ["--output", out]
        dpi = self.share_dpi.value()
        if dpi != 200:
            args += ["--dpi", str(dpi)]
        if self.share_export.isChecked():
            args += ["--export-share"]
        self._run("brand_share_trend.py", self.log5, args, run_btn=self.run_btn5)
