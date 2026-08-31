# -*- coding: utf-8 -*-
"""
comments_step_2.py

第2步：合并 step1 的提取结果，统计标签，并生成归类总结。

核心策略：
1. 优先读取 product_configs.json 中 fields[].stat_strategy，决定每个字段的统计方式。
2. normalize_only 字段：只做标签标准化和直接统计，适合目标国家、颜色、尺寸、接口类型等字段。
3. objective_auto 字段：AI 自动生成类别 + AI 二级主题，适合使用场景、设备、用户身份等客观字段。
4. subjective_* 字段：使用“通用一级分类 + AI 二级主题归纳 + AI 自检纠偏”的中间方案，适合正向关注点、负向关注点、改进需求、用户关键任务等字段。
5. 如果字段没有配置 stat_strategy，则使用字段名关键词兜底判断；仍判断不出来，默认 objective_auto。

该脚本不把分类体系写死到某一个品类，只固定跨品类通用一级分类，适合后续复用到多个电商品类。
"""

import os
import re
import ast
import json
import time
from collections import Counter, defaultdict, OrderedDict
from typing import List, Tuple, Union, Dict, Any, Optional

import pandas as pd
from openai import OpenAI
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

# ================= 环境变量配置 =================
API_ENV_NAME = os.getenv("API_ENV_NAME", "SILICONFLOW_API_KEY")
API_KEY = os.getenv(API_ENV_NAME) or os.getenv("API_KEY")
if not API_KEY:
    raise ValueError(
        f"未检测到环境变量 {API_ENV_NAME} 或 API_KEY，请先设置后再运行。")

BASE_URL = os.getenv("BASE_URL", "https://api.siliconflow.cn/v1")
MODEL = os.getenv("MODEL_NAME", "deepseek-ai/DeepSeek-V3")

INPUT_FILE = os.getenv("STEP1_OUTPUT_FILE")
OUTPUT_FILE = os.getenv("STEP2_OUTPUT_FILE")
CURRENT_PRODUCT = os.getenv("CURRENT_PRODUCT")
CONFIG_FILE = os.getenv("CONFIG_FILE", "./product_configs.json")

TARGET_SHEETS = [
    s.strip() for s in os.getenv("TARGET_SHEETS", "").split(",") if s.strip()
]
SKIP_FAILED_ROWS = os.getenv("STEP2_SKIP_FAILED_ROWS", "1").strip().lower() not in (
    "0", "false", "no", "n",
)

if not INPUT_FILE:
    raise ValueError("未检测到环境变量 STEP1_OUTPUT_FILE")
if not OUTPUT_FILE:
    raise ValueError("未检测到环境变量 STEP2_OUTPUT_FILE")
if not CURRENT_PRODUCT:
    raise ValueError("未检测到环境变量 CURRENT_PRODUCT")

if not os.path.exists(CONFIG_FILE):
    raise FileNotFoundError(f"配置文件不存在：{CONFIG_FILE}")

with open(CONFIG_FILE, "r", encoding="utf-8") as f:
    PRODUCT_CONFIGS = json.load(f)

if CURRENT_PRODUCT not in PRODUCT_CONFIGS:
    raise ValueError(f"未找到品类配置：{CURRENT_PRODUCT}")

product_config = PRODUCT_CONFIGS[CURRENT_PRODUCT]

FIELDS = product_config.get("stats_fields")
if not FIELDS:
    FIELDS = [
        field["excel_col"]
        for field in product_config.get("fields", [])
        if field.get("excel_col") != "翻译后评论"
    ]

if not FIELDS:
    raise ValueError(f"{CURRENT_PRODUCT} 未配置可统计字段 stats_fields")

TEMPERATURE = float(os.getenv("STEP2_TEMPERATURE", "0.2"))
MAX_TOKENS = int(os.getenv("STEP2_MAX_TOKENS", "3500"))
SLEEP_SECONDS = float(os.getenv("STEP2_SLEEP_SECONDS", "0.5"))
MAX_RETRIES = int(os.getenv("STEP2_MAX_RETRIES", "3"))

NORMALIZE_BATCH_SIZE = int(os.getenv("NORMALIZE_BATCH_SIZE", "80"))
CLASSIFY_BATCH_SIZE = int(os.getenv("CLASSIFY_BATCH_SIZE", "80"))
ENABLE_SELF_CHECK = os.getenv("ENABLE_SELF_CHECK", "1").strip().lower() not in ("0", "false", "no", "n")
SELF_CHECK_MAX_LABELS = int(os.getenv("SELF_CHECK_MAX_LABELS", "180"))

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

