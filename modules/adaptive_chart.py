# -*- coding: utf-8 -*-
"""自适应图表模块 — 粘贴数据，AI 自动识别结构，智能出图"""

import os
import json
import tempfile
import re
import numpy as np
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QTextEdit, QComboBox, QLineEdit, QLabel, QScrollArea, QSplitter,
    QMessageBox, QSizePolicy,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QPixmap

from core.widgets import (
    Card, LogConsole, make_button, configure_combo, make_hint_label,
)
from core.theme import THEME

MODULE_INFO = {
    "name": "自适应图表",
    "icon": "📈",
    "category": "图表与报告",
    "order": 3,
    "description": "粘贴表格数据 → AI 自动清洗 → 智能出图（柱状图/饼图/折线图/堆积面积图/排名图）",
}

# AI 系统提示词
SYSTEM_PROMPT = """你是一个数据可视化助手。用户会粘贴表格数据，你需要：

1. 分析数据结构（列类型：分类/数值/日期）
2. 如果用户没有指定图表类型，自动选择最合适的：
   - 分类列(≤8类) + 数值列 → pie 饼图
   - 分类列(>8类) + 数值列 → barh 水平条形图（排名）
   - 分类列 + 数值列(少量) → bar 柱状图
   - 日期列 + 数值列 → line 折线图
   - 日期列 + 多个数值列(各部分构成整体) → stacked_area 100%堆积面积图
   - 日期列 + 多个数值列(数据含正负值，如毛利/损益) → diverging_area 正负面积堆积图
   - 多列数值(宽表，各部分占比有意义) → stacked_area 100%堆积面积图
3. 清洗数据：去除空行、合并单元格痕迹、多余空格
4. 聚合数据：如果相同分类出现多次，按 sum 汇总

**你必须只输出一个 JSON 对象**，不要有任何解释文字。JSON 格式：

柱状图/饼图/条形图:
{"type": "bar", "title": "图表标题", "labels": ["A","B","C"], "values": [10,20,15]}

折线图/堆积面积图（多系列）:
{"type": "line", "title": "图表标题", "x": ["2024-01","2024-02","2024-03"], "series": {"产品A":[10,20,15], "产品B":[8,12,18]}}
{"type": "stacked_area", "title": "图表标题", "x": ["2024-01","2024-02","2024-03"], "series": {"产品A":[10,20,15], "产品B":[8,12,18]}}
{"type": "diverging_area", "title": "图表标题", "x": ["2024-01","2024-02","2024-03"], "series": {"毛利A":[100,-20,150], "毛利B":[50,100,-30]}}

折线图（单系列）:
{"type": "line", "title": "图表标题", "labels": ["1月","2月","3月"], "values": [10,20,15]}

type 可选值: bar, barh, pie, line, stacked_area, diverging_area

规则：
- 数值必须是数字，不是字符串
- title 用中文，简洁描述图表内容
- 分类标签不超过30个，超过的合并为"其他"
- 饼图自动合并占比<2%的项
- stacked_area 用于展示各部分占比随时间/维度变化，数据会被自动归一化到100%
- diverging_area 用于展示含正负值的数据（如毛利、损益），正值向上堆叠、负值向下堆叠，不归一化，保留原始数值"""


