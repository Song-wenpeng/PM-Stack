# -*- coding: utf-8 -*-
"""
comments_step_1.py

第1步：逐条读取评论，调用 AI 按 product_configs.json 中的字段配置提取结构化标签。

主要改动：
1. 去掉重复初始化。
2. 增强 JSON 解析容错。
3. 统一要求列表字段输出“简体中文短标签”。
4. 对模型返回字段做严格归一化，缺失字段自动补空。
"""

import os
import time
import re
import json
from typing import Dict, Any

import pandas as pd
from openai import OpenAI
from tqdm import tqdm

# ================= 环境变量配置 =================
API_ENV_NAME = os.getenv("API_ENV_NAME", "SILICONFLOW_API_KEY")
API_KEY = os.getenv(API_ENV_NAME)
if not API_KEY:
    raise ValueError(f"未检测到环境变量 {API_ENV_NAME}，请先设置后再运行。")

BASE_URL = os.getenv("BASE_URL", "https://api.siliconflow.cn/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "deepseek-ai/DeepSeek-V3")

INPUT_FILE = os.getenv("RAW_INPUT_FILE")
OUTPUT_FILE = os.getenv("STEP1_OUTPUT_FILE")
COMMENT_COLUMN = os.getenv("COMMENT_COLUMN", "内容")

CONFIG_FILE = os.getenv("CONFIG_FILE", "./product_configs.json")
CURRENT_PRODUCT = os.getenv("CURRENT_PRODUCT")

TARGET_SHEETS = [
    s.strip() for s in os.getenv("TARGET_SHEETS", "").split(",") if s.strip()
]

if not INPUT_FILE:
    raise ValueError("未检测到环境变量 RAW_INPUT_FILE")
if not OUTPUT_FILE:
    raise ValueError("未检测到环境变量 STEP1_OUTPUT_FILE")
if not CURRENT_PRODUCT:
    raise ValueError("未检测到环境变量 CURRENT_PRODUCT")

TEMPERATURE = float(os.getenv("STEP1_TEMPERATURE", "0.2"))
MAX_TOKENS = int(os.getenv("STEP1_MAX_TOKENS", "1200"))
SLEEP_SECONDS = float(os.getenv("STEP1_SLEEP_SECONDS", "0.3"))
MAX_RETRIES = int(os.getenv("STEP1_MAX_RETRIES", "3"))

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)


# ================= 读取配置 =================
def load_product_configs(config_file: str) -> Dict[str, Any]:
    """从 JSON 文件读取品类配置。"""
    if not os.path.exists(config_file):
        raise FileNotFoundError(f"配置文件不存在：{config_file}")

    with open(config_file, "r", encoding="utf-8") as f:
        configs = json.load(f)

    if not isinstance(configs, dict):
        raise ValueError("配置文件格式错误：最外层必须是 JSON 对象")

    return configs


# ================= 工具函数 =================
def build_prompt(config: Dict[str, Any], comment: str) -> str:
    """根据品类配置自动生成 prompt。"""
    field_desc = []
    for field in config["fields"]:
        field_type = "字符串列表" if field["type"] == "list" else "字符串"
        field_desc.append(f'`{field["key"]}`（{field_type}，Excel列名：{field.get("excel_col", "")}）')

    tasks_text = "\n".join(
        f"{i}. {task}" for i, task in enumerate(config.get("tasks", []), start=1)
    )

    prompt = f"""
你是一个专业的用户评论分析专家，专门处理以下品类评论：
{config.get("product_desc", "")}

请对用户评论完成以下任务：
{tasks_text}

输出格式要求：
- 必须只输出一个 JSON 对象，不要输出解释、说明或 markdown 标记。
- JSON 中必须包含以下字段：
  {", ".join(field_desc)}
- 列表字段必须输出数组；字符串字段必须输出字符串。
- 若信息缺失，列表字段输出 []，字符串字段输出 ""。
- 所有提取结果尽量使用简体中文短标签，不要把多个标签合并成一个长句。
- 不要为了填满字段而编造评论中没有依据的信息。

用户评论：
{comment}
"""
    return prompt.strip()


def get_default_result(config: Dict[str, Any]) -> Dict[str, Any]:
    """生成默认空结果。"""
    result = {}
    for field in config["fields"]:
        result[field["key"]] = [] if field["type"] == "list" else ""
    return result