# ================= 通用一级分类体系 =================
# 这部分是跨品类通用分类，不绑定某一个具体品类。
UNIVERSAL_TAXONOMIES: Dict[str, List[Dict[str, str]]] = {
    "negative": [
        {
            "category": "功能问题",
            "definition": "产品核心功能不可用、功能缺失、功能失效，或核心功能没有按用户预期工作。",
            "examples": "无法使用、核心功能失效、不触发、无法开启、无法关闭、缺少某功能",
        },
        {
            "category": "性能体验问题",
            "definition": "产品能工作，但速度、延迟、精度、效果、效率、响应表现不佳。",
            "examples": "启动慢、延迟长、效果差、效率低、响应不稳定、清理不干净",
        },
        {
            "category": "兼容适配问题",
            "definition": "产品与设备、接口、规格、系统、尺寸、场景或用户原有配置不匹配。",
            "examples": "不兼容、无法适配、接口不匹配、功率不匹配、场景不适用",
        },
        {
            "category": "可靠性与寿命问题",
            "definition": "产品短期损坏、寿命短、长期不稳定、零部件失效或做工耐用性不足。",
            "examples": "短期失效、寿命短、开关损坏、继电器故障、插座不通电、不耐用",
        },
        {
            "category": "安全与负载问题",
            "definition": "与过载、跳闸、发热、烧焦、火花、漏电、电流不足、功率不足、安全隐患相关的问题。",
            "examples": "容易跳闸、过载、发热、烧焦、火花、电流不足、工具断电、安全隐患",
        },
        {
            "category": "结构设计问题",
            "definition": "与尺寸、线长、插孔、接口、安装、固定、材质、外壳、标识、布局等实体结构相关的问题。",
            "examples": "线太短、插孔太近、插头遮挡、无法壁挂、标识不清、外壳脆弱",
        },
        {
            "category": "使用便利性问题",
            "definition": "与操作麻烦、学习成本高、需要频繁调整或插拔、说明不清、流程不顺相关的问题。",
            "examples": "使用不便、需要频繁插拔、说明书不清楚、操作麻烦、设置复杂",
        },
        {
            "category": "价格与性价比问题",
            "definition": "与价格高、性价比低、不值这个价、价值感不足相关的问题。",
            "examples": "价格太高、价格过高、性价比低、不值这个价",
        },
        {
            "category": "描述与售后问题",
            "definition": "与产品描述不符、宣传不准确、保修不足、客服、退货、售后响应相关的问题。",
            "examples": "产品描述不符、虚假宣传、售后差、退货不便、保修不足",
        },
        {
            "category": "其他问题",
            "definition": "无法明确归入以上类别的问题。",
            "examples": "其他零散问题",
        },
    ],
    "positive": [
        {
            "category": "功能有效",
            "definition": "核心功能可用，并且确实解决了用户问题。",
            "examples": "功能好用、自动工作、能解决问题、效果符合预期",
        },
        {
            "category": "性能表现好",
            "definition": "速度、响应、精度、效果、效率等表现较好。",
            "examples": "响应快、触发准确、效果好、效率高、清理干净",
        },
        {
            "category": "使用方便",
            "definition": "安装、设置、操作、日常使用过程简单省事。",
            "examples": "安装简单、使用方便、省事、无需手动操作、节省时间",
        },
        {
            "category": "兼容适配好",
            "definition": "能适配用户的设备、接口、规格或使用场景。",
            "examples": "适合车库、适合木工工具、兼容设备、适配场景",
        },
        {
            "category": "设计合理",
            "definition": "结构、布局、尺寸、外观、材质、安装方式等设计让用户满意。",
            "examples": "设计实用、布局合理、线长合适、做工扎实、安装孔好用",
        },
        {
            "category": "可靠耐用",
            "definition": "产品稳定、耐用、质量可靠、长期使用表现好。",
            "examples": "运行稳定、质量好、耐用、长期可靠",
        },
        {
            "category": "价格价值好",
            "definition": "价格合理、性价比高、物有所值。",
            "examples": "价格划算、性价比高、物有所值",
        },
        {
            "category": "服务体验好",
            "definition": "与物流、包装、客服、售后、保修相关的正面体验。",
            "examples": "发货快、包装好、客服好、售后好",
        },
        {
            "category": "其他正向点",
            "definition": "无法明确归入以上类别的正向反馈。",
            "examples": "其他满意点",
        },
    ],
    "improvement": [
        {
            "category": "功能扩展",
            "definition": "希望增加新功能、新模式、新控制方式或更多功能选项。",
            "examples": "增加遥控、增加手动开关、增加旁路开关、增加多设备控制",
        },
        {
            "category": "性能优化",
            "definition": "希望提升速度、响应、精度、效果、效率、延时、阈值等表现。",
            "examples": "缩短启动延迟、可调延时、提高灵敏度、减少误触发、提升清理效果",
        },
        {
            "category": "兼容适配优化",
            "definition": "希望适配更多设备、接口、规格、功率、尺寸、系统或场景。",
            "examples": "支持更多设备、适配低功率工具、适配高功率设备、明确适用范围",
        },
        {
            "category": "安全可靠优化",
            "definition": "希望提升安全性、负载能力、稳定性、寿命、耐用性和质量可靠性。",
            "examples": "支持20A、支持双回路、提升负载能力、增加过载保护、提升继电器寿命",
        },
        {
            "category": "结构设计优化",
            "definition": "希望改进线长、插孔、接口、尺寸、外壳、材质、标识、安装固定方式。",
            "examples": "加长电源线、优化插孔间距、增加壁挂孔、改进标识、提升外壳强度",
        },
        {
            "category": "易用性优化",
            "definition": "希望降低学习成本、简化操作流程、减少误用、改进说明书或提示。",
            "examples": "改进说明书、增加连接图示、区分插口、简化设置",
        },
        {
            "category": "价格服务优化",
            "definition": "希望降低价格、提升保修、改善客服、退货和售后服务。",
            "examples": "降低价格、延长保修、改善售后、提高退货便利性",
        },
        {
            "category": "其他改进",
            "definition": "无法明确归入以上类别的改进需求。",
            "examples": "其他改进建议",
        },
    ],
    "task": [
        {
            "category": "完成功能任务",
            "definition": "用户希望完成某个明确功能或实际操作任务。",
            "examples": "自动控制设备、清理粉尘、检测问题、连接设备、供电控制",
        },
        {
            "category": "提升效率任务",
            "definition": "用户希望节省时间、减少步骤、提升工作效率或作业连续性。",
            "examples": "减少手动操作、提升工作效率、避免频繁走动、简化工作流程",
        },
        {
            "category": "改善体验任务",
            "definition": "用户希望使用过程更方便、更舒适、更顺手。",
            "examples": "使用更省事、操作更方便、减少麻烦、提升工作体验",
        },
        {
            "category": "适配场景任务",
            "definition": "用户希望产品适配某个具体场景、设备组合或空间布局。",
            "examples": "适配车库、适配工作台、适配工具组合、适配装修现场",
        },
        {
            "category": "安全可靠任务",
            "definition": "用户希望降低风险、避免故障、保证稳定和安全。",
            "examples": "避免跳闸、降低过载风险、保证长期稳定、提高安全性",
        },
        {
            "category": "价值回报任务",
            "definition": "用户希望获得性价比、节省成本、减少额外支出或获得更好的购买价值。",
            "examples": "节省成本、替代更贵方案、提高性价比",
        },
        {
            "category": "其他任务",
            "definition": "无法明确归入以上类别的用户任务。",
            "examples": "其他任务",
        },
    ],
}

