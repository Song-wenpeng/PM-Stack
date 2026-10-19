# -*- coding: utf-8 -*-
"""产品矩阵模块 — 使用场景矩阵、销额透视矩阵、品牌×分类图片矩阵"""

import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTabWidget, QFormLayout, QLineEdit,
    QComboBox,
)

from core.widgets import (
    Card, LogConsole, FileDropLineEdit, make_button, configure_combo,
    file_row, set_running_state, ScrollTabs, collapsible_log, action_row,
)

from core.task_ui import register_form, pin_actions, validated, advanced_rows, mark_required
from core.excel_choices import ChoiceEdit, ExcelChoices

MODULE_INFO = {
    "name": "产品矩阵",
    "icon": "🧩",
    "category": "市场与产品规划",
    "order": 4,
    "description": "使用场景矩阵、销额透视矩阵、品牌×分类图片矩阵",
}


class ModuleWidget(QWidget):
    def __init__(self, config_mgr, runner):
        super().__init__()
        self.setProperty("workspacePage", True)
        self.config_mgr = config_mgr
        self.runner = runner
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 20, 28, 24)
        layout.setSpacing(14)
        tabs = ScrollTabs()

        # ================= Tab 1: 使用场景矩阵 =================
        tab5 = QWidget()
        t5 = QVBoxLayout(tab5)
        t5.setContentsMargins(0, 0, 0, 0)
        t5.setSpacing(14)
        card5 = Card("使用场景矩阵（主图嵌入）",
                     "从 Excel 读取 ASIN/主图/上架时间，按使用场景分列生成可视化产品矩阵，支持图片嵌入")
        form5 = QFormLayout()
        form5.setSpacing(10)

        self.matrix_file = FileDropLineEdit(placeholder="选择或拖入源 Excel 文件")
        form5.addRow("源Excel:", file_row(self.matrix_file, "open", parent=self))

        self.matrix_sheet = ChoiceEdit()
        self.matrix_sheet.setPlaceholderText("含 ASIN、商品主图、上架时间 的 Sheet 名")
        form5.addRow("源数据Sheet:", self.matrix_sheet)

        self.matrix_brand_col = ChoiceEdit("使用场景")
        form5.addRow("分组列名:", self.matrix_brand_col)

        self.matrix_brands = QLineEdit()
        self.matrix_brands.setPlaceholderText("逗号分隔，留空=全部")
        form5.addRow("目标值:", self.matrix_brands)

        self.matrix_output = FileDropLineEdit(placeholder="输出 Excel 文件路径")
        form5.addRow("输出文件:", file_row(self.matrix_output, "save", parent=self))

        self.run_btn5 = make_button("生成使用场景矩阵", "primary")
        self.run_btn5.clicked.connect(self._run_matrix)
        register_form(form5)
        card5.content_layout.addLayout(form5)
        t5.addWidget(card5)
        self.matrix_log = LogConsole()
        collapsible_log(t5, self.matrix_log)
        t5.addStretch()
        tabs.addTab(pin_actions(tab5, self.run_btn5), "使用场景矩阵")
        tabs.setTabToolTip(tabs.count() - 1,
            "按「使用场景」分列，嵌入商品主图+ASIN+上架时间的可视化矩阵")

        # ================= Tab 2: 销额透视矩阵 =================
        tab6 = QWidget()
        t6 = QVBoxLayout(tab6)
        t6.setContentsMargins(0, 0, 0, 0)
        t6.setSpacing(14)
        card6 = Card("销额透视矩阵（双维交叉）",
                     "按两个维度交叉分析，生成销额数据透视表。可从元数据列取值或子表格指定月份列取值")
        form6 = QFormLayout()
        form6.setSpacing(10)

        self.matrix2_file = FileDropLineEdit(placeholder="选择或拖入 Excel 文件")
        form6.addRow("Excel文件:", file_row(self.matrix2_file, "open", parent=self))

        self.matrix2_sheet = ChoiceEdit()
        self.matrix2_sheet.setPlaceholderText("Sheet 名称")
        form6.addRow("Sheet名称:", self.matrix2_sheet)

        self.matrix2_filter = QLineEdit()
        self.matrix2_filter.setPlaceholderText("格式: 列名=值（可选，多个用 ; 分隔）")
        form6.addRow("筛选条件:", self.matrix2_filter)

        self.matrix2_row_col = ChoiceEdit()
        self.matrix2_row_col.setPlaceholderText("如: 三级分类")
        form6.addRow("纵向维度:", self.matrix2_row_col)

        self.matrix2_row_values = QLineEdit()
        self.matrix2_row_values.setPlaceholderText("逗号分隔，留空=全部")
        form6.addRow("纵向维度值:", self.matrix2_row_values)

        self.matrix2_col_col = ChoiceEdit()
        self.matrix2_col_col.setPlaceholderText("如: 插孔布局、有无USB")
        form6.addRow("横向维度:", self.matrix2_col_col)

        self.matrix2_col_values = QLineEdit()
        self.matrix2_col_values.setPlaceholderText("逗号分隔，留空=全部")
        form6.addRow("横向维度值:", self.matrix2_col_values)

        self.matrix2_value_col = ChoiceEdit()
        self.matrix2_value_col.setPlaceholderText("方式一：直接从元数据取值")
        form6.addRow("销额列名:", self.matrix2_value_col)

        self.matrix2_data_sheet = ChoiceEdit()
        self.matrix2_data_sheet.setPlaceholderText("方式二：子表格名（如 子体销额）")
        form6.addRow("数据子表格:", self.matrix2_data_sheet)

        self.matrix2_month_col = ChoiceEdit()
        self.matrix2_month_col.setPlaceholderText("月份列名（如 2025-12）")
        form6.addRow("月份列:", self.matrix2_month_col)

        self.matrix2_output = FileDropLineEdit(placeholder="输出 Excel 文件路径")
        form6.addRow("输出文件:", file_row(self.matrix2_output, "save", parent=self))

        self.run_btn6 = make_button("生成销额透视矩阵", "primary")
        self.run_btn6.clicked.connect(self._run_matrix2)
        register_form(form6)
        card6.content_layout.addLayout(form6)
        t6.addWidget(card6)
        self.matrix2_log = LogConsole()
        collapsible_log(t6, self.matrix2_log)
        t6.addStretch()
        tabs.addTab(pin_actions(tab6, self.run_btn6), "销额透视矩阵")
        tabs.setTabToolTip(tabs.count() - 1,
            "按两个维度交叉生成销额透视表，单元格显示销额总和/ASIN数/平均销额")

        # ================= Tab 3: 品牌×分类矩阵 =================
        tab7 = QWidget()
        t7 = QVBoxLayout(tab7)
        t7.setContentsMargins(0, 0, 0, 0)
        t7.setSpacing(14)
        card7 = Card("品牌 × 分类 图片矩阵",
                     "以品牌为列、三级分类为行，自适应行数，每个单元格嵌入主图+ASIN+属性。支持变体合并")
        form7 = QFormLayout()
        form7.setSpacing(10)

        self.m3_file = FileDropLineEdit(placeholder="选择或拖入 Excel 文件")
        form7.addRow("Excel文件:", file_row(self.m3_file, "open", parent=self))

        self.m3_sheet = ChoiceEdit()
        self.m3_sheet.setPlaceholderText("Sheet 名称")
        form7.addRow("Sheet名称:", self.m3_sheet)

        self.m3_filter = QLineEdit()
        self.m3_filter.setPlaceholderText("格式: 列名=值（可选，多个用 ; 分隔）")
        form7.addRow("筛选条件:", self.m3_filter)

        self.m3_cat_col = ChoiceEdit("三级分类")
        form7.addRow("分类列名:", self.m3_cat_col)

        self.m3_cat_vals = QLineEdit()
        self.m3_cat_vals.setPlaceholderText("逗号分隔，留空=全部")
        form7.addRow("分类值:", self.m3_cat_vals)

        self.m3_brand_col = ChoiceEdit("品牌")
        form7.addRow("品牌列名:", self.m3_brand_col)

        self.m3_brands = QLineEdit()
        self.m3_brands.setPlaceholderText("逗号分隔，必填")
        form7.addRow("目标品牌:", self.m3_brands)

        self.m3_image_col = ChoiceEdit("商品主图")
        form7.addRow("图片列名:", self.m3_image_col)

        self.m3_asin_col = ChoiceEdit("ASIN")
        form7.addRow("ASIN列名:", self.m3_asin_col)

        self.m3_attrs = QLineEdit()
        self.m3_attrs.setPlaceholderText("逗号分隔，如: 插孔布局,额定功率,价格")
        form7.addRow("属性列:", self.m3_attrs)

        self.m3_sort_col = ChoiceEdit()
        self.m3_sort_col.setPlaceholderText("留空=按ASIN排序")
        form7.addRow("排序列:", self.m3_sort_col)

        self.m3_sort_order = configure_combo(QComboBox())
        self.m3_sort_order.addItems(["升序", "降序"])
        self.m3_sort_order.setEnabled(False)
        self.m3_sort_order.setToolTip("填写排序列后可选择排序方式")
        self.m3_sort_col.textChanged.connect(self._update_sort_order_state)
        form7.addRow("排序方式:", self.m3_sort_order)

        self.m3_parent_asin = ChoiceEdit()
        self.m3_parent_asin.setPlaceholderText("留空=不合并变体")
        form7.addRow("父ASIN列:", self.m3_parent_asin)

        self.m3_sales_col = ChoiceEdit()
        self.m3_sales_col.setPlaceholderText("选销量最高变体为代表，启用合并时必填")
        form7.addRow("销量列:", self.m3_sales_col)

        self.m3_variant_cols = QLineEdit()
        self.m3_variant_cols.setPlaceholderText("逗号分隔，如: 线长,颜色")
        form7.addRow("变体属性列:", self.m3_variant_cols)

        self.m3_launch_date_col = ChoiceEdit()
        self.m3_launch_date_col.setPlaceholderText("用于提取年份汇总，如: 上架时间")
        form7.addRow("上架时间列:", self.m3_launch_date_col)

        self.m3_output = FileDropLineEdit(placeholder="输出 Excel 文件路径")
        form7.addRow("输出文件:", file_row(self.m3_output, "save", parent=self))

        self.run_btn7 = make_button("生成品牌×分类矩阵", "primary")
        self.run_btn7.clicked.connect(self._run_matrix3)
        register_form(form7)
        card7.content_layout.addLayout(form7)
        t7.addWidget(card7)
        self.m3_log = LogConsole()
        collapsible_log(t7, self.m3_log)
        t7.addStretch()
        tabs.addTab(pin_actions(tab7, self.run_btn7), "品牌×分类矩阵")
        tabs.setTabToolTip(tabs.count() - 1,
            "以品牌为列、三级分类为行，单元格嵌入主图+ASIN+属性，支持变体合并")

        self.matrix_advanced_toggle = advanced_rows(form7, 9, 15, '卡片属性、排序与变体合并')
        from core.widgets import make_hint_label
        self.matrix_options_hint = make_hint_label('')
        form7.insertRow(9, self.matrix_options_hint)
        for field in (self.m3_attrs, self.m3_sort_col, self.m3_parent_asin, self.m3_variant_cols):
            field.textChanged.connect(self._update_matrix_options)
        self.m3_sort_order.currentIndexChanged.connect(self._update_matrix_options)
        self._update_matrix_options()
        self._excel_choices = [
            ExcelChoices(self.matrix_file, [self.matrix_sheet], [(self.matrix_brand_col, self.matrix_sheet)], self),
            ExcelChoices(self.matrix2_file, [self.matrix2_sheet, self.matrix2_data_sheet],
                         [(f, self.matrix2_sheet) for f in (self.matrix2_row_col, self.matrix2_col_col, self.matrix2_value_col)]
                         + [(self.matrix2_month_col, self.matrix2_data_sheet)], self),
            ExcelChoices(self.m3_file, [self.m3_sheet], [(f, self.m3_sheet) for f in
                         (self.m3_cat_col, self.m3_brand_col, self.m3_image_col, self.m3_asin_col,
                          self.m3_sort_col, self.m3_parent_asin, self.m3_sales_col, self.m3_launch_date_col)], self),
        ]
        for field in (self.matrix_file, self.matrix_sheet, self.matrix_output,
                      self.matrix2_file, self.matrix2_sheet, self.matrix2_row_col, self.matrix2_col_col,
                      self.m3_file, self.m3_sheet, self.m3_brands):
            mark_required(field)
        self._result_sources = {
            self.run_btn5: lambda: self.matrix_output.text(),
            self.run_btn6: lambda: self.matrix2_output.text() or 'product_matrix.xlsx',
            self.run_btn7: lambda: self.m3_output.text() or 'product_matrix3.xlsx',
        }
        layout.addWidget(tabs)
        from core.matrix_workspace import MatrixWorkspace
        self.free_matrix = MatrixWorkspace(self)
        tabs.addTab(self.free_matrix, "自由组合矩阵")

    def _update_matrix_options(self, *_):
        attrs = [x for x in self.m3_attrs.text().split(',') if x.strip()]
        sort = self.m3_sort_col.text().strip()
        self.matrix_options_hint.setText(
            f'附加属性：{len(attrs)} 项 · 排序：{sort or "ASIN"}'
            f'{"（降序）" if sort and self.m3_sort_order.currentIndex() == 1 else "（升序）"} · '
            f'变体合并：{"开启" if self.m3_parent_asin.text().strip() else "关闭"}')

    def _update_sort_order_state(self, text):
        enabled = bool(text.strip())
        self.m3_sort_order.setEnabled(enabled)
        self.m3_sort_order.setToolTip(
            "" if enabled else "填写排序列后可选择排序方式")

    # ================================================================
    # 脚本执行（业务逻辑保持不变）
    # ================================================================

    def _run(self, script, log_area, args=None, env_overrides=None, run_btn=None):
        """矩阵类脚本统一执行入口。"""
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
        bar = getattr(run_btn, '_task_bar', None)
        if bar is not None:
            output = self._result_sources[run_btn]().strip()
            bar.begin([output], os.path.dirname(os.path.abspath(output)))
            self.runner.log_signal.connect(bar.observe)

        def _done(code):
            log_area.append('处理完成' if code == 0 else f'处理失败（错误码 {code}），请查看上方日志。')
            if bar is not None:
                bar.finish(code)
            log_area.set_status("ok" if code == 0 else "error")
            if run_btn is not None:
                set_running_state(run_btn, False)

        self.runner.finished_signal.connect(_done)
        if run_btn is not None:
            set_running_state(run_btn, True)
        log_area.set_status("running")

        script_path = os.path.join(self.config_mgr.get_script_dir(), script)
        if env_overrides is not None:
            full_env = self.config_mgr.get_env_dict()
            full_env.update(env_overrides)
            return self.runner.run_script(script_path, env_extra=full_env)
        else:
            return self.runner.run_script(script_path, args)

    @validated(lambda s: [(s.matrix_file, '源 Excel 文件'), (s.matrix_sheet, '源数据 Sheet'), (s.matrix_output, '输出文件')], "run_btn5")
    def _run_matrix(self):
        f = self.matrix_file.text().strip()
        s = self.matrix_sheet.text().strip()
        o = self.matrix_output.text().strip()
        if not f or not s:
            self.matrix_log.setPlainText("请填写源 Excel 文件和源数据 Sheet。")
            return
        if not o:
            self.matrix_log.setPlainText("请指定输出文件路径。")
            return

        env = {
            "MATRIX_EXCEL_FILE": f,
            "MATRIX_SOURCE_SHEET": s,
            "MATRIX_OUTPUT_FILE": o,
            "MATRIX_BRAND_COL": self.matrix_brand_col.text().strip() or "使用场景",
            "MATRIX_TARGET_BRANDS": self.matrix_brands.text().strip(),
        }
        self._run("product_matrix.py", self.matrix_log,
                  env_overrides=env, run_btn=self.run_btn5)

    @validated(lambda s: [(s.matrix2_file, 'Excel 文件'), (s.matrix2_sheet, 'Sheet 名称'), (s.matrix2_row_col, '纵向维度'), (s.matrix2_col_col, '横向维度')] + ([(s.matrix2_value_col, '销额列名，或填写数据子表格和月份列')] if not (s.matrix2_data_sheet.text().strip() and s.matrix2_month_col.text().strip()) else []), "run_btn6")
    def _run_matrix2(self):
        """运行产品矩阵2（销额数据版）。"""
        f = self.matrix2_file.text().strip()
        s = self.matrix2_sheet.text().strip()
        row_col = self.matrix2_row_col.text().strip()
        col_col = self.matrix2_col_col.text().strip()
        value_col = self.matrix2_value_col.text().strip()
        o = self.matrix2_output.text().strip()

        data_sheet = self.matrix2_data_sheet.text().strip()
        month_col = self.matrix2_month_col.text().strip()
        use_data_sheet = bool(data_sheet and month_col)

        if not f or not s:
            self.matrix2_log.setPlainText("请填写 Excel 文件和 Sheet 名称。")
            return
        if not row_col or not col_col:
            self.matrix2_log.setPlainText("请填写纵向维度列名和横向维度列名。")
            return
        if not use_data_sheet and not value_col:
            self.matrix2_log.setPlainText("请填写销额列名，或填写数据子表格+月份列。")
            return

        args = ["--file", f, "--sheet", s]

        filter_text = self.matrix2_filter.text().strip()
        if filter_text:
            for expr in filter_text.split(';'):
                expr = expr.strip()
                if expr:
                    args += ["--filter", expr]

        args += ["--row-col", row_col]
        row_values = self.matrix2_row_values.text().strip()
        if row_values:
            args += ["--row-values", row_values]

        args += ["--col-col", col_col]
        col_values = self.matrix2_col_values.text().strip()
        if col_values:
            args += ["--col-values", col_values]

        if use_data_sheet:
            args += ["--data-sheet", data_sheet, "--month-col", month_col]
        if value_col:
            args += ["--value-col", value_col]

        if o:
            args += ["--output", o]

        self._run("product_matrix2.py", self.matrix2_log, args=args,
                  run_btn=self.run_btn6)

    @validated(lambda s: [(s.m3_file, 'Excel 文件'), (s.m3_sheet, 'Sheet 名称'), (s.m3_brands, '目标品牌'), (s.m3_cat_col, '分类列名'), (s.m3_brand_col, '品牌列名')] + ([(s.m3_sales_col, '合并变体所需的销量列')] if s.m3_parent_asin.text().strip() else []), "run_btn7")
    def _run_matrix3(self):
        """运行产品矩阵3（品牌×分类 图片矩阵）。"""
        f = self.m3_file.text().strip()
        s = self.m3_sheet.text().strip()
        brands = self.m3_brands.text().strip()
        cat_col = self.m3_cat_col.text().strip()
        brand_col = self.m3_brand_col.text().strip()

        if not f or not s:
            self.m3_log.setPlainText("请填写 Excel 文件和 Sheet 名称。")
            return
        if not brands:
            self.m3_log.setPlainText("请填写目标品牌（逗号分隔）。")
            return
        if not cat_col or not brand_col:
            self.m3_log.setPlainText("请填写分类列名和品牌列名。")
            return

        args = ["--file", f, "--sheet", s,
                "--category-col", cat_col, "--brand-col", brand_col,
                "--brands", brands]

        filter_text = self.m3_filter.text().strip()
        if filter_text:
            for expr in filter_text.split(';'):
                expr = expr.strip()
                if expr:
                    args += ["--filter", expr]

        cat_vals = self.m3_cat_vals.text().strip()
        if cat_vals:
            args += ["--category-values", cat_vals]

        img_col = self.m3_image_col.text().strip() or "商品主图"
        asin_col = self.m3_asin_col.text().strip() or "ASIN"
        args += ["--image-col", img_col, "--asin-col", asin_col]

        attrs = self.m3_attrs.text().strip()
        if attrs:
            args += ["--attrs", attrs]

        sort_col = self.m3_sort_col.text().strip()
        if sort_col:
            args += ["--sort-col", sort_col]
        if self.m3_sort_order.currentIndex() == 1:  # 降序
            args += ["--sort-descending"]

        parent_asin = self.m3_parent_asin.text().strip()
        if parent_asin:
            args += ["--parent-asin-col", parent_asin]
        sales = self.m3_sales_col.text().strip()
        if sales:
            args += ["--sales-col", sales]
        variant = self.m3_variant_cols.text().strip()
        if variant:
            args += ["--variant-cols", variant]
        launch = self.m3_launch_date_col.text().strip()
        if launch:
            args += ["--launch-date-col", launch]

        o = self.m3_output.text().strip()
        if o:
            args += ["--output", o]

        self._run("product_matrix3.py", self.m3_log, args=args,
                  run_btn=self.run_btn7)
