"""Create a review category without editing JSON or replacing other templates."""
from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QFormLayout, QLineEdit, QPlainTextEdit, QLabel, QHBoxLayout
from core.widgets import make_button


def normalized_name(value):
    return unicodedata.normalize("NFKC", str(value)).strip().casefold()


def build_category(name, description, dimensions, base, existing):
    name, description = name.strip(), description.strip()
    if not name:
        raise ValueError("请填写品类名称。")
    if len(name) > 50:
        raise ValueError("品类名称请控制在 50 个字以内。")
    if any(normalized_name(name) in (normalized_name(key), normalized_name(value.get("display_name", key))) for key, value in existing.items()):
        raise ValueError("这个品类名称已存在，请使用其他名称。")
    if not description:
        raise ValueError("请简单说明这类产品是什么，例如用途、适用人群或主要功能。")
    if not base.get("fields"):
        raise ValueError("缺少基础分析模板，暂时无法创建品类。")
    entry = copy.deepcopy(base)
    entry["display_name"] = name
    entry["product_desc"] = f"产品品类：{name}。产品说明：{description}。仅依据评论中的明确证据提取信息，未提及的信息保留空值。"
    entry["custom_category"] = True
    used = {normalized_name(field["excel_col"]) for field in entry["fields"]}
    used.update(normalized_name(value) for value in ("内容", "星级", "_处理状态", "来源工作表", "来源行号"))
    lines = [line.strip() for line in dimensions.splitlines() if line.strip()]
    if len(lines) > 12:
        raise ValueError("最多添加 12 个补充分析维度。")
    keys = {field["key"] for field in entry["fields"]}
    for line in lines:
        label, _, instruction = line.replace("：", ":", 1).partition(":")
        label = label.strip()
        if not label or len(label) > 30 or any(char in label for char in '[]:*?/\\'):
            raise ValueError("维度名称须为 1–30 个字，不能包含 []:*?/\\ 等符号。")
        if normalized_name(label) in used:
            raise ValueError(f"“{label}”与已有维度重名，请删除重复项。")
        used.add(normalized_name(label))
        key = "custom_" + uuid.uuid4().hex[:12]
        while key in keys:
            key = "custom_" + uuid.uuid4().hex[:12]
        keys.add(key)
        entry["fields"].append({"key": key, "type": "list", "excel_col": label})
        entry.setdefault("stats_fields", []).append(label)
        entry.setdefault("tasks", []).append(
            f"{label}：{instruction.strip() or '提取评论中明确提及的' + label + '相关信息'}。"
            f"输出到 {key}，使用简体中文短标签数组；未提及输出 []，不得编造。"
        )
    return entry


def add_category(config_mgr, name, description, dimensions=""):
    source = Path(config_mgr.resolve_config("product_configs.json"))
    data = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("现有模板文件格式不正确，已保留原文件。")
    products = data.get("products", data)
    if not isinstance(products, dict) or any(not isinstance(value, dict) for value in products.values()):
        raise ValueError("现有品类配置格式不正确，已保留原文件。")
    base = products.get("general")
    if not base:
        bundled = json.loads((Path(config_mgr.get_script_dir()) / "product_configs.json").read_text(encoding="utf-8"))
        base = bundled.get("products", bundled).get("general", {})
    entry = build_category(name, description, dimensions, base, products)
    key = "category_" + uuid.uuid4().hex
    products[key] = entry
    save_templates(config_mgr, source, data)
    return key


def save_templates(config_mgr, source, data):
    """Back up and atomically save a template document, including its metadata."""
    destination = source if source.parent == Path(config_mgr.get_path()).parent else (Path(sys.executable).parent / "product_configs.json" if getattr(sys, "frozen", False) else source)
    # Preserve an existing override before atomically replacing it.
    backup_source = destination if destination.exists() else source
    if backup_source.exists():
        backup_dir = destination.parent / "template-backups"
        backup_dir.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        shutil.copy2(backup_source, backup_dir / f"product_configs_{stamp}.json")
    pending = destination.with_name(f".product_configs_{uuid.uuid4().hex}.tmp")
    try:
        pending.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        # Retry transient Windows file scanner locks; keep atomic replacement.
        import time
        for attempt in range(6):
            try:
                os.replace(pending, destination)
                break
            except PermissionError:
                if attempt == 5: raise
                time.sleep(0.1)
    finally:
        pending.unlink(missing_ok=True)


class AddCategoryDialog(QDialog):
    def __init__(self, config_mgr, parent=None):
        super().__init__(parent)
        self.config_mgr = config_mgr
        self.created_key = None
        self.setWindowTitle("新增分析品类")
        self.resize(610, 480)
        layout = QVBoxLayout(self)
        intro = QLabel("填写产品信息即可创建专属品类，保存后可直接用于评论分析。")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setMaxLength(50)
        self.name_edit.setPlaceholderText("例如：电源滤波器、桌面收纳架")
        form.addRow("品类名称 *", self.name_edit)
        self.description_edit = QPlainTextEdit()
        self.description_edit.setMaximumHeight(95)
        self.description_edit.setPlaceholderText("说明产品是什么、用于什么场景。例如：用于音响设备供电，减少电源干扰的滤波器。")
        form.addRow("产品说明 *", self.description_edit)
        layout.addLayout(form)
        defaults = QLabel("默认分析：使用场景、用户身份、购买动机、关键任务、使用条件、优点、问题和改进需求，并保留评论翻译。")
        defaults.setWordWrap(True)
        layout.addWidget(defaults)
        layout.addWidget(QLabel("补充分析维度（选填，每行一项）"))
        self.dimensions_edit = QPlainTextEdit()
        self.dimensions_edit.setPlaceholderText("例如：\n兼容设备：提取用户实际连接的设备类型\n噪声改善：提取用户对底噪变化的明确描述")
        self.dimensions_edit.setMaximumHeight(130)
        layout.addWidget(self.dimensions_edit)
        self.error_label = QLabel()
        self.error_label.setTextFormat(Qt.TextFormat.PlainText)
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)
        actions = QHBoxLayout()
        actions.addStretch()
        cancel = make_button("取消")
        cancel.clicked.connect(self.reject)
        self.save_btn = make_button("保存品类", "primary")
        self.save_btn.clicked.connect(self._save)
        actions.addWidget(cancel)
        actions.addWidget(self.save_btn)
        layout.addLayout(actions)

    def _save(self):
        try:
            self.created_key = add_category(self.config_mgr, self.name_edit.text(), self.description_edit.toPlainText(), self.dimensions_edit.toPlainText())
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.error_label.setText(str(exc))
            return
        self.accept()