class AIThread(QThread):
    """后台调用 AI API 的线程。"""
    finished = pyqtSignal(dict)   # 成功: {"ok": True, "result": {...}}
    error = pyqtSignal(str)       # 失败: 错误消息

    def __init__(self, api_config, raw_data, chart_type_hint):
        super().__init__()
        self.api_config = api_config
        self.raw_data = raw_data
        self.chart_type_hint = chart_type_hint

    def run(self):
        try:
            from openai import OpenAI

            client = OpenAI(
                api_key=self.api_config["api_key"],
                base_url=self.api_config["base_url"],
            )

            model = self.api_config.get("model_name", "deepseek-ai/DeepSeek-V3")

            user_msg = f"请分析以下数据并输出图表 JSON：\n\n{self.raw_data}"
            if self.chart_type_hint:
                user_msg += f"\n\n（用户倾向图表类型: {self.chart_type_hint}）"

            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.1,
                max_tokens=4096,
            )

            content = response.choices[0].message.content.strip()

            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                content = json_match.group(0)

            result = json.loads(content)

            if "type" not in result:
                self.error.emit("AI 返回的 JSON 缺少 'type' 字段")
                return

            chart_type = result["type"]
            if chart_type not in ("bar", "barh", "pie", "line", "stacked_area", "diverging_area"):
                self.error.emit(f"AI 返回了不支持的图表类型: {chart_type}")
                return

            if chart_type in ("line", "stacked_area", "diverging_area") and "x" in result and "series" in result:
                pass
            elif "labels" in result and "values" in result:
                pass
            else:
                self.error.emit("AI 返回的 JSON 格式不正确，需要 labels+values 或 x+series")
                return

            self.finished.emit({"ok": True, "result": result})

        except json.JSONDecodeError as e:
            self.error.emit(f"AI 返回的内容不是有效 JSON: {e}\n\n原始返回:\n{content[:500]}")
        except ImportError:
            self.error.emit("未安装 openai 库。请执行: pip install openai")
        except Exception as e:
            msg = str(e)
            if "api_key" in msg.lower() or "authentication" in msg.lower():
                msg = "API Key 无效或未配置，请在设置中配置 API Key"
            elif "connection" in msg.lower() or "timeout" in msg.lower():
                msg = f"无法连接 API 服务器，请检查网络和 Base URL 配置\n{msg}"
            self.error.emit(msg)


