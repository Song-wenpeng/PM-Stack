import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PyQt6.QtWidgets import QApplication, QMessageBox
from core.field_templates import with_output_rules
from modules.field_template_panel import FieldTemplatePanel


class TemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'fields.json'
        self.product = dict(name='排插', target_fields=['颜色', '线长'],
            field_config={'颜色': '提取颜色'}, vision_allowed_fields=['颜色'],
            vision_field_config={'颜色': '观察图片'}, custom='保留')
        self.path.write_text(json.dumps({'products': {'strip': self.product}}), encoding='utf-8')
        self.panel = FieldTemplatePanel(str(self.path))
        self.addCleanup(self.panel.deleteLater)

    def test_prompt_rules_are_additive_and_do_not_mutate(self):
        self.product['field_output'] = {'颜色': {'language': '简体中文', 'format': '多色用；分隔'}}
        result = with_output_rules(self.product)
        for key in ('field_config', 'vision_field_config'):
            self.assertIn('简体中文', result[key]['颜色'])
            self.assertIn('不换算单位', result[key]['颜色'])
        self.assertEqual(self.product['field_config']['颜色'], '提取颜色')
        self.assertEqual(with_output_rules({'target_fields': []}), {'target_fields': []})

    def test_edit_reorder_and_save_preserves_metadata(self):
        self.panel.open_product('strip')
        self.panel.language.setText('简体中文')
        self.panel.format.setPlainText('多色用；分隔')
        self.panel.move_field(1)
        self.panel.save()
        data = json.loads(self.path.read_text(encoding='utf-8'))['products']['strip']
        self.assertEqual(data['target_fields'], ['线长', '颜色'])
        self.assertEqual(data['field_output']['颜色']['language'], '简体中文')
        self.assertEqual(data['custom'], '保留')
        self.assertEqual(data['vision_allowed_fields'], ['颜色'])

    def test_copy_new_category_and_cancel_guard(self):
        self.panel.open_product()
        self.panel.copy_from.setCurrentIndex(1)
        self.panel.name.setText('新排插')
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(self.panel.open_product('strip'))
        self.panel.save()
        products = json.loads(self.path.read_text(encoding='utf-8'))['products']
        new_key = next(k for k in products if k != 'strip')
        self.assertTrue(new_key.startswith('category_'))
        self.assertEqual(products[new_key]['name'], '新排插')
        self.assertEqual(products[new_key]['target_fields'], ['颜色', '线长'])
        self.assertEqual(products['strip'], self.product)

    def test_rename_keeps_internal_key(self):
        self.panel.open_product('strip')
        self.panel.name.setText('金属排插')
        self.panel.save()
        products = json.loads(self.path.read_text(encoding='utf-8'))['products']
        self.assertEqual(list(products), ['strip'])
        self.assertEqual(products['strip']['name'], '金属排插')
        self.assertFalse(hasattr(self.panel, 'key'))

    def test_duplicate_and_empty_category_names_do_not_write(self):
        original = self.path.read_bytes()
        self.panel.open_product()
        self.panel.copy_from.setCurrentIndex(1)
        for name in ('', ' 排插 '):
            self.panel.name.setText(name)
            with patch.object(QMessageBox, 'warning') as warning:
                self.panel.save()
                warning.assert_called_once()
            self.assertEqual(self.path.read_bytes(), original)

    def test_duplicate_fields_do_not_write(self):
        before = self.path.read_bytes()
        self.panel.open_product('strip')
        self.panel.field_name.setText('线长')
        with patch.object(QMessageBox, 'warning') as warning:
            self.panel.save()
            warning.assert_called_once()
        self.assertEqual(self.path.read_bytes(), before)

    def test_add_delete_field(self):
        self.panel.open_product('strip')
        self.panel.add_field()
        self.panel.field_name.setText('功率')
        self.panel.rule.setPlainText('提取额定功率')
        self.panel.list.setCurrentRow(1)
        self.panel.remove_field()
        self.panel.save()
        product = json.loads(self.path.read_text(encoding='utf-8'))['products']['strip']
        self.assertEqual(product['target_fields'], ['颜色', '功率'])
        self.assertEqual(product['field_config']['功率'], '提取额定功率')

    def test_both_loaders_use_snapshot_and_prompt_rules(self):
        import ast
        snapshot = {'products': {'strip': dict(self.product, field_output={
            '颜色': {'language': '简体中文', 'format': '黑色；黄色'}})}}
        for script in ('exstract_from_description.py', 'exstract_from_description_fast.py'):
            tree = ast.parse((Path(__file__).parents[1] / 'scripts' / script).read_text(encoding='utf-8-sig'))
            function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'load_product_config')
            scope = {'os': os, 'json': json}
            exec(compile(ast.Module(body=[function], type_ignores=[]), script, 'exec'), scope)
            with patch.dict(os.environ, PRODUCT_CONFIG_SNAPSHOT=json.dumps(snapshot)):
                _, result = scope['load_product_config'](self.path, 'strip')
            self.assertIn('黑色；黄色', result['field_config']['颜色'])
            self.assertIn('简体中文', result['vision_field_config']['颜色'])

    def test_run_captures_template_snapshot(self):
        from modules.market_planning import ModuleWidget
        config = type('Config', (), {'resolve_config': lambda _, name: str(self.path)})()
        widget = ModuleWidget(config, None)
        self.assertEqual(widget.tag_combo.currentText(), '排插')
        self.assertEqual(widget.tag_combo.currentData(), 'strip')
        self.addCleanup(widget.deleteLater)
        widget.tag_input.setText('not-executed.xlsx')
        with patch.object(widget, '_run', return_value=True) as run:
            widget._run_tagging()
        env = run.call_args.args[2]
        self.panel.open_product('strip')
        self.panel.language.setText('简体中文')
        self.panel.save()
        self.assertNotIn('field_output', json.loads(env['PRODUCT_CONFIG_SNAPSHOT'])['products']['strip'])