def extract_json_object(content: str) -> Dict[str, Any]:
    """从模型输出中提取 JSON 对象，兼容 markdown 代码块和前后多余文本。"""
    if content is None:
        raise ValueError("模型返回为空")

    text = str(content).strip()
    text = re.sub(r"^```json\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("未找到 JSON 对象")

    json_text = text[start:end + 1]
    json_text = re.sub(r",\s*}", "}", json_text)
    json_text = re.sub(r",\s*]", "]", json_text)
    data = json.loads(json_text)
    if not isinstance(data, dict):
        raise ValueError("JSON 顶层不是对象")
    return data


def normalize_field_value(value: Any, field_type: str):
    """字段值标准化。"""
    if field_type == "list":
        if value is None:
            return []
        if isinstance(value, list):
            return [str(x).strip() for x in value if str(x).strip()]
        if isinstance(value, str):
            v = value.strip()
            if not v or v in ("[]", "null", "None", "nan"):
                return []
            if v.startswith("[") and v.endswith("]"):
                try:
                    parsed = json.loads(v)
                    if isinstance(parsed, list):
                        return [str(x).strip() for x in parsed if str(x).strip()]
                except Exception:
                    pass
            # 兜底：模型把多个标签写成一个字符串时，尽量拆分
            if any(sep in v for sep in ["；", ";", "、", "|"]):
                parts = re.split(r"[；;、|]", v)
                return [p.strip() for p in parts if p.strip()]
            return [v]
        return [str(value).strip()] if str(value).strip() else []

    if value is None:
        return ""
    return str(value).strip()


def normalize_result(data: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    """按配置统一整理返回结果，只保留配置字段。"""
    result = {}
    for field in config["fields"]:
        key = field["key"]
        field_type = field["type"]
        result[key] = normalize_field_value(data.get(key), field_type)
    return result


def call_ai_extract(comment: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """调用 AI 提取评论信息。"""
    if pd.isna(comment) or not str(comment).strip():
        return get_default_result(config)

    comment = str(comment).strip()
    prompt = build_prompt(config, comment)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": config.get("system_prompt", "你是专业的用户评论分析专家。")},
                    {"role": "user", "content": prompt},
                ],
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS,
            )

            content = response.choices[0].message.content
            data = extract_json_object(content)
            return normalize_result(data, config)

        except Exception as e:
            print(f"[第 {attempt}/{MAX_RETRIES} 次失败] API 调用或解析错误: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(1.2 * attempt)
            else:
                return get_default_result(config)


def serialize_for_excel(value: Any) -> str:
    """写入 Excel 前处理列表字段。"""
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    return value


def process_sheet(df_sheet: pd.DataFrame, config: Dict[str, Any]) -> pd.DataFrame:
    """处理单个 sheet。"""
    results = []

    for _, row in tqdm(df_sheet.iterrows(), total=len(df_sheet), desc="处理评论"):
        comment = row.get(COMMENT_COLUMN, "")
        details = call_ai_extract(comment, config)

        combined = row.to_dict()
        for field in config["fields"]:
            key = field["key"]
            excel_col = field["excel_col"]
            combined[excel_col] = serialize_for_excel(details[key])

        results.append(combined)
        time.sleep(SLEEP_SECONDS)

    return pd.DataFrame(results)


# ================= 主程序 =================
def main():
    product_configs = load_product_configs(CONFIG_FILE)

    if CURRENT_PRODUCT not in product_configs:
        raise ValueError(f"未找到品类配置：{CURRENT_PRODUCT}")

    config = product_configs[CURRENT_PRODUCT]
    if "fields" not in config or not config["fields"]:
        raise ValueError(f"{CURRENT_PRODUCT} 未配置 fields")

    if not os.path.exists(INPUT_FILE):
        raise FileNotFoundError(f"输入文件不存在：{INPUT_FILE}")

    output_dir = os.path.dirname(os.path.abspath(OUTPUT_FILE))
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    xls = pd.ExcelFile(INPUT_FILE)
    all_sheet_names = xls.sheet_names
    print(f"发现工作表: {all_sheet_names}")

    if TARGET_SHEETS:
        sheet_names = [s for s in TARGET_SHEETS if s in all_sheet_names]
    else:
        sheet_names = all_sheet_names

    if not sheet_names:
        raise ValueError(f"没有可处理的工作表。TARGET_SHEETS={TARGET_SHEETS}，实际={all_sheet_names}")

    print(f"本次实际处理工作表: {sheet_names}")

    with pd.ExcelWriter(OUTPUT_FILE, engine="openpyxl") as writer:
        for sheet_name in sheet_names:
            print(f"\n开始处理工作表：{sheet_name}")
            df_sheet = pd.read_excel(INPUT_FILE, sheet_name=sheet_name)

            if COMMENT_COLUMN not in df_sheet.columns:
                print(f"跳过工作表 '{sheet_name}'，缺少列 '{COMMENT_COLUMN}'")
                continue

            df_result = process_sheet(df_sheet, config)
            df_result.to_excel(writer, sheet_name=sheet_name, index=False)
            print(f"工作表 '{sheet_name}' 处理完成，共 {len(df_result)} 条")

    print(f"\n全部处理完成，结果已保存到：{OUTPUT_FILE}")


if __name__ == "__main__":
    main()