SUBJECTIVE_FIELD_KEYWORDS = {
    "negative": ["用户负向关注点", "负向关注点", "负面关注点", "负向", "负面", "痛点", "不满意"],
    "positive": ["用户正向关注点", "正向关注点", "正面关注点", "正向", "正面", "满意点"],
    "improvement": ["改进需求", "改进建议", "优化需求", "优化建议"],
    "task": ["用户关键任务", "关键任务", "用户任务", "购买任务"],
}

# ================= 通用工具函数 =================
def get_taxonomy_type(field_name: str) -> Optional[str]:
    for tax_type, keywords in SUBJECTIVE_FIELD_KEYWORDS.items():
        if any(k in field_name for k in keywords):
            return tax_type
    return None

# ================= 字段统计策略 =================
# 优先从 product_configs.json 的 fields[].stat_strategy 读取。
# 如果没有配置，再用字段名关键词做兜底判断。
# 支持的策略：
# - normalize_only：只做标签标准化和直接统计，不做AI大类归类。
# - objective_auto：客观字段，AI自动归类 + 二级主题。
# - subjective_positive：正向关注点，通用一级分类 + 二级主题。
# - subjective_negative：负向关注点，通用一级分类 + 自检纠偏 + 二级主题。
# - subjective_improvement：改进需求，通用一级分类 + 二级主题。
# - subjective_task：用户关键任务，通用一级分类 + 二级主题。
STRATEGY_ALIASES = {
    "normalize": "normalize_only",
    "normalize_only": "normalize_only",
    "direct": "normalize_only",
    "direct_count": "normalize_only",
    "直接统计": "normalize_only",
    "只标准化": "normalize_only",

    "auto": "objective_auto",
    "objective": "objective_auto",
    "objective_auto": "objective_auto",
    "客观自动归类": "objective_auto",

    "positive": "subjective_positive",
    "subjective_positive": "subjective_positive",
    "正向": "subjective_positive",

    "negative": "subjective_negative",
    "subjective_negative": "subjective_negative",
    "负向": "subjective_negative",

    "improvement": "subjective_improvement",
    "subjective_improvement": "subjective_improvement",
    "改进": "subjective_improvement",

    "task": "subjective_task",
    "subjective_task": "subjective_task",
    "任务": "subjective_task",
}

SUBJECTIVE_STRATEGY_TO_TAXONOMY = {
    "subjective_positive": "positive",
    "subjective_negative": "negative",
    "subjective_improvement": "improvement",
    "subjective_task": "task",
}


def canonicalize_strategy(strategy: Optional[str]) -> Optional[str]:
    if not strategy:
        return None
    s = str(strategy).strip()
    if not s:
        return None
    return STRATEGY_ALIASES.get(s, STRATEGY_ALIASES.get(s.lower(), s))