class ModuleWidget(QWidget):
    def __init__(self, config_mgr, runner):
        super().__init__()
        self.config_mgr = config_mgr
        self.runner = runner
        self._last_chart_path = None
        self._ai_thread = None
        self._init_ui()

        self.runner.finished_signal.connect(self._on_script_done)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 20, 28, 24)
        layout.setSpacing(14)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ================= 左侧：输入 =================
        left = QWidget()
        left.setMinimumWidth(360)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(14)

        data_card = Card("数据输入",
                         "从 Excel 复制表格数据后粘贴到此（Ctrl+V），支持任意分隔符")
        self.data_input = QTextEdit()
        self.data_input.setPlaceholderText(
            "在此粘贴表格数据，例如：\n\n"
            "颜色\t数量\n"
            "白色\t15\n"
            "黑色\t12\n"
            "灰色\t8\n\n"
            "也支持空格、逗号等分隔符"
        )
        self.data_input.setFont(QFont("Consolas", 11))
        self.data_input.setMinimumHeight(220)
        self.data_input.setMaximumHeight(280)
        self.data_input.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        data_card.content_layout.addWidget(self.data_input)
        data_card.content_layout.addWidget(
            make_hint_label("从 Excel 选中区域 Ctrl+C，回到这里 Ctrl+V 粘贴"))
        left_layout.addWidget(data_card)

        config_card = Card("图表配置")
        config_form = QFormLayout()
        config_form.setSpacing(10)

        self.chart_type_combo = configure_combo(QComboBox())
        self.chart_type_combo.addItems([
            "🤖 自动检测",
            "📊 柱状图 (bar)",
            "📋 排名条形图 (barh)",
            "🍩 饼图 (pie)",
            "📈 折线图 (line)",
            "🏔️ 100%堆积面积图 (stacked_area)",
            "📉 正负面积堆积图 (diverging_area)",
        ])
        self.chart_type_combo.setCurrentIndex(0)
        self.chart_type_combo.setToolTip("选择期望的图表类型，或不指定由 AI 自动判断")
        config_form.addRow("图表类型:", self.chart_type_combo)

        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("留空由 AI 自动生成标题")
        config_form.addRow("标题:", self.title_input)
        config_card.content_layout.addLayout(config_form)
        left_layout.addWidget(config_card)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self.generate_btn = make_button("🎨 生成图表", "primary",
                                        "根据粘贴的数据生成图表（Ctrl+Enter）")
        self.generate_btn.setShortcut("Ctrl+Return")
        self.generate_btn.clicked.connect(self._on_generate)
        self.generate_btn.setMinimumHeight(40)
        btn_row.addWidget(self.generate_btn, stretch=1)
        clear_btn = make_button("清空", tooltip="清空数据、日志与预览")
        clear_btn.clicked.connect(self._on_clear)
        btn_row.addWidget(clear_btn)
        left_layout.addLayout(btn_row)

        self.log_area = LogConsole(max_height=170)
        left_layout.addWidget(self.log_area)
        left_layout.addStretch()

        splitter.addWidget(left)

        # ================= 右侧：预览 =================
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)

        preview_card = Card("图表预览", "生成的图表将在此显示")
        self.image_scroll = QScrollArea()
        self.image_scroll.setWidgetResizable(True)
        self.image_scroll.setMinimumHeight(420)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(300, 300)
        self._set_preview_empty()
        self.image_scroll.setWidget(self.image_label)
        preview_card.content_layout.addWidget(self.image_scroll)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.open_btn = make_button("打开图片", "compact")
        self.open_btn.clicked.connect(self._open_image)
        self.open_btn.setEnabled(False)
        action_row.addWidget(self.open_btn)
        self.open_dir_btn = make_button("打开输出目录", "compact")
        self.open_dir_btn.clicked.connect(self._open_output_dir)
        action_row.addWidget(self.open_dir_btn)
        action_row.addStretch()
        preview_card.content_layout.addLayout(action_row)

        right_layout.addWidget(preview_card)
        splitter.addWidget(right)
        splitter.setSizes([430, 570])

        layout.addWidget(splitter)

    def _set_preview_empty(self):
        t = THEME.tokens()
        self.image_label.setStyleSheet(
            f"color: {t['text3']}; font-size: 14px; background: transparent;")
        self.image_label.setText("图表将在此显示\n\n← 粘贴数据后点击「生成图表」")

    # ================================================================
    # 核心逻辑（保持不变）
    # ================================================================

    def _on_generate(self):
        raw_data = self.data_input.toPlainText().strip()
        if not raw_data:
            QMessageBox.warning(self, "提示", "请先粘贴数据到输入框。")
            return

        api_key = self.config_mgr.get("api_key", "")
        if not api_key:
            QMessageBox.warning(
                self, "未配置 API",
                "请先在「设置」中配置 API Key 和 Base URL。\n\n"
                "支持 DeepSeek、Qwen、OpenAI 等兼容接口。"
            )
            return

        self._log("🚀 开始处理...")
        self._log(f"  数据长度: {len(raw_data)} 字符")
        self.log_area.set_status("running")
        self.generate_btn.setEnabled(False)
        self.generate_btn.setText("⏳ AI 分析中...")

        type_idx = self.chart_type_combo.currentIndex()
        type_map = {0: "", 1: "bar", 2: "barh", 3: "pie", 4: "line",
                    5: "stacked_area", 6: "diverging_area"}
        chart_type_hint = type_map.get(type_idx, "")

        api_config = {
            "api_key": api_key,
            "base_url": self.config_mgr.get("base_url", "https://api.siliconflow.cn/v1"),
            "model_name": self.config_mgr.get("model_name", "deepseek-ai/DeepSeek-V3"),
        }

        self._ai_thread = AIThread(api_config, raw_data, chart_type_hint)
        self._ai_thread.finished.connect(self._on_ai_done)
        self._ai_thread.error.connect(self._on_ai_error)
        self._ai_thread.start()

    def _on_ai_done(self, result_data):
        self._log("✅ AI 分析完成")
        chart_cfg = result_data["result"]

        manual_title = self.title_input.text().strip()
        if manual_title:
            chart_cfg["title"] = manual_title

        self._log(f"  图表类型: {chart_cfg.get('type', '?')}")
        self._log(f"  标题: {chart_cfg.get('title', '?')}")

        labels = chart_cfg.get("labels", chart_cfg.get("x", []))
        values = chart_cfg.get("values", [])
        series = chart_cfg.get("series", {})
        if labels:
            self._log(f"  数据: {len(labels)} 个数据点")
            self._log(f"  labels: {labels}")
            self._log(f"  values: {values}")
        elif series:
            n_pts = len(list(series.values())[0]) if series else 0
            self._log(f"  数据: {len(series)} 条线, {n_pts} 个点")
            for name, vals in series.items():
                self._log(f"    {name}: {vals}")
            data_arr = np.array(list(series.values()), dtype=float)
            col_sums = data_arr.sum(axis=0)
            self._log(f"  各列总和: {[f'{s:.0f}' for s in col_sums]}")
            data_pct = data_arr / (col_sums + 1e-9) * 100
            self._log("  归一化占比(%):")
            for name, pcts in zip(series.keys(), data_pct):
                self._log(f"    {name}: {[f'{p:.1f}%' for p in pcts]}")

        try:
            tmp = tempfile.NamedTemporaryFile(
                mode='w', suffix='.json', delete=False, encoding='utf-8')
            json.dump(chart_cfg, tmp, ensure_ascii=False, indent=2)
            tmp_path = tmp.name
            tmp.close()
        except Exception as e:
            self._log(f"❌ 写入临时文件失败: {e}")
            self._reset_btn()
            return

        self._log("📊 生成图表中...")

        script_dir = self.config_mgr.get_script_dir()
        script_path = os.path.join(script_dir, "quick_chart.py")

        if not os.path.exists(script_path):
            self._log("❌ 未找到 quick_chart.py，请确保已部署到 scripts/ 目录")
            self._reset_btn()
            return

        try:
            self.runner.log_signal.disconnect()
        except TypeError:
            pass
        self.runner.log_signal.connect(self._on_script_log)
        self.runner.run_script(script_path, ["--config", tmp_path],
                               self.config_mgr.get_env_dict())

    def _on_ai_error(self, msg):
        self._log(f"❌ AI 调用失败: {msg}")
        self.log_area.set_status("error")
        self._reset_btn()

    def _on_script_log(self, line):
        if '→' in line and '.png' in line:
            path = line.split('→')[-1].strip()
            if os.path.exists(path):
                self._last_chart_path = path
                self._display_image(path)
        self._log(f"  {line}")

    def _on_script_done(self, code):
        self._reset_btn()
        if code == 0:
            self._log("✅ 完成")
            self.log_area.set_status("ok")
        else:
            self._log(f"⚠️ 脚本退出码: {code}")
            self.log_area.set_status("error")

    def _on_clear(self):
        """清空数据输入、日志与图表预览。"""
        self.data_input.clear()
        self.log_area.clear()
        self.image_label.clear()
        self._set_preview_empty()
        self._last_chart_path = None
        self.open_btn.setEnabled(False)

    def _display_image(self, path):
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self._log("⚠️ 无法加载生成的图片")
            return

        view_w = self.image_scroll.viewport().width() - 24
        view_h = self.image_scroll.viewport().height() - 24
        if pixmap.width() > view_w or pixmap.height() > view_h:
            pixmap = pixmap.scaled(
                view_w, view_h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)

        self.image_label.setPixmap(pixmap)
        self.image_label.adjustSize()
        self.open_btn.setEnabled(True)

    def _open_image(self):
        if self._last_chart_path and os.path.exists(self._last_chart_path):
            os.startfile(self._last_chart_path)

    def _open_output_dir(self):
        import subprocess
        out_dir = os.path.join(os.path.dirname(
            self.config_mgr.get_script_dir()), "图表输出")
        default_dir = os.path.abspath("./图表输出")
        for d in [out_dir, default_dir]:
            if os.path.isdir(d):
                subprocess.Popen(['explorer', d])
                return
        subprocess.Popen(['explorer', '.'])

    def _log(self, msg):
        self.log_area.append(msg)

    def _reset_btn(self):
        self.generate_btn.setEnabled(True)
        self.generate_btn.setText("🎨 生成图表")
