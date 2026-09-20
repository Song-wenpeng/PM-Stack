"""Reserved review provenance and versioned AI annotations."""
import hashlib
import json
from .normalizer import json_dumps

KEY = "pm_stack"

def as_dict(value):
    if isinstance(value, str):
        try: value = json.loads(value)
        except (ValueError, TypeError): value = {}
    return value if isinstance(value, dict) else {}

def merge_payload(old, new):
    old, new = as_dict(old), as_dict(new)
    result = {**old, **new}
    left, right = as_dict(old.get(KEY)), as_dict(new.get(KEY))
    if left or right:
        result[KEY] = {**left, **right}
        for name in ("imports", "analyses"):
            result[KEY][name] = {**as_dict(left.get(name)), **as_dict(right.get(name))}
    return result

def content_hash(text):
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()

def raw_of(row):
    return as_dict(row.get("raw_payload") or row.get("raw_json"))

def latest_analysis(row):
    analyses = as_dict(as_dict(raw_of(row).get(KEY)).get("analyses"))
    candidates = [a for a in analyses.values() if isinstance(a, dict)
                  and a.get("status") == "success"
                  and a.get("content_hash") == content_hash(row.get("content", ""))]
    return max(candidates, key=lambda a:a.get("created_at", ""), default=None)

def label_summary(row):
    analysis = latest_analysis(row)
    if not analysis: return "未提取"
    values = analysis.get("labels", {})
    pieces = []
    for key, value in values.items():
        if isinstance(value, list) and value:
            pieces.append("/".join(str(x) for x in value[:3]))
    return "；".join(pieces)[:150] or "已提取（无显著标签）"

def review_extra_detail(row):
    analysis = latest_analysis(row)
    lines = ["AI 标签（当前原文）："]
    if analysis:
        lines.append("品类：" + str(analysis.get("category","")))
        lines.append("模型：" + str(analysis.get("model","")))
        for key,value in analysis.get("labels",{}).items():
            label = analysis.get("field_labels",{}).get(key,key)
            lines.append(str(label) + "：" + ("、".join(value) if isinstance(value,list) else str(value) or "无"))
    else:
        lines.append("尚未提取")
    sources = as_dict(as_dict(raw_of(row).get(KEY)).get("imports"))
    if sources:
        lines.append("\n导入来源：")
        for source in sources.values():
            if not isinstance(source,dict): continue
            lines.append(f"{source.get('file','')} · {source.get('sheet','')} 第 {source.get('row','')} 行")
            lines.append(f"目标 ASIN：{source.get('target_asin','')}；来源变体：{source.get('linked_asin') or '未标注'}")
    return "\n".join(lines)
