# -*- coding: utf-8 -*-
"""
产品评论 AI 总结结果可视化脚本
--------------------------------------------------
适用场景：
1）输入文件是"评论 AI 总结"类 Excel；
2）Excel 中已经有类似以下 sheet：
   - 目标国家_AI归类
   - 设备类型_AI归类
   - 用户身份_AI归类
   - 正向关注点_AI归类
   - 负向关注点_AI归类
   - 摘要汇总
3）脚本会读取各维度归类结果，调用 AI API 生成可视化方案，
   然后用 Python 自动生成 Excel 看板。

运行示例：
python review_visual_dashboard_ai.py \
  --input "./评论数据_B0DR2V76JV_AI总结.xlsx" \
  --output "./评论数据_B0DR2V76JV_可视化看板.xlsx" \
  --product-name "旅行插座适配器"

依赖安装：
pip install pandas openpyxl xlsxwriter openai

API 配置：
Windows PowerShell：
$env:SILICONFLOW_API_KEY="你的API Key"

macOS / Linux：
export SILICONFLOW_API_KEY="你的API Key"
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

import pandas as pd


# ===================== 配置加载 =====================
def load_dashboard_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """加载看板配置 JSON，未提供或文件不存在时使用内置默认值。"""
    defaults: Dict[str, Any] = {
        "api": {
            "base_url": "https://api.siliconflow.cn/v1",
            "model": "deepseek-ai/DeepSeek-V3",
            "api_key_env": "SILICONFLOW_API_KEY",
        },
        "data_reading": {
            "sheet_suffix": "_AI归类",
            "fallback_sheet": "摘要汇总",
            "required_ai_cols": ["类别", "类别总次数", "原始标签", "原始标签次数", "代表性标签"],
        },
        "fallback_rules": {
            "dimension_order": ["目标国家", "设备类型", "正向关注点", "负向关注点", "用户身份"],
            "chart_type_rules": [
                {"keyword": "正向", "chart_type": "bar", "top_n": 10},
                {"keyword": "负向", "chart_type": "bar", "top_n": 10},
                {"keyword": "国家", "chart_type": "column", "top_n": 8},
                {"keyword": "地区", "chart_type": "column", "top_n": 8},
            ],
            "default_rule": {"chart_type": "column", "top_n": 8},
            "donut_threshold": 6,
            "skip_min_categories": 1,
            "min_top_n": 3,
            "max_top_n": 15,
            "max_modules": 6,
            "default_ai_top_n": 12,
        },
        "layout": {
            "chart_width": 520,
            "chart_height": 300,
            "chart_style": 10,
            "donut_hole_size": 55,
            "start_row": 7,
            "start_col": 1,
            "col_spacing": 8,
            "rows_per_chart": 19,
            "insight_row_offset": 15,
            "insight_width_cols": 7,
            "dashboard": {
                "sheet_name": "Dashboard",
                "col_A": 3, "col_B_to_H": 13, "col_I": 3, "col_J_to_P": 13,
                "title_col_range": "B1:P1", "subtitle_col_range": "B2:P2",
                "subtitle_text": "由 Python 读取评论 AI 总结结果，并结合 AI 生成可视化方案后自动生成。",
                "row_height_0": 32,
                "kpi_card_start_row": 3,
                "kpi_card_positions": [[3, 1], [3, 5], [3, 9], [3, 13]],
                "kpi_card_title_rows": 1, "kpi_card_value_rows": 2, "kpi_card_title_cols": 2,
            },
            "chart_data": {
                "sheet_name": "图表数据",
                "columns": [
                    {"col": "A:A", "width": 14}, {"col": "B:B", "width": 24},
                    {"col": "C:C", "width": 10}, {"col": "D:D", "width": 10}, {"col": "E:E", "width": 40},
                ],
                "headers": ["维度", "类别", "次数", "占比", "代表性标签"],
            },
            "plan_sheet": {
                "sheet_name": "AI可视化方案",
                "headers": ["维度", "标题", "图表类型", "TopN", "看图判断", "业务用途"],
            },
            "insight_sheet": {
                "sheet_name": "产品洞察",
                "headers": ["项目", "内容"],
                "fallback_text": "未调用 AI 或 AI 未返回产品洞察，可依据 Dashboard 和图表数据自行补充。",
            },
            "cleaned_sheet_suffix": "_清洗统计",
        },
        "styles": {
            "colors": {
                "title_font": "#1F2937", "subtitle_font": "#6B7280",
                "card_title_font": "#374151", "card_title_bg": "#F3F4F6",
                "card_value_font": "#111827", "card_value_bg": "#FFFFFF",
                "header_font": "#FFFFFF", "header_bg": "#374151",
                "border": "#E5E7EB", "insight_font": "#374151", "insight_bg": "#F9FAFB",
            },
            "fonts": {
                "title_size": 20, "subtitle_size": 10,
                "card_title_size": 11, "card_value_size": 18,
            },
        },
        "ui_text": {
            "kpi_labels": ["分析维度", "归类类别", "统计次数", "看板模块"],
            "insight_template": "看图判断：{insight}\n用途：{business_use}",
            "fallback_chart_title_template": "{dim}分布",
            "fallback_insight_template": "{dim}的高频类别反映了用户评论中的主要集中方向，可用于判断产品定位和优化优先级。",
            "fallback_business_use": "用于产品开发、Listing卖点提炼和差评问题定位。",
            "dashboard_title_template": "{product_name} 评论洞察可视化看板",
            "fallback_positioning": "该产品的评论反馈应围绕高频使用场景、核心设备适配和正负向关注点进行产品判断。",
        },
        "prompts": {
            "system_prompt_file": "dashboard_prompts/system_prompt.txt",
            "user_prompt_file": "dashboard_prompts/user_prompt.txt",
        },
    }

    if config_path and os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as fh:
            user_config = json.load(fh)
        _deep_merge(defaults, user_config)
    return defaults


def _deep_merge(base: dict, override: dict) -> None:
    """将 override 递归合并到 base 中（原地修改 base），列表直接替换。"""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def _load_prompt_text(relative_path: str, fallback: str) -> str:
    """从指定路径加载 Prompt 模板文件，失败时返回 fallback。"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    full_path = os.path.join(script_dir, relative_path)
    if os.path.exists(full_path):
        with open(full_path, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    return fallback


@dataclass
class DimensionData:
    """单个分析维度的数据，例如：目标国家、设备类型、正向关注点。"""

    dimension: str
    source_sheet: str
    categories: pd.DataFrame
    raw_rows: pd.DataFrame


# ===================== 工具函数 =====================
def safe_sheet_name(name: str) -> str:
    """清理 Excel sheet 名称，避免超过长度或包含非法字符。"""
    name = re.sub(r"[\\/*?:\[\]]", "_", str(name))
    return name[:31] if len(name) > 31 else name


def to_number(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").fillna(0)


def extract_json_from_text(text: str) -> Dict[str, Any]:
    """从模型返回文本中提取 JSON，兼容 ```json 包裹的情况。"""
    if not text:
        raise ValueError("AI 返回为空")

    text = text.strip()
    text = re.sub(r"^```json\s*", "", text)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    return df


def clean_text(value: Any) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    text = re.sub(r"\s+", " ", text)
    return "" if text.lower() == "nan" else text


def split_labels(text: str) -> List[str]:
    """兼容中文分号、英文分号、逗号、换行等分隔符。"""
    if not text:
        return []
    parts = re.split(r"[;；\n、,，]+", str(text))
    out = []
    seen = set()
    for p in parts:
        p = clean_text(p)
        if not p or p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def format_count(value: Any) -> str:
    try:
        v = float(value)
        return str(int(v)) if v.is_integer() else f"{v:.1f}"
    except Exception:
        return str(value)


def is_generic_text(text: str, phrases: Optional[List[str]] = None) -> bool:
    if not clean_text(text):
        return True
    if not phrases:
        return False
    return any(p in text for p in phrases)


# ===================== 代表性标签工具 =====================
def get_top_raw_labels(data: "DimensionData", category: str, top_k: int = 4) -> List[str]:
    """优先从 raw_rows 中提取某个类别下的高频原始标签；没有时退回 categories 的代表性标签。"""
    labels: List[str] = []
    raw = data.raw_rows.copy()

    if not raw.empty and {"类别", "原始标签", "原始标签次数"}.issubset(set(raw.columns)):
        sub = raw[raw["类别"].astype(str).str.strip() == str(category).strip()].copy()
        if not sub.empty:
            sub["原始标签次数"] = to_number(sub["原始标签次数"])
            sub = sub.sort_values("原始标签次数", ascending=False)
            seen = set()
            for _, row in sub.iterrows():
                label = clean_text(row.get("原始标签", ""))
                if not label or label in seen:
                    continue
                seen.add(label)
                cnt = row.get("原始标签次数", 0)
                labels.append(f"{label}（{format_count(cnt)}）" if float(cnt or 0) > 0 else label)
                if len(labels) >= top_k:
                    return labels

    # 退回 categories 的代表性标签字段
    cat = data.categories[data.categories["类别"].astype(str).str.strip() == str(category).strip()]
    if not cat.empty:
        rep_text = clean_text(cat.iloc[0].get("代表性标签", ""))
        for label in split_labels(rep_text):
            labels.append(label)
            if len(labels) >= top_k:
                break
    return labels


def build_detail_rows(data: "DimensionData", top_n: int = 8, label_top_k: int = 4) -> List[Dict[str, Any]]:
    """构造每个可视化模块要展示的 Top 类别 + 代表性标签。"""
    rows: List[Dict[str, Any]] = []
    df = data.categories.head(top_n).copy()
    for _, row in df.iterrows():
        category = clean_text(row.get("类别", ""))
        rows.append(
            {
                "类别": category,
                "次数": float(row.get("次数", 0) or 0),
                "占比": float(row.get("占比", 0) or 0),
                "代表性标签": "；".join(get_top_raw_labels(data, category, top_k=label_top_k)),
            }
        )
    return rows


# ===================== 读取 Excel 汇总结果 =====================
def load_ai_summary_excel(input_file: str, config: Optional[dict] = None) -> Dict[str, DimensionData]:
    """
    优先读取 *_AI归类 sheet。
    如果没有 *_AI归类 sheet，则尝试读取"摘要汇总"。
    """
    data_cfg = config.get("data_reading", {}) if config else {}
    required_cols = data_cfg.get("required_ai_cols", ["类别", "类别总次数", "原始标签", "原始标签次数", "代表性标签"])
    sheet_suffix = data_cfg.get("sheet_suffix", "_AI归类")
    fallback_sheet = data_cfg.get("fallback_sheet", "摘要汇总")

    xls = pd.ExcelFile(input_file)
    dimensions: Dict[str, DimensionData] = {}

    for sheet in xls.sheet_names:
        if not sheet.endswith(sheet_suffix):
            continue

        df = pd.read_excel(input_file, sheet_name=sheet)
        df = normalize_columns(df)

        if not set(["类别", "原始标签"]).issubset(set(df.columns)):
            continue

        # 补齐缺失列，保证后续逻辑稳定
        for col in required_cols:
            if col not in df.columns:
                df[col] = "" if col not in ["类别总次数", "原始标签次数"] else 0

        df = df[required_cols].copy()
        df["类别"] = df["类别"].astype(str).str.strip()
        df = df[(df["类别"] != "") & (df["类别"].str.lower() != "nan")]

        df["类别总次数"] = to_number(df["类别总次数"])
        df["原始标签次数"] = to_number(df["原始标签次数"])

        # 注意：类别总次数在同一类别下会重复出现，不能 sum，否则会重复计算。
        cat_df = (
            df.groupby("类别", as_index=False)
            .agg(
                次数=("类别总次数", "max"),
                代表性标签=("代表性标签", lambda x: next((str(v) for v in x if pd.notna(v) and str(v).strip()), "")),
            )
            .sort_values("次数", ascending=False)
        )

        # 如果类别总次数缺失，则退化为原始标签次数加总
        zero_mask = cat_df["次数"] <= 0
        if zero_mask.any():
            fallback_ref = df.groupby("类别")["原始标签次数"].sum().to_dict()
            cat_df.loc[zero_mask, "次数"] = cat_df.loc[zero_mask, "类别"].map(fallback_ref).fillna(0)

        total = cat_df["次数"].sum()
        cat_df["占比"] = cat_df["次数"] / total if total else 0
        cat_df = cat_df.sort_values("次数", ascending=False).reset_index(drop=True)

        dimension_name = sheet.replace(sheet_suffix, "")
        dimensions[dimension_name] = DimensionData(
            dimension=dimension_name,
            source_sheet=sheet,
            categories=cat_df,
            raw_rows=df,
        )

    if dimensions:
        return dimensions

    # 兜底：读取摘要汇总
    if fallback_sheet in xls.sheet_names:
        summary = pd.read_excel(input_file, sheet_name=fallback_sheet)
        summary = normalize_columns(summary)
        if set(["字段", "类别", "总次数"]).issubset(set(summary.columns)):
            current_dim = None
            rows = []
            for _, row in summary.iterrows():
                if pd.notna(row.get("字段")):
                    current_dim = str(row.get("字段")).strip()
                if current_dim and pd.notna(row.get("类别")):
                    rows.append(
                        {
                            "维度": current_dim,
                            "类别": row.get("类别"),
                            "次数": row.get("总次数"),
                            "代表性标签": row.get("代表性标签", ""),
                        }
                    )
            if rows:
                tmp = pd.DataFrame(rows)
                tmp["次数"] = to_number(tmp["次数"])
                for dim, g in tmp.groupby("维度"):
                    cat_df = g[["类别", "次数", "代表性标签"]].copy()
                    total = cat_df["次数"].sum()
                    cat_df["占比"] = cat_df["次数"] / total if total else 0
                    cat_df = cat_df.sort_values("次数", ascending=False).reset_index(drop=True)
                    raw_df = pd.DataFrame(columns=required_cols)
                    dimensions[dim] = DimensionData(dim, fallback_sheet, cat_df, raw_df)

    if not dimensions:
        raise ValueError(f"没有识别到可视化所需数据。请确认 Excel 中是否存在 *{sheet_suffix} 或 {fallback_sheet} sheet。")

    return dimensions


def build_ai_input_payload(dimensions: Dict[str, DimensionData], top_n: int = 12, label_top_k: int = 4) -> Dict[str, Any]:
    """传给 AI 的数据中增加代表性标签，避免 AI 只写泛泛判断。"""
    payload: Dict[str, Any] = {}
    for dim, data in dimensions.items():
        rows = build_detail_rows(data, top_n=top_n, label_top_k=label_top_k)
        payload[dim] = [
            {
                "类别": r["类别"],
                "次数": int(r["次数"]) if float(r["次数"]).is_integer() else r["次数"],
                "占比": round(float(r["占比"]), 4),
                "代表性标签": r["代表性标签"],
            }
            for r in rows
        ]
    return payload


# ===================== AI 生成可视化方案 =====================
_FALLBACK_SYSTEM_PROMPT = """
你是一个跨境电商产品经理和数据可视化顾问，擅长把亚马逊评论分析结果转化为产品开发看板。
你不能写"高频类别反映主要集中方向"这种空话，必须基于输入数据中的 Top 类别、次数、占比、代表性标签写出具体判断。
只能返回严格 JSON，不要返回 Markdown，不要解释。
""".strip()

_FALLBACK_USER_PROMPT_TPL = """
产品名称：{product_name}

下面是该产品评论分析后的归类统计数据。每个类别都包含次数、占比、代表性标签。
请基于这些数据，输出一个 Excel 看板可视化方案。

要求：
1. 每个模块指定 chart_type，可选值：bar、column、donut；
2. 正向关注点、负向关注点通常适合 bar；目标国家/地区通常适合 column 或 donut；
3. insight 必须具体引用 Top 类别和业务含义，例如"差评集中在设计缺陷、质量问题，说明改款优先处理……"，禁止写空泛模板句；
4. business_use 必须说明这一张图用于哪个决策，例如"主图场景选择""Listing五点卖点""结构改款优先级""不适配提醒"；
5. 不要编造输入中没有的类别、次数、标签；
6. 返回严格 JSON，不要包含多余文字。

返回格式：
{{
  "dashboard_title": "xxx",
  "modules": [
    {{
      "dimension": "维度名称，必须来自输入数据",
      "title": "图表标题",
      "chart_type": "bar/column/donut",
      "top_n": 8,
      "insight": "具体数据判断，必须出现Top类别名称",
      "business_use": "具体用途",
      "priority": 1
    }}
  ],
  "product_insights": {{
    "positioning": "一句话产品定位判断",
    "selling_points": ["可转化为Listing卖点的点1", "点2", "点3"],
    "improvement_priorities": ["优先改进点1", "优先改进点2", "优先改进点3"]
  }}
}}

输入数据：
{data_payload}
""".strip()


def call_ai_for_visual_plan(
    data_payload: Dict[str, Any],
    product_name: str,
    api_key: Optional[str],
    base_url: str,
    model: str,
    config: Optional[dict] = None,
) -> Optional[Dict[str, Any]]:
    """调用 OpenAI 兼容接口，让 AI 生成可视化方案。没有 API Key 时返回 None。"""
    if not api_key:
        return None

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ImportError("未安装 openai 包，请先执行：pip install openai") from exc

    client = OpenAI(api_key=api_key, base_url=base_url)

    prompt_cfg = config.get("prompts", {}) if config else {}

    system_prompt = _load_prompt_text(
        prompt_cfg.get("system_prompt_file", "dashboard_prompts/system_prompt.txt"),
        _FALLBACK_SYSTEM_PROMPT,
    )

    user_prompt_tpl = _load_prompt_text(
        prompt_cfg.get("user_prompt_file", "dashboard_prompts/user_prompt.txt"),
        _FALLBACK_USER_PROMPT_TPL,
    )
    data_json = json.dumps(data_payload, ensure_ascii=False, indent=2)
    user_prompt = user_prompt_tpl.format(product_name=product_name, data_payload=data_json)

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
    )

    content = resp.choices[0].message.content
    return extract_json_from_text(content)


def enrich_plan_with_details(
    plan: Dict[str, Any],
    dimensions: Dict[str, DimensionData],
    config: Optional[dict] = None,
    label_top_k: int = 4,
) -> Dict[str, Any]:
    """把代表性标签明细写回每个 module；同时替换被检测为空泛的 insight/business_use。"""
    generic_phrases = config.get("generic_phrases", []) if config else []
    fb_cfg = config.get("fallback", {}) if config else {}
    for module in plan.get("modules", []):
        dim = module.get("dimension")
        if dim not in dimensions:
            continue
        top_n = int(module.get("top_n", 8) or 8)
        rows = build_detail_rows(dimensions[dim], top_n=top_n, label_top_k=label_top_k)
        module["detail_rows"] = rows

        if is_generic_text(module.get("insight", ""), generic_phrases) and rows:
            top1 = rows[0]["类别"]
            label_text = "；".join(str(r.get("代表性标签", "")) for r in rows[:3])
            tpl = fb_cfg.get("insight_template", "{dim} Top {top_n} 类别分布，{top1} 占比最高，具体判断可启用 AI 生成。代表性标签：{labels}")
            module["insight"] = tpl.format(dim=dim, top_n=top_n, top1=top1, labels=label_text)

        if is_generic_text(module.get("business_use", ""), generic_phrases):
            tpl = fb_cfg.get("business_use_template", "用于辅助判断 {dim} 的产品定位和优化方向。")
            module["business_use"] = tpl.format(dim=dim)
    return plan


def fallback_visual_plan(
    dimensions: Dict[str, DimensionData],
    product_name: str,
    config: Optional[dict] = None,
    label_top_k: int = 4,
) -> Dict[str, Any]:
    """没有 API 或 AI 返回失败时，使用配置规则生成方案。判断诚实简单，不做关键词猜测。"""
    rules_cfg = config.get("fallback_rules", {}) if config else {}
    ui_cfg = config.get("ui_text", {}) if config else {}
    fb_cfg = config.get("fallback", {}) if config else {}

    modules = []
    priority = 1

    dimension_order = rules_cfg.get("dimension_order", [])
    chart_type_rules = rules_cfg.get("chart_type_rules", [])
    default_rule = rules_cfg.get("default_rule", {"chart_type": "column", "top_n": 8})
    donut_threshold = rules_cfg.get("donut_threshold", 6)
    skip_min = rules_cfg.get("skip_min_categories", 1)
    max_modules = rules_cfg.get("max_modules", 6)

    ordered_dims = dimension_order + [d for d in dimensions if d not in dimension_order]
    for dim in ordered_dims:
        if dim not in dimensions:
            continue
        cat_count = len(dimensions[dim].categories)
        if cat_count <= skip_min:
            continue

        # 按规则列表顺序匹配，首个关键字命中即胜出
        ruled = False
        for rule in chart_type_rules:
            keyword = rule.get("keyword", "")
            if keyword and keyword in dim:
                chart_type = rule.get("chart_type", default_rule["chart_type"])
                top_n = rule.get("top_n", default_rule["top_n"])
                ruled = True
                break

        if not ruled:
            if cat_count <= donut_threshold:
                chart_type = "donut"
                top_n = donut_threshold
            else:
                chart_type = default_rule["chart_type"]
                top_n = default_rule["top_n"]

        detail_rows = build_detail_rows(dimensions[dim], top_n=top_n, label_top_k=label_top_k)
        top1 = detail_rows[0]["类别"] if detail_rows else ""
        label_text = "；".join(str(r.get("代表性标签", "")) for r in detail_rows[:3]) if detail_rows else ""
        insight_tpl = fb_cfg.get("insight_template", "{dim} Top {top_n} 类别分布，{top1} 占比最高，具体判断可启用 AI 生成。代表性标签：{labels}")
        business_tpl = fb_cfg.get("business_use_template", "用于辅助判断 {dim} 的产品定位和优化方向。")

        chart_title_tpl = ui_cfg.get("fallback_chart_title_template", "{dim}分布")
        modules.append(
            {
                "dimension": dim,
                "title": chart_title_tpl.format(dim=dim),
                "chart_type": chart_type,
                "top_n": top_n,
                "insight": insight_tpl.format(dim=dim, top_n=top_n, top1=top1, labels=label_text),
                "business_use": business_tpl.format(dim=dim),
                "priority": priority,
                "detail_rows": detail_rows,
            }
        )
        priority += 1

    # 产品洞察从配置指定的正/负向维度自动提取
    selling_points = []
    improvement_priorities = []
    sp_dim = config.get("selling_points_dim", "正向关注点") if config else "正向关注点"
    ip_dim = config.get("improvement_priorities_dim", "负向关注点") if config else "负向关注点"
    if sp_dim in dimensions:
        selling_points = [r["类别"] for r in build_detail_rows(dimensions[sp_dim], top_n=5, label_top_k=2)[:5]]
    if ip_dim in dimensions:
        improvement_priorities = [r["类别"] for r in build_detail_rows(dimensions[ip_dim], top_n=5, label_top_k=2)[:5]]

    dashboard_title_tpl = ui_cfg.get("dashboard_title_template", "{product_name} 评论洞察可视化看板")
    positioning_tpl = fb_cfg.get("positioning_template", "该产品应围绕核心维度的 Top 类别进行页面表达与改款排序，开启 AI 可获取更具体的产品洞察。")
    return {
        "dashboard_title": dashboard_title_tpl.format(product_name=product_name),
        "modules": modules[:max_modules],
        "product_insights": {
            "positioning": positioning_tpl,
            "selling_points": selling_points,
            "improvement_priorities": improvement_priorities,
        },
    }


def validate_plan(
    plan: Dict[str, Any],
    dimensions: Dict[str, DimensionData],
    product_name: str,
    config: Optional[dict] = None,
) -> Dict[str, Any]:
    """修正 AI 方案，避免维度名不存在、图表类型非法等问题。"""
    rules_cfg = config.get("fallback_rules", {}) if config else {}
    ui_cfg = config.get("ui_text", {}) if config else {}

    valid_dims = set(dimensions.keys())
    valid_types = {"bar", "column", "donut"}
    cleaned_modules = []
    used = set()

    min_tn = rules_cfg.get("min_top_n", 3)
    max_tn = rules_cfg.get("max_top_n", 15)
    max_modules = rules_cfg.get("max_modules", 6)

    for idx, module in enumerate(plan.get("modules", []), start=1):
        dim = module.get("dimension")
        if dim not in valid_dims or dim in used:
            continue
        chart_type = module.get("chart_type", "column")
        if chart_type not in valid_types:
            chart_type = "column"
        try:
            top_n = int(module.get("top_n", 8))
        except Exception:
            top_n = 8
        top_n = max(min_tn, min(top_n, max_tn))

        chart_title_tpl = ui_cfg.get("fallback_chart_title_template", "{dim}分布")
        cleaned_modules.append(
            {
                "dimension": dim,
                "title": str(module.get("title") or chart_title_tpl.format(dim=dim)),
                "chart_type": chart_type,
                "top_n": top_n,
                "insight": str(module.get("insight") or ""),
                "business_use": str(module.get("business_use") or ""),
                "priority": int(module.get("priority") or idx),
            }
        )
        used.add(dim)

    if not cleaned_modules:
        return fallback_visual_plan(dimensions, product_name, config)

    label_top_k = config.get("label_top_k", 4) if config else 4
    cleaned_modules = sorted(cleaned_modules, key=lambda x: x.get("priority", 999))[:max_modules]
    dashboard_title_tpl = ui_cfg.get("dashboard_title_template", "{product_name} 评论洞察可视化看板")
    plan["modules"] = cleaned_modules
    plan["dashboard_title"] = plan.get("dashboard_title") or dashboard_title_tpl.format(product_name=product_name)
    plan.setdefault("product_insights", {})
    return enrich_plan_with_details(plan, dimensions, config, label_top_k=label_top_k)


# ===================== Excel 看板生成 =====================
def write_merged(ws, row1: int, col1: int, row2: int, col2: int, value: Any, fmt) -> None:
    if row1 == row2 and col1 == col2:
        ws.write(row1, col1, value, fmt)
    else:
        ws.merge_range(row1, col1, row2, col2, value, fmt)


def write_detail_table(
    dashboard,
    start_row: int,
    start_col: int,
    detail_rows: List[Dict[str, Any]],
    header_fmt,
    normal_fmt,
    percent_fmt,
    max_rows: int = 5,
) -> int:
    """在图表下方写 Top 类别代表性标签明细表。返回写完后的下一行。"""
    write_merged(dashboard, start_row, start_col, start_row, start_col + 6, "代表性标签（Top类目）", header_fmt)
    r = start_row + 1
    write_merged(dashboard, r, start_col, r, start_col + 1, "类别", header_fmt)
    dashboard.write(r, start_col + 2, "次数", header_fmt)
    dashboard.write(r, start_col + 3, "占比", header_fmt)
    write_merged(dashboard, r, start_col + 4, r, start_col + 6, "代表性标签", header_fmt)

    for item in detail_rows[:max_rows]:
        r += 1
        write_merged(dashboard, r, start_col, r, start_col + 1, item.get("类别", ""), normal_fmt)
        dashboard.write_number(r, start_col + 2, float(item.get("次数", 0) or 0), normal_fmt)
        dashboard.write_number(r, start_col + 3, float(item.get("占比", 0) or 0), percent_fmt)
        write_merged(dashboard, r, start_col + 4, r, start_col + 6, item.get("代表性标签", ""), normal_fmt)
        dashboard.set_row(r, 32)
    return r + 1


def write_text_box(ws, row: int, col: int, text: str, fmt, width_cols: int = 6):
    """用合并单元格模拟文本卡片。"""
    ws.merge_range(row, col, row + 1, col + width_cols - 1, text, fmt)


def add_chart(
    workbook,
    dashboard_ws,
    data_ws_name: str,
    chart_type: str,
    title: str,
    first_row: int,
    last_row: int,
    chart_col: int,
    chart_row: int,
    chart_width: int = 520,
    chart_height: int = 300,
    chart_style: int = 10,
    donut_hole_size: int = 55,
):
    """在 Dashboard 中插入图表。"""
    if chart_type == "donut":
        chart = workbook.add_chart({"type": "doughnut"})
        chart.add_series(
            {
                "name": title,
                "categories": [data_ws_name, first_row, 1, last_row, 1],
                "values": [data_ws_name, first_row, 2, last_row, 2],
                "data_labels": {"percentage": True},
            }
        )
        chart.set_hole_size(donut_hole_size)
    elif chart_type == "bar":
        chart = workbook.add_chart({"type": "bar"})
        chart.add_series(
            {
                "name": title,
                "categories": [data_ws_name, first_row, 1, last_row, 1],
                "values": [data_ws_name, first_row, 2, last_row, 2],
                "data_labels": {"value": True},
            }
        )
        chart.set_x_axis({"name": "次数", "major_gridlines": {"visible": False}})
        chart.set_y_axis({"reverse": True})
    else:
        chart = workbook.add_chart({"type": "column"})
        chart.add_series(
            {
                "name": title,
                "categories": [data_ws_name, first_row, 1, last_row, 1],
                "values": [data_ws_name, first_row, 2, last_row, 2],
                "data_labels": {"value": True},
            }
        )
        chart.set_y_axis({"name": "次数", "major_gridlines": {"visible": False}})

    chart.set_title({"name": title})
    chart.set_legend({"position": "bottom"})
    chart.set_size({"width": chart_width, "height": chart_height})
    chart.set_style(chart_style)
    dashboard_ws.insert_chart(chart_row, chart_col, chart)


def create_dashboard_excel(
    dimensions: Dict[str, DimensionData],
    plan: Dict[str, Any],
    output_file: str,
    product_name: str,
    config: Optional[dict] = None,
    label_rows: int = 5,
):
    """生成最终 Excel 看板。"""
    layout_cfg = config.get("layout", {}) if config else {}
    colors = config.get("styles", {}).get("colors", {}) if config else {}
    fonts = config.get("styles", {}).get("fonts", {}) if config else {}
    ui_cfg = config.get("ui_text", {}) if config else {}

    # 快捷解引用
    dash_cfg = layout_cfg.get("dashboard", {})
    chart_cfg = layout_cfg.get("chart_data", {})
    plan_cfg = layout_cfg.get("plan_sheet", {})
    insight_cfg = layout_cfg.get("insight_sheet", {})

    cw = layout_cfg.get("chart_width", 520)
    ch = layout_cfg.get("chart_height", 260)
    cs = layout_cfg.get("chart_style", 10)
    dhs = layout_cfg.get("donut_hole_size", 55)

    with pd.ExcelWriter(output_file, engine="xlsxwriter") as writer:
        workbook = writer.book

        # -------- 格式 --------
        border_color = colors.get("border", "#E5E7EB")
        title_fmt = workbook.add_format({
            "bold": True, "font_size": fonts.get("title_size", 20),
            "font_color": colors.get("title_font", "#1F2937"),
            "align": "left", "valign": "vcenter",
        })
        subtitle_fmt = workbook.add_format({
            "font_size": fonts.get("subtitle_size", 10),
            "font_color": colors.get("subtitle_font", "#6B7280"),
            "align": "left",
        })
        card_title_fmt = workbook.add_format({
            "bold": True, "font_size": fonts.get("card_title_size", 11),
            "font_color": colors.get("card_title_font", "#374151"),
            "bg_color": colors.get("card_title_bg", "#F3F4F6"),
            "border": 1, "border_color": border_color,
            "align": "center", "valign": "vcenter",
        })
        card_value_fmt = workbook.add_format({
            "bold": True, "font_size": fonts.get("card_value_size", 18),
            "font_color": colors.get("card_value_font", "#111827"),
            "bg_color": colors.get("card_value_bg", "#FFFFFF"),
            "border": 1, "border_color": border_color,
            "align": "center", "valign": "vcenter",
        })
        header_fmt = workbook.add_format({
            "bold": True, "font_color": colors.get("header_font", "#FFFFFF"),
            "bg_color": colors.get("header_bg", "#374151"),
            "border": 1, "align": "center", "valign": "vcenter",
        })
        normal_fmt = workbook.add_format({
            "border": 1, "border_color": border_color, "valign": "top", "text_wrap": True,
        })
        percent_fmt = workbook.add_format({
            "num_format": "0.0%", "border": 1, "border_color": border_color, "align": "center",
        })
        insight_fmt = workbook.add_format({
            "text_wrap": True, "valign": "top",
            "font_color": colors.get("insight_font", "#374151"),
            "bg_color": colors.get("insight_bg", "#F9FAFB"),
            "border": 1, "border_color": border_color,
        })

        # -------- Dashboard --------
        dashboard = workbook.add_worksheet(dash_cfg.get("sheet_name", "Dashboard"))
        dashboard.hide_gridlines(2)
        dashboard.set_column("A:A", dash_cfg.get("col_A", 3))
        dashboard.set_column("B:H", dash_cfg.get("col_B_to_H", 13))
        dashboard.set_column("I:I", dash_cfg.get("col_I", 3))
        dashboard.set_column("J:P", dash_cfg.get("col_J_to_P", 13))
        dashboard.set_row(0, dash_cfg.get("row_height_0", 32))

        dashboard_title_tpl = ui_cfg.get("dashboard_title_template", "{product_name} 评论洞察可视化看板")
        dashboard.merge_range(
            dash_cfg.get("title_col_range", "B1:P1"),
            plan.get("dashboard_title", dashboard_title_tpl.format(product_name=product_name)),
            title_fmt,
        )
        dashboard.merge_range(
            dash_cfg.get("subtitle_col_range", "B2:P2"),
            dash_cfg.get("subtitle_text", "图表展示分布，图表下方展示 Top 类别与代表性标签，用于直接支持产品开发、Listing 卖点和差评优化判断。"),
            subtitle_fmt,
        )

        # KPI 卡片
        total_dimensions = len(dimensions)
        total_categories = sum(len(d.categories) for d in dimensions.values())
        total_mentions = sum(float(d.categories["次数"].sum()) for d in dimensions.values())
        module_count = len(plan.get("modules", []))
        kpi_labels = ui_cfg.get("kpi_labels", ["分析维度", "归类类别", "统计次数", "看板模块"])
        kpis = list(zip(kpi_labels, [total_dimensions, total_categories, int(total_mentions), module_count]))
        card_positions = dash_cfg.get("kpi_card_positions", [[3, 1], [3, 5], [3, 9], [3, 13]])
        title_cols = dash_cfg.get("kpi_card_title_cols", 2)
        for (label, value), (r, c) in zip(kpis, card_positions):
            dashboard.merge_range(r, c, r, c + title_cols, label, card_title_fmt)
            dashboard.merge_range(r + 1, c, r + 2, c + title_cols, value, card_value_fmt)

        # -------- 图表数据 --------
        chart_data_ws = workbook.add_worksheet(chart_cfg.get("sheet_name", "图表数据"))
        for col_def in chart_cfg.get("columns", [
            {"col": "A:A", "width": 14}, {"col": "B:B", "width": 24},
            {"col": "C:C", "width": 10}, {"col": "D:D", "width": 10}, {"col": "E:E", "width": 60},
        ]):
            chart_data_ws.set_column(col_def["col"], col_def["width"])
        chart_data_ws.write_row(0, 0, chart_cfg.get("headers", ["维度", "类别", "次数", "占比", "代表性标签"]), header_fmt)

        # 动态计算图表布局
        start_row = layout_cfg.get("start_row", 7)
        start_col = layout_cfg.get("start_col", 1)
        col_spacing = layout_cfg.get("col_spacing", 8)
        rows_per_chart = layout_cfg.get("rows_per_chart", 29)
        max_modules = config.get("fallback_rules", {}).get("max_modules", 6) if config else 6
        modules_to_render = plan.get("modules", [])[:max_modules]
        chart_positions = [
            (start_row + (i // 2) * rows_per_chart, start_col + (i % 2) * col_spacing)
            for i in range(len(modules_to_render))
        ]

        chart_row_cursor = 1
        chart_title_tpl = ui_cfg.get("fallback_chart_title_template", "{dim}分布")
        insight_tpl = ui_cfg.get("insight_template", "核心判断：{insight}\n决策用途：{business_use}")

        for idx, module in enumerate(modules_to_render):
            dim = module["dimension"]
            data = dimensions[dim]
            top_n = int(module.get("top_n", 8))
            detail_rows = module.get("detail_rows") or build_detail_rows(data, top_n=top_n)
            top_df = pd.DataFrame(detail_rows).head(top_n)
            if top_df.empty:
                continue
            top_df["次数"] = to_number(top_df["次数"])

            # 写入图表数据
            first_data_row = chart_row_cursor
            for _, row in top_df.iterrows():
                chart_data_ws.write(chart_row_cursor, 0, dim, normal_fmt)
                chart_data_ws.write(chart_row_cursor, 1, row["类别"], normal_fmt)
                chart_data_ws.write_number(chart_row_cursor, 2, float(row["次数"]), normal_fmt)
                chart_data_ws.write_number(chart_row_cursor, 3, float(row["占比"]), percent_fmt)
                chart_data_ws.write(chart_row_cursor, 4, str(row.get("代表性标签", "")), normal_fmt)
                chart_row_cursor += 1
            last_data_row = chart_row_cursor - 1
            chart_row_cursor += 2

            # 插入图表
            chart_anchor_row, chart_anchor_col = chart_positions[idx]
            module_title = module.get("title", chart_title_tpl.format(dim=dim))
            write_merged(dashboard, chart_anchor_row - 1, chart_anchor_col,
                         chart_anchor_row - 1, chart_anchor_col + 6, module_title, card_title_fmt)
            add_chart(
                workbook=workbook,
                dashboard_ws=dashboard,
                data_ws_name=chart_cfg.get("sheet_name", "图表数据"),
                chart_type=module.get("chart_type", "column"),
                title=module_title,
                first_row=first_data_row,
                last_row=last_data_row,
                chart_col=chart_anchor_col,
                chart_row=chart_anchor_row,
                chart_width=cw,
                chart_height=ch,
                chart_style=cs,
                donut_hole_size=dhs,
            )

            # 代表性标签明细表
            detail_start = chart_anchor_row + 14
            next_row = write_detail_table(
                dashboard, detail_start, chart_anchor_col, detail_rows,
                header_fmt, normal_fmt, percent_fmt, max_rows=label_rows,
            )
            insight_text = insight_tpl.format(
                insight=module.get("insight", ""),
                business_use=module.get("business_use", ""),
            )
            write_merged(dashboard, next_row, chart_anchor_col, next_row + 2, chart_anchor_col + 6,
                         insight_text, insight_fmt)
            dashboard.set_row(next_row, 38)
            dashboard.set_row(next_row + 1, 38)
            dashboard.set_row(next_row + 2, 38)

        # -------- AI可视化方案 --------
        plan_ws = workbook.add_worksheet(plan_cfg.get("sheet_name", "AI可视化方案"))
        plan_ws.set_column("A:A", 14)
        plan_ws.set_column("B:B", 22)
        plan_ws.set_column("C:C", 12)
        plan_ws.set_column("D:D", 10)
        plan_ws.set_column("E:F", 48)
        plan_ws.write_row(0, 0, plan_cfg.get("headers", ["维度", "标题", "图表类型", "TopN", "核心判断", "业务用途"]), header_fmt)
        for r, module in enumerate(plan.get("modules", []), start=1):
            plan_ws.write(r, 0, module.get("dimension"), normal_fmt)
            plan_ws.write(r, 1, module.get("title"), normal_fmt)
            plan_ws.write(r, 2, module.get("chart_type"), normal_fmt)
            plan_ws.write(r, 3, module.get("top_n"), normal_fmt)
            plan_ws.write(r, 4, module.get("insight"), normal_fmt)
            plan_ws.write(r, 5, module.get("business_use"), normal_fmt)
        plan_ws.freeze_panes(1, 0)

        # -------- 产品洞察 --------
        insight_ws = workbook.add_worksheet(insight_cfg.get("sheet_name", "产品洞察"))
        insight_ws.set_column("A:A", 18)
        insight_ws.set_column("B:B", 90)
        insight_ws.write_row(0, 0, insight_cfg.get("headers", ["项目", "内容"]), header_fmt)
        insights = plan.get("product_insights", {}) or {}
        rows = [("产品定位判断", insights.get("positioning", ""))]
        for item in insights.get("selling_points", []) or []:
            rows.append(("可转化卖点", item))
        for item in insights.get("improvement_priorities", []) or []:
            rows.append(("改进优先级", item))
        if len(rows) == 1 and not rows[0][1]:
            rows.append(("说明", insight_cfg.get("fallback_text", "未调用 AI 或 AI 未返回产品洞察，可依据 Dashboard 和图表数据自行补充。")))
        for r, (k, v) in enumerate(rows, start=1):
            insight_ws.write(r, 0, k, normal_fmt)
            insight_ws.write(r, 1, v, insight_fmt)
        insight_ws.freeze_panes(1, 0)

        # -------- 清洗后的维度数据 --------
        cleaned_suffix = layout_cfg.get("cleaned_sheet_suffix", "_清洗统计")
        for dim, data in dimensions.items():
            sheet_name = safe_sheet_name(f"{dim}{cleaned_suffix}")
            out_df = data.categories.copy()
            # 附加每个类别的 Top 原始标签
            out_df["Top原始标签"] = out_df["类别"].map(
                lambda c: "；".join(get_top_raw_labels(data, c, top_k=6))
            )
            out_df.to_excel(writer, sheet_name=sheet_name, index=False)
            ws = writer.sheets[sheet_name]
            ws.set_column("A:A", 24)
            ws.set_column("B:B", 10)
            ws.set_column("C:C", 36)
            ws.set_column("D:D", 10)
            ws.set_column("E:E", 60)
            ws.freeze_panes(1, 0)
            for col_num, value in enumerate(out_df.columns.values):
                ws.write(0, col_num, value, header_fmt)


# ===================== 主流程 =====================
def run(args):
    config = load_dashboard_config(args.config)
    api_cfg = config.get("api", {})
    rules_cfg = config.get("fallback_rules", {})

    label_top_k = config.get("label_top_k", 4)
    label_rows = config.get("label_rows", 5)

    dimensions = load_ai_summary_excel(args.input, config)

    ai_top_n = args.ai_top_n
    if ai_top_n is None:
        ai_top_n = rules_cfg.get("default_ai_top_n", 12)
    data_payload = build_ai_input_payload(dimensions, top_n=ai_top_n, label_top_k=label_top_k)

    api_env = args.api_env
    if api_env is None:
        api_env = api_cfg.get("api_key_env", "SILICONFLOW_API_KEY")
    api_key = os.getenv(api_env)

    base_url = args.base_url
    if base_url is None:
        base_url = api_cfg.get("base_url", "https://api.siliconflow.cn/v1")
    model = args.model
    if model is None:
        model = api_cfg.get("model", "deepseek-ai/DeepSeek-V3")

    plan = None
    if not args.no_ai:
        try:
            plan = call_ai_for_visual_plan(
                data_payload=data_payload,
                product_name=args.product_name,
                api_key=api_key,
                base_url=base_url,
                model=model,
                config=config,
            )
        except Exception as exc:
            print(f"[提示] AI 可视化方案生成失败，已切换为规则方案。原因：{exc}")

    if not plan:
        plan = fallback_visual_plan(dimensions, args.product_name, config, label_top_k=label_top_k)

    plan = validate_plan(plan, dimensions, args.product_name, config)
    create_dashboard_excel(dimensions, plan, args.output, args.product_name, config, label_rows=label_rows)

    print("处理完成：")
    print(f"输入文件：{args.input}")
    print(f"输出文件：{args.output}")
    print("已生成 sheet：Dashboard、图表数据、AI可视化方案、产品洞察、各维度清洗统计")


def parse_args():
    parser = argparse.ArgumentParser(description="产品评论 AI 总结结果自动可视化脚本")
    parser.add_argument("--input", required=True, help="输入 Excel 文件路径，例如：评论数据_xxx_AI总结.xlsx")
    parser.add_argument("--output", required=True, help="输出 Excel 看板文件路径")
    parser.add_argument("--product-name", default="该产品", help="产品名称，用于看板标题和 AI 判断")
    parser.add_argument("--config", default="dashboard_config.json", help="可视化看板配置文件路径")
    parser.add_argument("--api-env", default=None, help="API Key 环境变量名，默认从配置文件读取")
    parser.add_argument("--base-url", default=None, help="OpenAI 兼容接口 Base URL，默认从配置文件读取")
    parser.add_argument("--model", default=None, help="模型名称，默认从配置文件读取")
    parser.add_argument("--ai-top-n", type=int, default=None, help="传给 AI 的每个维度最大类别数，默认从配置文件读取")
    parser.add_argument("--no-ai", action="store_true", help="不调用 AI，直接使用规则方案生成看板")
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