def get_field_config(field_name: str, config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """根据 Excel 列名或字段 key 找到 product_configs.json 中的字段配置。"""
    for field in config.get("fields", []):
        if field.get("excel_col") == field_name or field.get("key") == field_name:
            return field
    return None


def get_field_strategy(field_name: str, config: Dict[str, Any]) -> str:
    """
    获取字段统计策略。

    优先级：
    1. fields[].stat_strategy / fields[].strategy / fields[].stat_mode
    2. product_config.field_strategies 或 product_config.stats_strategies
    3. 字段名关键词兜底判断主观字段
    4. 默认 objective_auto
    """
    field_conf = get_field_config(field_name, config)
    if field_conf:
        for key in ("stat_strategy", "strategy", "stat_mode"):
            strategy = canonicalize_strategy(field_conf.get(key))
            if strategy:
                return strategy

    for dict_key in ("field_strategies", "stats_strategies", "stat_strategies"):
        strategies = config.get(dict_key, {})
        if isinstance(strategies, dict):
            strategy = canonicalize_strategy(strategies.get(field_name))
            if strategy:
                return strategy
            if field_conf:
                strategy = canonicalize_strategy(strategies.get(field_conf.get("key")))
                if strategy:
                    return strategy

    taxonomy_type = get_taxonomy_type(field_name)
    if taxonomy_type == "positive":
        return "subjective_positive"
    if taxonomy_type == "negative":
        return "subjective_negative"
    if taxonomy_type == "improvement":
        return "subjective_improvement"
    if taxonomy_type == "task":
        return "subjective_task"

    return "objective_auto"


def strategy_to_taxonomy_type(strategy: str) -> Optional[str]:
    return SUBJECTIVE_STRATEGY_TO_TAXONOMY.get(strategy)


def taxonomy_to_prompt(taxonomy: List[Dict[str, str]]) -> str:
    lines = []
    for i, item in enumerate(taxonomy, start=1):
        lines.append(
            f"{i}. {item['category']}：{item['definition']} 典型例子：{item.get('examples', '')}"
        )
    return "\n".join(lines)


def parse_cell(cell) -> List[str]:
    """读取 Excel 单元格中的列表标签。"""
    if pd.isna(cell):
        return []
    s = str(cell).strip()
    if s == "" or s in ("[]", "nan", "None", "null"):
        return []

    if s.startswith("[") and s.endswith("]"):
        try:
            value = ast.literal_eval(s)
            if isinstance(value, list):
                return [str(x).strip() for x in value if str(x).strip()]
        except Exception:
            inner = s[1:-1]
            if inner.strip():
                return [x.strip().strip('"').strip("'") for x in inner.split(",") if x.strip()]
            return []

    if any(sep in s for sep in ["；", ";", "、", "|"]):
        return [x.strip() for x in re.split(r"[；;、|]", s) if x.strip()]

    return [s]


def merge_sheets(input_file: str, target_sheets: List[str]) -> pd.DataFrame:
    with pd.ExcelFile(input_file) as xls:
        if target_sheets:
            existing = [s for s in target_sheets if s in xls.sheet_names]
        else:
            existing = list(xls.sheet_names)
        if not existing:
            raise ValueError(f"未找到目标 sheets: {target_sheets}，实际有 {xls.sheet_names}")
        dfs = []
        for sheet in existing:
            df = pd.read_excel(xls, sheet_name=sheet)
            if SKIP_FAILED_ROWS and "_处理状态" in df.columns:
                status = df["_处理状态"].fillna("").astype(str).str.strip()
                failed_mask = ~status.isin(("", "成功"))
                failed_count = int(failed_mask.sum())
                if failed_count:
                    print(
                        f"   工作表 '{sheet}' 跳过 {failed_count} 条失败/停止记录，"
                        "避免不完整数据进入汇总。"
                    )
                    df = df.loc[~failed_mask].copy()
                # 状态列仅用于 Step 1 质量门槛，不进入正式汇总结果。
                df = df.drop(columns=["_处理状态"])
            df["星级"] = sheet
            dfs.append(df)
    return pd.concat(dfs, ignore_index=True)


def build_raw_stats(df: pd.DataFrame, field: str) -> List[Tuple[Union[str, List[str]], int]]:
    counter = Counter()
    for cell in df[field]:
        items = parse_cell(cell)
        if not items:
            continue
        for item in items:
            counter[item] += 1
    return [(k, v) for k, v in counter.items()]


def extract_json_any(text: str) -> Any:
    """提取模型输出中的 JSON 对象或数组。"""
    if text is None:
        raise ValueError("模型返回为空")
    text = str(text).strip()
    text = re.sub(r'^```json\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'^```\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    text = text.strip()

    try:
        return json.loads(text)
    except Exception:
        pass

    starts = [(text.find('{'), '{', '}'), (text.find('['), '[', ']')]
    starts = [x for x in starts if x[0] != -1]
    if not starts:
        raise ValueError("未找到 JSON")
    start, open_ch, close_ch = min(starts, key=lambda x: x[0])
    end = text.rfind(close_ch)
    if end <= start:
        raise ValueError("JSON 边界异常")

    json_str = text[start:end + 1]
    json_str = re.sub(r',\s*}', '}', json_str)
    json_str = re.sub(r',\s*]', ']', json_str)
    return json.loads(json_str)


def call_ai(prompt: str, max_tokens: int = MAX_TOKENS, temperature: float = TEMPERATURE) -> str:
    """统一调用 AI，带重试。"""
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            last_error = e
            print(f"[第 {attempt}/{MAX_RETRIES} 次失败] AI调用错误: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(1.2 * attempt)
    raise RuntimeError(f"AI 调用失败: {last_error}")


# ================= 标签标准化 =================
def flatten_stats(data: List[Tuple[Union[str, List[str]], int]], split_multi: bool = True) -> List[Dict[str, Any]]:
    """把原始统计转为统一结构。"""
    processed = []
    for tag, cnt in data:
        if isinstance(tag, (list, tuple)) and split_multi:
            for sub in tag:
                sub = str(sub).strip()
                if sub:
                    processed.append({"label": sub, "count": int(cnt)})
        else:
            label = " + ".join(tag) if isinstance(tag, (list, tuple)) else str(tag)
            label = label.strip()
            if label:
                processed.append({"label": label, "count": int(cnt)})

    merged = OrderedDict()
    for item in processed:
        key = item["label"]
        if key not in merged:
            merged[key] = {"label": key, "count": 0}
        merged[key]["count"] += item["count"]

    unique_items = list(merged.values())
    unique_items.sort(key=lambda x: x["count"], reverse=True)
    return unique_items


def ai_standardize_labels(labels_info: List[Dict[str, Any]], field_name: str) -> Dict[str, str]:
    """
    AI 标签标准化：把同义/近义标签合并成一个标准标签。
    返回 mapping: 原标签 -> 标准标签。
    """
    if not labels_info:
        return {}

    if len(labels_info) > NORMALIZE_BATCH_SIZE:
        mapping = {}
        for i in range(0, len(labels_info), NORMALIZE_BATCH_SIZE):
            batch = labels_info[i:i + NORMALIZE_BATCH_SIZE]
            mapping.update(ai_standardize_labels(batch, field_name))
            time.sleep(SLEEP_SECONDS)
        return mapping

    prompt = f"""
你是一个跨品类电商评论标签标准化专家。

下面是“{field_name}”字段下的原始标签及出现次数。请把语义相同或高度近似的标签统一成一个“标准标签”。

要求：
- 输出必须是 JSON 对象，格式为 {{"原标签": "标准标签"}}。
- 标准标签必须是简体中文短标签，尽量 2-10 个字。
- 只合并明显同义或高度近义的标签，不要过度合并不同问题。
- 例如“线太短”和“电源线太短”可统一为“电源线太短”；“启动延迟明显”和“延时关闭太长”不能合并。
- 每个输入标签都必须出现在 JSON 键中。
- 不要输出解释文字。

标签列表：
{json.dumps(labels_info, ensure_ascii=False, indent=2)}
"""
    content = call_ai(prompt, max_tokens=2500, temperature=0.1)
    data = extract_json_any(content)
    if not isinstance(data, dict):
        raise ValueError("标签标准化结果不是 JSON 对象")

    mapping = {}
    for item in labels_info:
        raw = str(item["label"]).strip()
        norm = str(data.get(raw, raw)).strip()
        mapping[raw] = norm or raw
    return mapping


def apply_normalization(labels_info: List[Dict[str, Any]], mapping: Dict[str, str]) -> List[Dict[str, Any]]:
    merged = OrderedDict()
    for item in labels_info:
        raw = item["label"]
        norm = mapping.get(raw, raw)
        if norm not in merged:
            merged[norm] = {"label": norm, "count": 0, "raw_labels": []}
        merged[norm]["count"] += int(item["count"])
        merged[norm]["raw_labels"].append({"label": raw, "count": int(item["count"])})

    result = list(merged.values())
    result.sort(key=lambda x: x["count"], reverse=True)
    return result


# ================= 客观字段：AI自动归类 =================
def ai_generate_categories(labels_info: List[dict], field_name: str) -> List[str]:
    if not labels_info:
        return ["其他"]

    prompt = f"""
你是一个跨品类电商评论数据分析专家。下面列出了“{field_name}”字段中的高频标准标签及出现次数。
请根据这些标签的语义，自动归纳出 3到8个 最合适的类别名称。

要求：
- 类别之间尽量互斥，覆盖主要主题。
- 类别名称简短、清晰，使用简体中文。
- 不要使用过于宽泛且边界重叠的类别，例如同时出现“性能问题/功能问题/质量问题”这类难以区分的组合。
- 不要输出解释文字，只输出 JSON 数组，例如：["类别1", "类别2", "类别3"]。

标签列表：
{json.dumps(labels_info, ensure_ascii=False, indent=2)}
"""
    content = call_ai(prompt, max_tokens=600, temperature=0.25)
    data = extract_json_any(content)
    if not isinstance(data, list) or not data:
        return ["其他"]
    categories = [str(x).strip() for x in data if str(x).strip()]
    return categories or ["其他"]


def ai_classify_with_categories(labels_info: List[dict], categories: List[str], field_name: str) -> Dict[str, List[Tuple[str, int]]]:
    if not labels_info:
        return {}
    if len(labels_info) > CLASSIFY_BATCH_SIZE:
        all_result = defaultdict(list)
        for i in range(0, len(labels_info), CLASSIFY_BATCH_SIZE):
            batch = labels_info[i:i + CLASSIFY_BATCH_SIZE]
            batch_result = ai_classify_with_categories(batch, categories, field_name)
            for cat, items in batch_result.items():
                all_result[cat].extend(items)
            time.sleep(SLEEP_SECONDS)
        return dict(all_result)

    prompt = f"""
请将以下“{field_name}”字段的标准标签归类到给定类别中。只能使用下面列出的类别，不能新增类别。

类别列表：
{json.dumps(categories, ensure_ascii=False, indent=2)}

输出 JSON 对象，键为类别名，值为该类别下的 [标签, 次数] 数组。

示例输出：
{{
  "场景类型A": [["标签1", 86], ["标签2", 30]],
  "场景类型B": [["标签3", 52]]
}}

标签列表：
{json.dumps(labels_info, ensure_ascii=False, indent=2)}

要求：
- 每个标签只能归入一个最合适类别。
- 如果不确定，归入最接近的类别。
- 只输出 JSON，不要输出解释文字。
"""
    content = call_ai(prompt, max_tokens=2500, temperature=0.15)
    data = extract_json_any(content)
    if not isinstance(data, dict):
        raise ValueError("自动归类结果不是 JSON 对象")

    output = defaultdict(list)
    valid = set(categories)
    for cat, items in data.items():
        target_cat = cat if cat in valid else "其他"
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, list) and len(item) >= 2:
                label = str(item[0]).strip()
                try:
                    cnt = int(item[1])
                except Exception:
                    cnt = 0
                if label:
                    output[target_cat].append((label, cnt))
    return dict(output)


# ================= 主观字段：通用一级分类 + 自检 + 二级主题 =================
def ai_classify_with_universal_taxonomy(labels_info: List[dict], field_name: str, taxonomy_type: str) -> Dict[str, List[Tuple[str, int]]]:
    if not labels_info:
        return {}
    taxonomy = UNIVERSAL_TAXONOMIES[taxonomy_type]
    categories = [x["category"] for x in taxonomy]

    if len(labels_info) > CLASSIFY_BATCH_SIZE:
        all_result = defaultdict(list)
        for i in range(0, len(labels_info), CLASSIFY_BATCH_SIZE):
            batch = labels_info[i:i + CLASSIFY_BATCH_SIZE]
            batch_result = ai_classify_with_universal_taxonomy(batch, field_name, taxonomy_type)
            for cat, items in batch_result.items():
                all_result[cat].extend(items)
            time.sleep(SLEEP_SECONDS)
        return dict(all_result)

    priority_text = """
重要优先级：
- 涉及跳闸、过载、发热、烧焦、火花、电流不足、功率不足、安全隐患，优先归入“安全与负载问题”（如果该类别存在）。
- 涉及短期坏、寿命短、开关坏、继电器坏、插座不通电、长期不稳定，优先归入“可靠性与寿命问题”（如果该类别存在）。
- 涉及线长、插孔、接口、尺寸、外壳、材质、标识、壁挂、安装固定，优先归入“结构设计问题”（如果该类别存在）。
- 涉及价格高、性价比低，优先归入“价格与性价比问题”（如果该类别存在）。
- 涉及售后、退货、保修、客服、描述不符，优先归入“描述与售后问题”（如果该类别存在）。
"""

    prompt = f"""
你是一个跨品类电商评论分析专家。

请将以下“{field_name}”字段的标准标签归入通用一级分类中。分类体系适用于电商产品评论，不针对某一个具体品类。

通用一级分类：
{taxonomy_to_prompt(taxonomy)}

{priority_text}

输出 JSON 对象，键为一级分类名，值为该类别下的 [标签, 次数] 数组。

标签列表：
{json.dumps(labels_info, ensure_ascii=False, indent=2)}

要求：
- 每个标签只能归入一个最主要类别。
- 不要新增一级分类。
- 如果无法明确判断，归入“其他问题”“其他正向点”“其他改进”或“其他任务”等对应其他类。
- 只输出 JSON，不要输出解释文字。
"""
    content = call_ai(prompt, max_tokens=2800, temperature=0.12)
    data = extract_json_any(content)
    if not isinstance(data, dict):
        raise ValueError("通用分类结果不是 JSON 对象")

    output = defaultdict(list)
    valid = set(categories)
    fallback = categories[-1]
    for cat, items in data.items():
        target_cat = cat if cat in valid else fallback
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, list) and len(item) >= 2:
                label = str(item[0]).strip()
                try:
                    cnt = int(item[1])
                except Exception:
                    cnt = 0
                if label:
                    output[target_cat].append((label, cnt))
    return dict(output)


def ai_self_check_classification(classified: Dict[str, List[Tuple[str, int]]], field_name: str, taxonomy_type: str) -> Dict[str, List[Tuple[str, int]]]:
    """AI 自检纠偏，仅用于通用一级分类。"""
    if not ENABLE_SELF_CHECK:
        return classified

    total_labels = sum(len(v) for v in classified.values())
    if total_labels == 0 or total_labels > SELF_CHECK_MAX_LABELS:
        return classified

    taxonomy = UNIVERSAL_TAXONOMIES[taxonomy_type]
    categories = [x["category"] for x in taxonomy]

    payload = {
        cat: [[label, cnt] for label, cnt in items]
        for cat, items in classified.items()
    }

    prompt = f"""
你是一个电商评论分类审核专家。请检查以下“{field_name}”字段的分类结果是否存在明显归类错误，并输出修正后的 JSON。

通用一级分类定义：
{taxonomy_to_prompt(taxonomy)}

重点检查：
1. 安全、过载、跳闸、发热、烧焦、火花、电流不足类标签，不应误入性能、质量或使用不便类。
2. 寿命、损坏、失效、开关坏、部件坏类标签，应进入可靠性/寿命相关类别。
3. 线长、插孔、接口、安装、标识、外壳、材质类标签，应进入结构设计相关类别。
4. 价格、售后、退货、保修、描述不符，不应误入产品功能类。

允许使用的一级分类：
{json.dumps(categories, ensure_ascii=False, indent=2)}

当前分类结果：
{json.dumps(payload, ensure_ascii=False, indent=2)}

要求：
- 只修正明显错误，不要为了调整而调整。
- 每个标签仍然只能归入一个类别。
- 不要新增一级分类。
- 输出格式与当前分类结果相同：{{"一级分类": [["标签", 次数]]}}。
- 只输出 JSON，不要输出解释文字。
"""
    try:
        content = call_ai(prompt, max_tokens=3200, temperature=0.05)
        data = extract_json_any(content)
        if not isinstance(data, dict):
            return classified
        output = defaultdict(list)
        valid = set(categories)
        fallback = categories[-1]
        for cat, items in data.items():
            target_cat = cat if cat in valid else fallback
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, list) and len(item) >= 2:
                    label = str(item[0]).strip()
                    try:
                        cnt = int(item[1])
                    except Exception:
                        cnt = 0
                    if label:
                        output[target_cat].append((label, cnt))
        return dict(output)
    except Exception as e:
        print(f"      [WARN] 自检纠偏失败，保留原分类：{e}")
        return classified


def ai_generate_secondary_topics(labels_info: List[dict], primary_category: str, field_name: str) -> List[str]:
    """在一级分类内自动生成二级主题。"""
    if not labels_info:
        return ["其他"]
    if len(labels_info) <= 3:
        return [primary_category]

    prompt = f"""
你是一个电商评论主题归纳专家。

下面是“{field_name}”字段中，已经归入一级分类“{primary_category}”的一组标准标签及次数。
请在这个一级分类内部，归纳出 2到5个 二级主题。

要求：
- 二级主题要比一级分类更具体。
- 主题名称使用简体中文短标签。
- 不要过度细分，也不要把不同问题强行合并。
- 只输出 JSON 数组，例如：["主题1", "主题2"]。

标签列表：
{json.dumps(labels_info, ensure_ascii=False, indent=2)}
"""
    try:
        content = call_ai(prompt, max_tokens=600, temperature=0.2)
        data = extract_json_any(content)
        if isinstance(data, list) and data:
            topics = [str(x).strip() for x in data if str(x).strip()]
            return topics or [primary_category]
    except Exception as e:
        print(f"      [WARN] 生成二级主题失败：{primary_category}，{e}")
    return [primary_category]


def ai_classify_secondary(labels_info: List[dict], topics: List[str], primary_category: str, field_name: str) -> Dict[str, List[Tuple[str, int]]]:
    """把一级分类内的标签归入二级主题。"""
    if not labels_info:
        return {}
    if len(topics) == 1:
        return {topics[0]: [(x["label"], int(x["count"])) for x in labels_info]}

    prompt = f"""
请将以下“{field_name}”字段中一级分类“{primary_category}”下的标签，归入给定二级主题中。

二级主题列表：
{json.dumps(topics, ensure_ascii=False, indent=2)}

标签列表：
{json.dumps(labels_info, ensure_ascii=False, indent=2)}

要求：
- 只能使用给定二级主题，不能新增。
- 每个标签只能归入一个最合适的二级主题。
- 输出 JSON 对象，键为二级主题，值为该主题下的 [标签, 次数] 数组。
- 只输出 JSON，不要输出解释文字。
"""
    try:
        content = call_ai(prompt, max_tokens=2200, temperature=0.12)
        data = extract_json_any(content)
        if not isinstance(data, dict):
            raise ValueError("二级主题分类不是 JSON 对象")
        valid = set(topics)
        fallback = topics[0]
        output = defaultdict(list)
        for topic, items in data.items():
            target_topic = topic if topic in valid else fallback
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, list) and len(item) >= 2:
                    label = str(item[0]).strip()
                    try:
                        cnt = int(item[1])
                    except Exception:
                        cnt = 0
                    if label:
                        output[target_topic].append((label, cnt))
        return dict(output)
    except Exception as e:
        print(f"      [WARN] 二级主题归类失败：{primary_category}，{e}")
        return {topics[0]: [(x["label"], int(x["count"])) for x in labels_info]}


# ================= 统一归类入口 =================
def build_result_from_classified(
    classified: Dict[str, List[Tuple[str, int]]],
    field_name: str,
    mode: str,
    taxonomy_type: Optional[str] = None,
    normalization_map: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """把分类结果整理为统一输出结构，并生成二级主题。"""
    category_counts: Dict[str, int] = {}
    category_items: Dict[str, List[Dict[str, Any]]] = {}
    secondary_counts: Dict[str, int] = {}

    for primary, items in classified.items():
        # 合并同一一级分类内可能重复的标签
        merged = OrderedDict()
        for label, cnt in items:
            label = str(label).strip()
            if not label:
                continue
            if label not in merged:
                merged[label] = {"label": label, "count": 0}
            merged[label]["count"] += int(cnt)

        label_items = list(merged.values())
        label_items.sort(key=lambda x: x["count"], reverse=True)
        category_counts[primary] = sum(x["count"] for x in label_items)

        # 自动生成二级主题
        topics = ai_generate_secondary_topics(label_items, primary, field_name)
        secondary_classified = ai_classify_secondary(label_items, topics, primary, field_name)

        rows = []
        for secondary, sec_items in secondary_classified.items():
            sec_total = sum(cnt for _, cnt in sec_items)
            secondary_counts[f"{primary}||{secondary}"] = sec_total
            for lbl, cnt in sec_items:
                rows.append({"label": lbl, "count": int(cnt), "secondary": secondary})

        # 防止二级分类漏标签：把遗漏的标签补到一级同名二级主题
        seen = {r["label"] for r in rows}
        for x in label_items:
            if x["label"] not in seen:
                secondary = primary
                rows.append({"label": x["label"], "count": x["count"], "secondary": secondary})
                secondary_counts[f"{primary}||{secondary}"] = secondary_counts.get(f"{primary}||{secondary}", 0) + x["count"]

        rows.sort(key=lambda x: x["count"], reverse=True)
        category_items[primary] = rows

    representative = {}
    for cat, items in category_items.items():
        sorted_items = sorted(items, key=lambda x: x["count"], reverse=True)
        representative[cat] = [it["label"] for it in sorted_items[:3]]

    return {
        "mode": mode,
        "taxonomy_type": taxonomy_type or "",
        "category_counts": category_counts,
        "category_items": category_items,
        "secondary_counts": secondary_counts,
        "representative": representative,
        "normalization_map": normalization_map or {},
    }


def build_result_from_normalize_only(
    normalized_items: List[Dict[str, Any]],
    field_name: str,
    normalization_map: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    normalize_only 策略：只做标签标准化和直接统计，不做大类归类。

    适合目标国家、颜色、尺寸、接口类型、插头类型、功率规格等字段。
    为了让“摘要汇总”可直接查看，每个标准标签会作为一级类别输出。
    """
    category_counts: Dict[str, int] = {}
    category_items: Dict[str, List[Dict[str, Any]]] = {}
    secondary_counts: Dict[str, int] = {}
    representative: Dict[str, List[str]] = {}

    for item in normalized_items:
        label = str(item.get("label", "")).strip()
        if not label:
            continue
        count = int(item.get("count", 0))
        category_counts[label] = count
        category_items[label] = [{"label": label, "count": count, "secondary": "直接统计"}]
        secondary_counts[f"{label}||直接统计"] = count
        representative[label] = [label]

    return {
        "mode": "标签标准化+直接统计",
        "taxonomy_type": "normalize_only",
        "category_counts": category_counts,
        "category_items": category_items,
        "secondary_counts": secondary_counts,
        "representative": representative,
        "normalization_map": normalization_map or {},
    }


def group_and_count(
    data: List[Tuple[Union[str, List[str]], int]],
    field_name: str,
    split_multi: bool = True,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    print(f"      [DEBUG] {field_name}: 接收到 {len(data)} 条原始数据")

    config = config or product_config
    strategy = get_field_strategy(field_name, config)
    strategy = canonicalize_strategy(strategy) or "objective_auto"
    print(f"      [DEBUG] 字段统计策略: {strategy}")

    unique_items = flatten_stats(data, split_multi=split_multi)
    print(f"      [DEBUG] 原始唯一标签 {len(unique_items)} 个")

    if not unique_items:
        return {
            "mode": "empty",
            "taxonomy_type": "",
            "category_counts": {},
            "category_items": {},
            "secondary_counts": {},
            "representative": {},
            "normalization_map": {},
        }

    print(f"   [阶段1] {field_name}: AI 标签标准化...")
    normalization_map = ai_standardize_labels(unique_items, field_name)
    normalized_items = apply_normalization(unique_items, normalization_map)
    print(f"      [DEBUG] 标准化后唯一标签 {len(normalized_items)} 个")

    labels = [{"label": item["label"], "count": item["count"]} for item in normalized_items]

    if strategy == "normalize_only":
        print(f"   [阶段2] {field_name}: 只做标签标准化和直接统计，不做大类归类...")
        return build_result_from_normalize_only(
            normalized_items,
            field_name=field_name,
            normalization_map=normalization_map,
        )

    taxonomy_type = strategy_to_taxonomy_type(strategy)
    if taxonomy_type:
        print(f"   [阶段2] {field_name}: 使用通用一级分类体系（{taxonomy_type}）...")
        classified = ai_classify_with_universal_taxonomy(labels, field_name, taxonomy_type)
        if taxonomy_type == "negative":
            print(f"   [阶段3] {field_name}: AI 自检纠偏...")
            classified = ai_self_check_classification(classified, field_name, taxonomy_type)
            print(f"   [阶段4] {field_name}: 在一级分类内自动生成二级主题...")
        else:
            print(f"   [阶段3] {field_name}: 在一级分类内自动生成二级主题...")
        return build_result_from_classified(
            classified,
            field_name=field_name,
            mode="通用一级分类+AI二级主题" + ("+自检纠偏" if taxonomy_type == "negative" and ENABLE_SELF_CHECK else ""),
            taxonomy_type=taxonomy_type,
            normalization_map=normalization_map,
        )

    if strategy != "objective_auto":
        print(f"      [WARN] 未识别的 stat_strategy={strategy}，将按 objective_auto 处理")

    print(f"   [阶段2] {field_name}: 客观字段，AI 自动生成类别...")
    top_for_cat = labels[:80]
    categories = ai_generate_categories(top_for_cat, field_name)
    print(f"      生成类别: {categories}")
    classified = ai_classify_with_categories(labels, categories, field_name)
    print(f"   [阶段3] {field_name}: 在一级分类内自动生成二级主题...")
    return build_result_from_classified(
        classified,
        field_name=field_name,
        mode="AI自动归类+AI二级主题",
        taxonomy_type="",
        normalization_map=normalization_map,
    )


# ================= 输出到 Excel =================
def safe_sheet_name(name: str) -> str:
    name = re.sub(r'[\\/*?:\[\]]', '_', str(name))
    return name[:31]


def auto_width_excel(output_file: str):
    wb = load_workbook(output_file)
    for sheet in wb.sheetnames:
        ws = wb[sheet]
        for col in ws.columns:
            max_len = 0
            col_letter = get_column_letter(col[0].column)
            for cell in col:
                if cell.value is not None:
                    max_len = max(max_len, len(str(cell.value)))
            ws.column_dimensions[col_letter].width = min(max_len + 2, 60)
    wb.save(output_file)


def save_results(merged_df: pd.DataFrame, raw_stats: Dict, ai_results: Dict, output_file: str):
    output_dir = os.path.dirname(os.path.abspath(output_file))
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        merged_df.to_excel(writer, sheet_name="合并数据", index=False)

        for field, data in raw_stats.items():
            rows = []
            for tag, cnt in data:
                tag_str = " | ".join(tag) if isinstance(tag, list) else str(tag)
                rows.append({"原始标签": tag_str, "出现次数": cnt})
            stat_df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["原始标签", "出现次数"])
            if rows:
                stat_df = stat_df.sort_values("出现次数", ascending=False)
            stat_df.to_excel(writer, sheet_name=safe_sheet_name(f"{field}_原始统计"), index=False)

        for field, result in ai_results.items():
            # 标签标准化映射
            norm_rows = []
            for raw, norm in result.get("normalization_map", {}).items():
                norm_rows.append({"原始标签": raw, "标准标签": norm})
            norm_df = pd.DataFrame(norm_rows) if norm_rows else pd.DataFrame(columns=["原始标签", "标准标签"])
            norm_df.to_excel(writer, sheet_name=safe_sheet_name(f"{field}_标签标准化"), index=False)

            # AI归类结果
            rows = []
            sec_counts = result.get("secondary_counts", {})
            for primary, items in result.get("category_items", {}).items():
                for item in items:
                    secondary = item.get("secondary", "")
                    rows.append({
                        "归类模式": result.get("mode", ""),
                        "一级类别": primary,
                        "一级类别总次数": result.get("category_counts", {}).get(primary, 0),
                        "二级主题": secondary,
                        "二级主题总次数": sec_counts.get(f"{primary}||{secondary}", 0),
                        "标准标签": item.get("label", ""),
                        "标准标签次数": item.get("count", 0),
                        "代表性标签": "；".join(result.get("representative", {}).get(primary, [])),
                    })
            df_cat = pd.DataFrame(rows) if rows else pd.DataFrame(columns=[
                "归类模式", "一级类别", "一级类别总次数", "二级主题", "二级主题总次数",
                "标准标签", "标准标签次数", "代表性标签"
            ])
            if rows:
                df_cat = df_cat.sort_values(
                    ["一级类别总次数", "一级类别", "二级主题总次数", "标准标签次数"],
                    ascending=[False, True, False, False]
                )
            df_cat.to_excel(writer, sheet_name=safe_sheet_name(f"{field}_AI归类"), index=False)

        # 摘要汇总：一级类别
        summary_rows = []
        for field, result in ai_results.items():
            summary_rows.append({"字段": field, "归类模式": result.get("mode", ""), "一级类别": "", "总次数": "", "代表性标签": ""})
            for cat, total in sorted(result.get("category_counts", {}).items(), key=lambda x: x[1], reverse=True):
                reps = "；".join(result.get("representative", {}).get(cat, []))
                summary_rows.append({"字段": "", "归类模式": "", "一级类别": cat, "总次数": total, "代表性标签": reps})
            summary_rows.append({"字段": "", "归类模式": "", "一级类别": "", "总次数": "", "代表性标签": ""})
        summary_df = pd.DataFrame(summary_rows)
        summary_df.to_excel(writer, sheet_name="摘要汇总", index=False)

        # 二级主题汇总
        secondary_rows = []
        for field, result in ai_results.items():
            for key, total in sorted(result.get("secondary_counts", {}).items(), key=lambda x: x[1], reverse=True):
                if "||" in key:
                    primary, secondary = key.split("||", 1)
                else:
                    primary, secondary = key, ""
                secondary_rows.append({
                    "字段": field,
                    "一级类别": primary,
                    "二级主题": secondary,
                    "二级主题总次数": total,
                })
        secondary_df = pd.DataFrame(secondary_rows) if secondary_rows else pd.DataFrame(columns=["字段", "一级类别", "二级主题", "二级主题总次数"])
        secondary_df.to_excel(writer, sheet_name="二级主题汇总", index=False)

    auto_width_excel(output_file)


# ================= 主函数 =================
def main():
    print("1. 正在读取并合并 sheets...")
    merged_df = merge_sheets(INPUT_FILE, TARGET_SHEETS)
    print(f"   合并后总行数: {len(merged_df)}")

    # 避免修改原始 FIELDS 引用
    fields_to_process = list(FIELDS)
    missing_cols = [f for f in fields_to_process if f not in merged_df.columns]
    if missing_cols:
        print(f"警告：以下列不存在，将跳过: {missing_cols}")
        fields_to_process = [f for f in fields_to_process if f not in missing_cols]

    if not fields_to_process:
        raise ValueError("没有可统计字段，请检查 product_configs.json 的 stats_fields 和 step1 输出列名。")

    print("2. 正在统计原始标签...")
    raw_stats = {}
    for field in fields_to_process:
        raw_stats[field] = build_raw_stats(merged_df, field)
        print(f"   {field}: 发现 {len(raw_stats[field])} 个不同标签")

    print("3. 正在调用 AI 进行标签标准化、通用一级分类、二级主题归纳...")
    ai_results = {}
    for field in fields_to_process:
        print(f"\n   正在处理: {field}")
        try:
            ai_results[field] = group_and_count(raw_stats[field], field, split_multi=True, config=product_config)
            print(f"     完成，生成 {len(ai_results[field]['category_counts'])} 个一级类别")
        except Exception as e:
            print(f"     处理 {field} 时出错: {e}")
            ai_results[field] = {
                "mode": "error",
                "taxonomy_type": "",
                "category_counts": {},
                "category_items": {},
                "secondary_counts": {},
                "representative": {},
                "normalization_map": {},
            }
        time.sleep(SLEEP_SECONDS)

    print("\n4. 正在保存结果到 Excel...")
    save_results(merged_df, raw_stats, ai_results, OUTPUT_FILE)
    print(f"完成！输出文件: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
