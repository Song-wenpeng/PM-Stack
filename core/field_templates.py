"""Conservative prompt-only output conventions; never rewrite extracted values."""
from copy import deepcopy


def with_output_rules(product):
    result = deepcopy(product)
    for field, spec in product.get('field_output', {}).items():
        if field not in product.get('target_fields', []):
            continue
        rules = []
        if spec.get('language', '').strip():
            rules.append('输出语言：' + spec['language'].strip())
        if spec.get('format', '').strip():
            rules.append('输出格式与示例：' + spec['format'].strip())
        if not rules:
            continue
        suffix = '\n【表达规范】' + '；'.join(rules) + '。仅统一语言和表达格式；不换算单位、不归并不同含义、不推断主色或补充事实。无法确定时留空，交由人工核对。'
        for key in ('field_config', 'vision_field_config'):
            config = result.setdefault(key, {})
            fallback = product.get('field_config', {}).get(field, '') if key == 'vision_field_config' else ''
            config[field] = (config.get(field) or fallback) + suffix
    return result
