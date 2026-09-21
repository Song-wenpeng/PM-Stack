# -*- coding: utf-8 -*-
"""REV-001 测试：发送分析前的范围确认、品类模板选择与指纹门禁。"""

import json
import os
import tempfile
import unittest

from core.reviews import analysis_dialog as ad


def make_templates():
    return {
        "adapter": {
            "display_name": "转换插头",
            "system_prompt": "你是专业的用户评论分析专家。",
            "product_desc": "插座适配器、转换插头",
            "tasks": ["翻译", "提取正向关注点"],
            "fields": [
                {"key": "translated_comment", "type": "str", "excel_col": "翻译后评论"},
                {"key": "positive_focus", "type": "list", "excel_col": "正向关注点"},
            ],
            "stats_fields": ["正向关注点"],
        },
        "power strip": {
            "display_name": "排插",
            "system_prompt": "你是专业的用户评论分析专家。",
            "product_desc": "排插、插线板",
            "tasks": ["翻译", "提取使用场景"],
            "fields": [
                {"key": "translated_comment", "type": "str", "excel_col": "翻译后评论"},
                {"key": "usage_scenes", "type": "list", "excel_col": "使用场景"},
            ],
            "stats_fields": ["使用场景"],
        },
    }


class FakeConfigMgr:
    def __init__(self, path):
        self._path = path

    def resolve_config(self, filename):
        return self._path


class TestTemplateFingerprint(unittest.TestCase):
    def test_stable_for_same_content(self):
        entry = make_templates()["adapter"]
        self.assertEqual(ad.template_fingerprint(entry), ad.template_fingerprint(dict(entry)))

    def test_sensitive_to_content_change(self):
        entry = make_templates()["adapter"]
        changed = json.loads(json.dumps(entry))
        changed["tasks"].append("提取负向关注点")
        self.assertNotEqual(ad.template_fingerprint(entry), ad.template_fingerprint(changed))

    def test_insensitive_to_key_order(self):
        entry = make_templates()["adapter"]
        reordered = {key: entry[key] for key in reversed(list(entry))}
        self.assertEqual(ad.template_fingerprint(entry), ad.template_fingerprint(reordered))


class TestLoadProductTemplates(unittest.TestCase):
    def _write(self, content):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        self.addCleanup(os.remove, path)
        return path

    def test_plain_mapping(self):
        path = self._write(json.dumps(make_templates(), ensure_ascii=False))
        templates = ad.load_product_templates(FakeConfigMgr(path))
        self.assertEqual(set(templates), {"adapter", "power strip"})

    def test_products_wrapper(self):
        path = self._write(json.dumps({"products": make_templates()}, ensure_ascii=False))
        templates = ad.load_product_templates(FakeConfigMgr(path))
        self.assertEqual(set(templates), {"adapter", "power strip"})

    def test_missing_file_returns_empty(self):
        templates = ad.load_product_templates(FakeConfigMgr(os.path.join(tempfile.gettempdir(), "不存在.json")))
        self.assertEqual(templates, {})

    def test_corrupt_json_returns_empty(self):
        path = self._write("{ 不是 JSON")
        self.assertEqual(ad.load_product_templates(FakeConfigMgr(path)), {})

    def test_non_dict_entries_filtered(self):
        payload = {"ok": make_templates()["adapter"], "bad": "字符串"}
        path = self._write(json.dumps(payload, ensure_ascii=False))
        templates = ad.load_product_templates(FakeConfigMgr(path))
        self.assertEqual(set(templates), {"ok"})


class TestPromptPreview(unittest.TestCase):
    def test_preview_shows_config_content_and_rules_not_fabricated_prompt(self):
        entry = make_templates()["adapter"]
        text = ad.template_prompt_preview("adapter", entry)
        self.assertIn(entry["system_prompt"], text)
        self.assertIn("提取正向关注点", text)
        self.assertIn("翻译后评论", text)
        self.assertIn("生成规则", text)
        self.assertIn("配置中并不保存", text)

    def test_summary_contains_dimensions_and_fingerprint(self):
        entry = make_templates()["power strip"]
        text = ad.template_summary_text("power strip", entry)
        self.assertIn("排插", text)
        self.assertIn("使用场景", text)
        self.assertIn(ad.template_fingerprint(entry), text)


class TestFingerprintGate(unittest.TestCase):
    def test_ok_when_unchanged(self):
        templates = make_templates()
        fp = ad.template_fingerprint(templates["adapter"])
        ok, reason = ad.check_template_fingerprint("adapter", fp, templates)
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_rejected_when_changed(self):
        templates = make_templates()
        ok, reason = ad.check_template_fingerprint("adapter", "旧指纹000000", templates)
        self.assertFalse(ok)
        self.assertIn("内容已变化", reason)

    def test_rejected_when_deleted(self):
        ok, reason = ad.check_template_fingerprint("adapter", "任意", {})
        self.assertFalse(ok)
        self.assertIn("删除", reason)

    def test_find_template_index(self):
        keys = [None, "adapter", "power strip"]
        self.assertEqual(ad.find_template_index(keys, "power strip"), 2)
        self.assertEqual(ad.find_template_index(keys, "不存在"), -1)
        self.assertEqual(ad.find_template_index(keys, None), -1)


class DialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def _make(self, templates=None, product=None):
        filters = {"asin": "B000TEST01", "rating": None, "keyword": ""}
        return ad.AnalysisSendDialog(None, filters, product, templates if templates is not None else make_templates())

    def test_confirm_disabled_until_scope_and_selection(self):
        dialog = self._make()
        self.assertFalse(dialog.confirm_btn.isEnabled(), "未选品类且未完成统计时不能确认")
        self.assertIsNone(dialog.category_combo.currentData(), "默认必须是占位项，不沿用任何品类")
        dialog.set_scope(12, ["B000TEST01"], ["amazon.com"], "本地快照")
        self.assertFalse(dialog.confirm_btn.isEnabled(), "统计完成但未选品类仍不能确认")
        dialog.category_combo.setCurrentIndex(1)
        self.assertTrue(dialog.confirm_btn.isEnabled())

    def test_selection_returns_key_display_fingerprint(self):
        dialog = self._make()
        dialog.set_scope(3, ["B000TEST01"], ["amazon.com"], "本地快照")
        dialog.category_combo.setCurrentIndex(2)
        key, display, fingerprint = dialog.selection()
        self.assertEqual(key, "power strip")
        self.assertEqual(display, "排插")
        self.assertEqual(fingerprint, ad.template_fingerprint(make_templates()["power strip"]))

    def test_zero_count_blocks_confirm(self):
        dialog = self._make()
        dialog.category_combo.setCurrentIndex(1)
        dialog.set_scope(0, [], [], "本地快照")
        self.assertFalse(dialog.confirm_btn.isEnabled())
        self.assertIn("没有匹配评论", dialog.error_label.text())

    def test_multi_asin_warning(self):
        dialog = self._make()
        dialog.set_scope(30, ["A1", "A2", "A3"], ["amazon.com"], "本地快照")
        # 对话框未 show 时子控件 isVisible() 恒为 False，用 isHidden() 断言自身状态
        self.assertFalse(dialog.multi_warning.isHidden())
        self.assertIn("3 个 ASIN", dialog.multi_warning.text())

    def test_single_asin_no_warning(self):
        dialog = self._make()
        dialog.set_scope(10, ["A1"], ["amazon.com"], "本地快照")
        self.assertTrue(dialog.multi_warning.isHidden())

    def test_empty_templates_blocks_confirm(self):
        dialog = self._make(templates={})
        dialog.set_scope(5, ["A1"], ["amazon.com"], "本地快照")
        self.assertFalse(dialog.confirm_btn.isEnabled())
        self.assertIn("品类模板为空", dialog.error_label.text())

    def test_fatal_error_blocks_confirm(self):
        dialog = self._make()
        dialog.category_combo.setCurrentIndex(1)
        dialog.set_scope(5, ["A1"], ["amazon.com"], "本地快照")
        dialog.set_error("统计失败：云端异常")
        self.assertFalse(dialog.confirm_btn.isEnabled())


class ReceiverTests(unittest.TestCase):
    """用最小宿主执行真实的 _use_collected_review_file 逻辑。"""

    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def _make_harness(self):
        from PyQt6.QtWidgets import QComboBox, QLineEdit
        from modules.comment_analysis import ModuleWidget

        class FakeLog:
            def __init__(self):
                self.text = ""
                self.status = ""

            def clear(self):
                self.text = ""

            def append(self, message):
                self.text += message + "\n"

            def setPlainText(self, message):
                self.text = message

            def set_status(self, status):
                self.status = status

        class FakeTabs:
            def __init__(self):
                self.current = None

            def widget(self, index):
                return f"page-{index}"

            def setCurrentWidget(self, widget):
                self.current = widget

        class Harness:
            _use_collected_review_file = ModuleWidget._use_collected_review_file
            _s12_product_changed = ModuleWidget._s12_product_changed

            def __init__(self):
                self.s12_input = QLineEdit()
                self.s12_sheets = QLineEdit()
                self.s12_product = QComboBox()
                self.s12_product.addItem("请选择品类…")
                for key, entry in make_templates().items():
                    self.s12_product.addItem(entry["display_name"], userData=key)
                self.s12_product.currentIndexChanged.connect(self._s12_product_changed)
                self.tabs = FakeTabs()
                self.log_s12 = FakeLog()
                self._s12_confirmation = None

        return Harness()

    def _payload(self, key="power strip"):
        templates = make_templates()
        return {
            "path": "C:/tmp/评论分析输入_test.xlsx",
            "product_key": key,
            "product_display": templates[key]["display_name"],
            "fingerprint": ad.template_fingerprint(templates[key]),
            "review_count": 120,
            "source": "本地快照",
            "filters": {"asin": "B000TEST01", "rating": None, "keyword": ""},
            "asins": ["B000TEST01"],
            "marketplaces": ["amazon.com"],
        }

    def test_receive_selects_confirmed_category(self):
        harness = self._make_harness()
        harness._use_collected_review_file(self._payload())
        self.assertEqual(harness.s12_product.currentData(), "power strip")
        self.assertEqual(harness.s12_input.text(), "C:/tmp/评论分析输入_test.xlsx")
        self.assertEqual(harness._s12_confirmation["key"], "power strip")
        self.assertEqual(harness.tabs.current, "page-3")
        self.assertIn("已确认分析品类：排插", harness.log_s12.text)
        self.assertIn("120 条", harness.log_s12.text)

    def test_receive_missing_template_does_not_fall_back(self):
        harness = self._make_harness()
        payload = self._payload()
        payload["product_key"] = "已被删除的品类"
        harness._use_collected_review_file(payload)
        self.assertIsNone(harness.s12_product.currentData(), "不得静默回退到某个品类")
        self.assertIsNone(harness._s12_confirmation)
        self.assertIn("错误", harness.log_s12.text)

    def test_manual_combo_change_clears_confirmation(self):
        harness = self._make_harness()
        harness._use_collected_review_file(self._payload())
        self.assertIsNotNone(harness._s12_confirmation)
        harness.s12_product.setCurrentIndex(1)
        self.assertIsNone(harness._s12_confirmation, "用户手动改品类后视为人工接管，清除确认态")


if __name__ == "__main__":
    unittest.main()
