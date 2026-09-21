"""REV-001: 发送评论到一键分析前的范围确认与品类模板选择。

纯函数（指纹、配置读取、门禁判断）与对话框分离，便于单元测试。
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
)

from core.widgets import Card, configure_combo, make_button


def load_product_templates(config_mgr) -> Dict[str, Any]:
    """读取品类模板配置；文件缺失或损坏时返回空字典而不是抛错。"""
    path = config_mgr.resolve_config("product_configs.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        return {}
    if not isinstance(cfg, dict):
        return {}
    products = cfg.get("products", cfg)
    if not isinstance(products, dict):
        return {}
    return {key: entry for key, entry in products.items() if isinstance(entry, dict)}


def template_fingerprint(entry: Dict[str, Any]) -> str:
    """模板内容的规范 JSON SHA-256 前 12 位，作为版本指纹。"""
    canonical = json.dumps(entry, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def template_display_name(key: str, entry: Dict[str, Any]) -> str:
    return str(entry.get("display_name") or key)


def template_summary_text(key: str, entry: Dict[str, Any]) -> str:
    fields = entry.get("fields") or []
    dims = ", ".join(
        str(f.get("excel_col") or f.get("key") or "")
        for f in fields
        if isinstance(f, dict)
    )
    tasks = entry.get("tasks") or []
    lines = [
        f"模板：{template_display_name(key, entry)}（稳定 key：{key}）",
        f"适用品类：{entry.get('product_desc') or '（未填写）'}",
        f"提取维度（{len(fields)} 项）：{dims or '（未配置）'}",
        f"提取任务：{len(tasks)} 项",
        f"版本指纹：{template_fingerprint(entry)}",
    ]
    if not fields:
        lines.append("⚠ 该模板未配置 fields，无法用于提取")
    return "\n".join(lines)


def template_prompt_preview(key: str, entry: Dict[str, Any]) -> str:
    """展示配置中可核验的模板内容与生成规则；配置不保存完整提示词，不伪造。"""
    parts: List[str] = []
    parts.append("以下内容原样来自 product_configs.json。")
    parts.append("完整提示词由脚本在运行时按“生成规则”组装，配置中并不保存。\n")
    parts.append(f"【系统角色 system_prompt】\n{entry.get('system_prompt') or '（未配置）'}\n")
    parts.append(f"【适用品类 product_desc】\n{entry.get('product_desc') or '（未配置）'}\n")
    tasks = entry.get("tasks") or []
    parts.append("【提取任务 tasks】")
    if tasks:
        parts.extend(f"{i}. {task}" for i, task in enumerate(tasks, start=1))
    else:
        parts.append("（未配置）")
    fields = entry.get("fields") or []
    parts.append("\n【输出字段 fields】")
    if fields:
        for field in fields:
            if isinstance(field, dict):
                parts.append(
                    f"- {field.get('key')}（{field.get('type')}，Excel 列名：{field.get('excel_col')}）"
                )
    else:
        parts.append("（未配置）")
    stats_fields = entry.get("stats_fields") or []
    parts.append(f"\n【汇总统计字段 stats_fields】\n{', '.join(map(str, stats_fields)) or '（未配置）'}")
    parts.append("\n【生成规则】")
    parts.append(
        "Step 1（AI 提取）：scripts/comments_step_1.py 的 build_prompt 把 product_desc、"
        "tasks 与固定的输出格式要求拼成每条评论的用户提示词，system_prompt 作为系统角色发送给模型。"
    )
    parts.append(
        "Step 2（汇总洞察）：scripts/comments_step_2.py 按 stats_fields"
        "（存在 fields[].stat_strategy 时优先）对 Step 1 结果归类统计。"
    )
    parts.append("两个阶段使用同一个品类模板；显示名称仅用于展示，稳定 key 才是唯一标识。")
    return "\n".join(parts)


def find_template_index(keys: Sequence[str], key: Optional[str]) -> int:
    """返回稳定 key 对应的下拉项索引；不存在返回 -1。"""
    if key is None:
        return -1
    for index, item in enumerate(keys):
        if item == key:
            return index
    return -1


def check_template_fingerprint(
    key: str, confirmed_fingerprint: Optional[str], templates: Dict[str, Any]
) -> Tuple[bool, str]:
    """执行前门禁：模板被删除或内容变化时拒绝静默继续。"""
    entry = templates.get(key)
    if entry is None:
        return False, f"品类模板“{key}”已从配置中删除"
    current = template_fingerprint(entry)
    if confirmed_fingerprint and current != confirmed_fingerprint:
        return False, (
            f"品类模板“{key}”在确认后内容已变化（指纹 {confirmed_fingerprint} → {current}）"
        )
    return True, ""


class AnalysisSendDialog(QDialog):
    """发送前的范围与模板确认对话框；取消不产生任何分析任务。"""

    def __init__(self, parent, filters: Dict[str, Any], product: Optional[Dict[str, Any]],
                 templates: Dict[str, Any]):
        super().__init__(parent)
        self.setWindowTitle("发送到一键分析 · 确认范围与品类")
        self.setMinimumWidth(600)
        self._templates = templates
        self._count_ready = False
        self._count_value = -1
        self._fatal_error = ""
        self._build(filters, product)
        self._update_confirm_state()

    # ---- 构建 ----

    def _build(self, filters: Dict[str, Any], product: Optional[Dict[str, Any]]):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        scope = Card("本次分析范围", "确认后即固定，不会因列表选中行或筛选条件后续变化而改变")
        form = QFormLayout()
        if product:
            scope_text = f"{product.get('asin', '')} · {product.get('marketplace', '')}"
            title = str(product.get("title") or "").strip()
            if title:
                scope_text += f" · {title[:60]}"
            form.addRow("目标商品:", self._label(scope_text))
            category_name = str(product.get("category_name") or "").strip()
            if category_name:
                form.addRow(
                    "商品小类目:",
                    self._label(f"“{category_name}”（商品属性，仅供参考，不决定分析模板）"),
                )
        else:
            form.addRow("目标商品:", self._label("未选择商品 · 整个工作区（可能包含多个 ASIN）"))
        rating = filters.get("rating")
        rating_text = "全部星级" if rating is None else f"{rating} 星"
        keyword = str(filters.get("keyword") or "").strip() or "（无）"
        form.addRow("筛选条件:", self._label(f"星级：{rating_text}；关键词：{keyword}"))
        form.addRow(
            "评论范围:",
            self._label("全部匹配记录（不受列表“显示 500 条”限制）"),
        )
        self.count_label = self._label("计算中…")
        form.addRow("匹配评论数:", self.count_label)
        self.asins_label = self._label("计算中…")
        self.asins_label.setWordWrap(True)
        form.addRow("涉及 ASIN:", self.asins_label)
        self.multi_warning = self._label("")
        self.multi_warning.setWordWrap(True)
        self.multi_warning.setVisible(False)
        form.addRow(self.multi_warning)
        scope.content_layout.addLayout(form)
        layout.addWidget(scope)

        category = Card("分析品类模板", "必选；不会静默沿用上一次其他商品的选择")
        cform = QFormLayout()
        self.category_combo = configure_combo(QComboBox())
        self.category_combo.addItem("请选择分析品类…")
        self.category_combo.setItemData(0, QColor("#8F959E"), Qt.ItemDataRole.ForegroundRole)
        for key, entry in self._templates.items():
            self.category_combo.addItem(template_display_name(key, entry), userData=key)
        self.category_combo.currentIndexChanged.connect(self._on_category_changed)
        cform.addRow("分析品类:", self.category_combo)
        self.summary_label = self._label("请先选择分析品类。")
        self.summary_label.setWordWrap(True)
        cform.addRow("模板摘要:", self.summary_label)
        preview_row = QHBoxLayout()
        self.preview_btn = make_button("查看提示词", tooltip="只读展示配置中的模板内容与生成规则")
        self.preview_btn.setEnabled(False)
        self.preview_btn.clicked.connect(self._show_prompt_preview)
        preview_row.addWidget(self.preview_btn)
        preview_row.addStretch()
        cform.addRow(preview_row)
        cform.addRow(
            self._label(
                "所选品类将同时用于“一键完成”的 Step 1（AI 提取）与 Step 2（汇总洞察）。"
            )
        )
        category.content_layout.addLayout(cform)
        layout.addWidget(category)

        self.error_label = self._label("")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.confirm_btn = make_button("确认并进入分析", "primary")
        self.confirm_btn.clicked.connect(self.accept)
        cancel_btn = make_button("取消")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(self.confirm_btn)
        buttons.addWidget(cancel_btn)
        layout.addLayout(buttons)

        if not self._templates:
            self.set_error("品类模板为空：未找到有效的 product_configs.json，请先在“分析品类配置”中导入。")

    @staticmethod
    def _label(text: str) -> QLabel:
        label = QLabel(text)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label

    # ---- 外部更新 ----

    def set_scope(self, count: int, asins: Sequence[str], marketplaces: Sequence[str],
                  source: str, cloud_error: str = ""):
        self._count_ready = True
        self._count_value = count
        text = f"{count} 条（来源：{source}）"
        if cloud_error:
            text += f"；云端回退原因：{cloud_error}"
        self.count_label.setText(text)
        asin_list = list(asins)
        shown = ", ".join(asin_list[:8])
        if len(asin_list) > 8:
            shown += f" 等 {len(asin_list)} 个"
        self.asins_label.setText(shown or "（无）")
        if len(asin_list) > 1:
            self.multi_warning.setText(
                f"⚠ 本次范围包含 {len(asin_list)} 个 ASIN，确认后将用同一个模板统一分析。"
                "不同商品如需不同品类模板，请取消后按商品分别发送。"
            )
            self.multi_warning.setVisible(True)
        if count == 0:
            self._fatal_error = "当前范围没有匹配评论，无法发送分析。"
            self.error_label.setText(self._fatal_error)
            self.error_label.setVisible(True)
        self._update_confirm_state()

    def set_error(self, message: str):
        self._fatal_error = message
        self.error_label.setText(message)
        self.error_label.setVisible(True)
        self._update_confirm_state()

    def selection(self) -> Tuple[str, str, str]:
        key = self.category_combo.currentData()
        entry = self._templates.get(key, {})
        return key, template_display_name(key, entry), template_fingerprint(entry)

    # ---- 内部 ----

    def _on_category_changed(self, _index: int):
        key = self.category_combo.currentData()
        if key and key in self._templates:
            self.summary_label.setText(template_summary_text(key, self._templates[key]))
            self.preview_btn.setEnabled(True)
        else:
            self.summary_label.setText("请先选择分析品类。")
            self.preview_btn.setEnabled(False)
        self._update_confirm_state()

    def _update_confirm_state(self):
        enabled = (
            self._count_ready
            and self._count_value > 0
            and not self._fatal_error
            and bool(self.category_combo.currentData())
        )
        self.confirm_btn.setEnabled(enabled)

    def _show_prompt_preview(self):
        key = self.category_combo.currentData()
        if not key or key not in self._templates:
            return
        viewer = QDialog(self)
        viewer.setWindowTitle(f"模板内容 · {template_display_name(key, self._templates[key])}")
        viewer.resize(680, 520)
        vlayout = QVBoxLayout(viewer)
        text = QPlainTextEdit(template_prompt_preview(key, self._templates[key]))
        text.setReadOnly(True)
        vlayout.addWidget(text)
        close_btn = make_button("关闭")
        close_btn.clicked.connect(viewer.accept)
        vlayout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)
        viewer.exec()


__all__ = [
    "AnalysisSendDialog",
    "load_product_templates",
    "template_fingerprint",
    "template_display_name",
    "template_summary_text",
    "template_prompt_preview",
    "find_template_index",
    "check_template_fingerprint",
]
