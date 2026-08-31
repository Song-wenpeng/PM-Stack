# -*- coding: utf-8 -*-
import pandas as pd
import time
import os
import json
import re
import base64
import requests
import io
from openai import OpenAI
from tqdm import tqdm
from PIL import Image

# ================= 1. 基础配置区 =================

API_KEY = os.getenv("API_KEY") or os.getenv("SILICONFLOW_API_KEY")
BASE_URL = os.getenv("BASE_URL", "https://api.siliconflow.cn/v1")

if not API_KEY:
    raise ValueError("未读取到 API Key，请检查环境变量 API_KEY 是否已正确配置。")

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

MODEL_TEXT = os.getenv("MODEL_TEXT", os.getenv("MODEL_NAME", "deepseek-ai/DeepSeek-V3"))

# 视觉模型：优先使用独立配置，回退到通用配置
VISION_API_KEY = os.getenv("VISION_API_KEY") or API_KEY
VISION_BASE_URL = os.getenv("VISION_BASE_URL") or BASE_URL
MODEL_VISION = os.getenv("MODEL_VISION", "Qwen/Qwen3-VL-30B-A3B-Instruct")
vision_client = OpenAI(api_key=VISION_API_KEY, base_url=VISION_BASE_URL)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

INPUT_FILE = os.getenv(
    "INPUT_FILE",
    r"C:/Users/QJH/WPSDrive/311520967/WPS云盘/联动排插_US/联动排插_数据.xlsx",
)
OUTPUT_FILE = os.getenv(
    "OUTPUT_FILE",
    r"C:/Users/QJH/WPSDrive/311520967/WPS云盘/联动排插_US/联动排插_数据_打标.xlsx",
)

CONFIG_FILE = os.getenv("CONFIG_FILE", os.path.join(SCRIPT_DIR, "product_field_config.json"))
CURRENT_PRODUCT = os.getenv("CURRENT_PRODUCT", "vacuum auto switch")

# 是否从已有输出文件继续跑
# 如果之前输出文件里有错误图片识别结果，建议设为 False，从原始文件重跑
RESUME_FROM_OUTPUT = False

# 是否运行时询问启用图片识别
ASK_ENABLE_VISION = os.getenv("ASK_ENABLE_VISION", "0").strip().lower() in ("1", "true", "yes", "y")

# ASK_ENABLE_VISION = False 时，默认是否启用图片识别
ENABLE_VISION_DEFAULT = os.getenv("ENABLE_VISION", "1").strip().lower() not in ("0", "false", "no", "n")

# 图片建议一批 3 张，减少调用频次
VISION_BATCH_SIZE = 3

# 每个商品最多识别前几张图片，避免 9 张图全部跑
MAX_VISION_IMAGES_PER_ROW = 9

# 连续多少批没有补出有效字段，就停止该商品的图片识别
MAX_EMPTY_VISION_BATCHES = 3

# 图片识别失败重试次数
VISION_MAX_RETRIES = 2

# 每处理多少行保存一次
SAVE_EVERY = 10

# 图片结果最低置信度
MIN_VISION_CONFIDENCE = 0.75



# 固定文本列，不放进 JSON
TEXT_COLS = ["商品标题", "详细参数", "SKU", "五点描述"]

# 固定图片列，不放进 JSON
IMAGE_COLS = [
    "image_1", "image_2", "image_3",
    "image_4", "image_5", "image_6",
    "image_7", "image_8", "image_9"
]

AUX_FIELDS = [
    "文本提取字段",
    "图片识别提取字段",
    "图片识别批次日志",
    "最终缺失字段",
    "提取完整状态"
]


# ================= 2. 读取字段配置 =================

def load_product_config(config_file, product_name=None):
    """
    从 JSON 文件读取当前品类字段配置。
    JSON 只负责产品字段，不负责固定文本列和图片列。
    """
    if not os.path.exists(config_file):
        raise FileNotFoundError(f"字段配置文件不存在：{config_file}")

    with open(config_file, "r", encoding="utf-8") as f:
        config = json.load(f)

    if not product_name:
        product_name = config.get("current_product")

    if not product_name:
        raise ValueError("配置文件中未设置 current_product，也未在代码中指定 CURRENT_PRODUCT。")

    products = config.get("products", {})

    if product_name not in products:
        raise ValueError(f"配置文件中不存在产品配置：{product_name}")

    product_config = products[product_name]

    required_keys = ["target_fields", "field_config"]
    missing_keys = [key for key in required_keys if key not in product_config]

    if missing_keys:
        raise ValueError(f"产品配置缺少必要字段：{missing_keys}")

    return product_name, product_config


CURRENT_PRODUCT, PRODUCT_CONFIG = load_product_config(CONFIG_FILE, CURRENT_PRODUCT)

PRODUCT_NAME = PRODUCT_CONFIG.get("name", CURRENT_PRODUCT)
TARGET_FIELDS = PRODUCT_CONFIG["target_fields"]
FIELD_CONFIG = PRODUCT_CONFIG["field_config"]

# 没写 vision_allowed_fields 的产品，默认不启用图片补字段
VISION_ALLOWED_FIELDS = PRODUCT_CONFIG.get("vision_allowed_fields", [])
VISION_FIELD_CONFIG = PRODUCT_CONFIG.get("vision_field_config", {})


# ================= 3. 工具函数 =================

def ask_enable_vision():
    """
    运行时选择是否启用图片识别。
    如果当前产品没有配置 vision_allowed_fields，即使输入 y，也不会实际补字段。
    """
    if not ASK_ENABLE_VISION:
        return ENABLE_VISION_DEFAULT

    while True:
        choice = input("是否启用图片识别补全？输入 y/n：").strip().lower()

        if choice in ["y", "yes", "是", "1"]:
            if not VISION_ALLOWED_FIELDS:
                print("已选择启用图片识别，但当前产品未配置 vision_allowed_fields，图片阶段不会补字段。")
            else:
                print("已启用图片识别补全。")
            return True

        if choice in ["n", "no", "否", "0"]:
            print("已关闭图片识别补全，本次只进行文本提取。")
            return False

        print("输入无效，请输入 y 或 n。")


def is_empty(value):
    if value is None:
        return True

    try:
        if pd.isna(value):
            return True
    except Exception:
        pass

    value_str = str(value).strip()

    if value_str == "":
        return True

    if value_str.lower() in ["nan", "none", "null", "n/a", "na"]:
        return True

    if value_str in ["未找到", "无", "空", "未知", "未说明"]:
        return True

    return False


def clean_value(value):
    if value is None:
        return ""

    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)

    value = str(value).strip()

    if is_empty(value):
        return ""

    return value


def parse_json_from_ai(content):
    if not content:
        return {}

    content = content.strip()
    content = content.replace("```json", "").replace("```", "").strip()

    try:
        data = json.loads(content)
        if isinstance(data, dict):
            return data
        return {}
    except Exception:
        pass

    match = re.search(r"\{[\s\S]*\}", content)
    if match:
        json_str = match.group(0)
        try:
            data = json.loads(json_str)
            if isinstance(data, dict):
                return data
        except Exception:
            return {}

    return {}


def filter_valid_fields(data, allowed_fields):
    result = {}

    if not isinstance(data, dict):
        return result

    for field in allowed_fields:
        value = clean_value(data.get(field, ""))
        if not is_empty(value):
            result[field] = value

    return result


def filter_valid_vision_fields_with_evidence(data, allowed_fields, min_confidence=0.75):
    result = {}

    if not isinstance(data, dict):
        return result

    suspicious_words = [
        "推测", "猜测", "可能", "应该", "通常", "一般", "常见",
        "根据产品类型", "根据同类产品", "看起来", "似乎"
    ]

    for field in allowed_fields:
        item = data.get(field, "")

        if not isinstance(item, dict):
            continue

        value = clean_value(item.get("value", ""))
        evidence = clean_value(item.get("evidence", ""))
        confidence = item.get("confidence", 0)

        try:
            confidence = float(confidence)
        except Exception:
            confidence = 0

        if is_empty(value):
            continue

        if is_empty(evidence):
            continue

        if confidence < min_confidence:
            continue

        if any(word in evidence for word in suspicious_words):
            continue

        result[field] = value

    return result


def get_missing_fields(row, extracted_data=None):
    extracted_data = extracted_data or {}
    missing = []

    for field in TARGET_FIELDS:
        existing_value = row.get(field, "")
        extracted_value = extracted_data.get(field, "")

        if is_empty(existing_value) and is_empty(extracted_value):
            missing.append(field)

    return missing


def build_text_from_row(row):
    parts = []

    for col in TEXT_COLS:
        value = row.get(col, "")

        if not is_empty(value):
            parts.append(f"【{col}】\n{str(value).strip()}")

    return "\n\n".join(parts)


def get_valid_image_urls(row, df_columns):
    urls = []
    url_pattern = r"https?://[^\s,;，；\)\]\}\"\']+"

    for col in IMAGE_COLS:
        if col not in df_columns:
            continue

        value = row.get(col, "")

        if is_empty(value):
            continue

        value_str = str(value).strip()
        found_urls = re.findall(url_pattern, value_str)

        if not found_urls and value_str.startswith("http"):
            found_urls = [value_str]

        for url in found_urls:
            lower_url = url.lower()

            is_likely_image = (
                ".jpg" in lower_url
                or ".jpeg" in lower_url
                or ".png" in lower_url
                or ".webp" in lower_url
                or "media-amazon" in lower_url
                or "ssl-images-amazon" in lower_url
                or "/images/" in lower_url
            )

            if is_likely_image and url not in urls:
                urls.append(url)

    return urls


def get_image_base64_from_url(image_url):
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/114.0.0.0 Safari/537.36"
            )
        }

        response = requests.get(image_url, headers=headers, timeout=15)
        response.raise_for_status()

        img = Image.open(io.BytesIO(response.content))

        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        max_size = 2000
        if max(img.size) > max_size:
            ratio = max_size / max(img.size)
            new_size = tuple(int(dim * ratio) for dim in img.size)
            img = img.resize(new_size, Image.Resampling.LANCZOS)

        buffer = io.BytesIO()
        img.save(buffer, format="WEBP", quality=85)

        base64_str = base64.b64encode(buffer.getvalue()).decode("utf-8")
        return f"data:image/webp;base64,{base64_str}"

    except Exception as e:
        print(f"图片下载或处理失败：{e}")
        print(f"失败图片链接：{image_url}")
        return None


# ================= 4. 文本提取函数 =================

def extract_text_features(row, missing_fields=None, max_retries=3):
    text_content = build_text_from_row(row)

    if is_empty(text_content):
        return {}

    if not missing_fields:
        missing_fields = TARGET_FIELDS

    field_details = "\n".join([
        f"- {field}: {FIELD_CONFIG.get(field, '无具体说明，请根据商品信息提取。')}"
        for field in missing_fields
    ])

    example_json = json.dumps(
        {field: "示例值" for field in missing_fields},
        ensure_ascii=False
    )

    prompt = f"""
你是一个严格的电商产品参数提取助手。

当前产品类型：{PRODUCT_NAME}

请从下面的商品信息中提取指定字段，并严格按照 JSON 格式输出。

商品信息如下：
{text_content}

本次需要提取的字段及规则：
{field_details}

输出格式示例：
{example_json}

提取要求：
1. 只能提取商品信息中明确出现的信息。
2. 不要根据常识猜测，不要编造。
3. 不要把同类产品常见功能当作本产品功能。
4. 没有找到的字段请返回空字符串 ""。
5. JSON 的 key 必须严格使用以下字段名：
{missing_fields}
6. 只输出 JSON，不要输出解释、分析、Markdown 代码块。
7. 字段值尽量使用中文表述；规格数值、单位、型号可以保留原文。
"""

    last_error = None

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=MODEL_TEXT,
                messages=[
                    {"role": "system", "content": "你是一个结构化商品参数提取器，只输出 JSON，不推测。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0,
                max_tokens=1200
            )

            content = response.choices[0].message.content.strip()
            data = parse_json_from_ai(content)
            result = filter_valid_fields(data, missing_fields)

            return result

        except Exception as e:
            last_error = str(e)
            print(f"\n文本提取错误，第 {attempt + 1}/{max_retries} 次尝试失败：{e}")
            time.sleep(1.5)

    print(f"\n文本提取最终失败：{last_error}")
    return {}


# ================= 5. 图片识别函数 =================

def extract_vision_features(image_urls, missing_fields, max_retries=1):
    if not image_urls or not missing_fields or not VISION_ALLOWED_FIELDS:
        return {}, {}, ""

    vision_fields = [field for field in missing_fields if field in VISION_ALLOWED_FIELDS]

    if not vision_fields:
        return {}, {}, ""

    field_details = "\n".join([
        f"- {field}: {VISION_FIELD_CONFIG.get(field, FIELD_CONFIG.get(field, '无具体说明，请根据图片信息提取。'))}"
        for field in vision_fields
    ])

    example_json = {
        field: {
            "value": "",
            "evidence": "",
            "confidence": 0
        }
        for field in vision_fields
    }

    prompt_text = f"""
你是一个非常严格的电商产品图片 OCR 与参数提取助手。

当前产品类型：{PRODUCT_NAME}

你只能基于以下两类证据提取信息：
1. 图片中清晰可见的文字；
2. 图片中肉眼可以直接数出的硬件结构，例如插孔数量、USB 接口数量、开关数量。

严禁事项：
1. 严禁根据产品类别推测功能。
2. 严禁根据同类产品常见配置推测参数。
3. 严禁看到手机 App 图标就推断支持定时、功耗监测、远程控制。
4. 严禁看到 USB 接口就推断 USB 功率。
5. 严禁在图片没有明确文字证据时填写功率、线缆长度、安全保护等字段。
6. 对于可以肉眼数出的接口数量，evidence 必须写清楚“图片中可见几个”。

本次只需要补全以下字段：
{field_details}

输出要求：
1. 每个字段都必须返回 value、evidence、confidence。
2. value 是提取值。
3. evidence 必须说明图片中的具体依据，例如“图片中可见4个AC插座”或“包装文字显示5V/2.1A”。
4. 如果没有清晰证据，value 和 evidence 必须为空字符串，confidence 为 0。
5. 只输出 JSON，不要输出解释、分析、Markdown 代码块。

请严格按以下 JSON 格式输出：
{json.dumps(example_json, ensure_ascii=False)}
"""

    content_list = []

    for url in image_urls:
        base64_image = get_image_base64_from_url(url)

        if not base64_image:
            continue

        content_list.append({
            "type": "image_url",
            "image_url": {
                "url": base64_image,
                "detail": "high"
            }
        })

    if not content_list:
        print("当前批次图片全部下载或转换失败，跳过视觉识别。")
        return {}, {}, ""

    content_list.append({
        "type": "text",
        "text": prompt_text
    })

    last_error = None

    for attempt in range(max_retries):
        try:
            response = vision_client.chat.completions.create(
                model=MODEL_VISION,
                messages=[
                    {
                        "role": "user",
                        "content": content_list
                    }
                ],
                max_tokens=1500,
                temperature=0
            )

            raw_text = response.choices[0].message.content.strip()

            print("视觉模型原始返回：")
            print(raw_text[:500])

            raw_data = parse_json_from_ai(raw_text)
            result = filter_valid_vision_fields_with_evidence(
                raw_data,
                vision_fields,
                min_confidence=MIN_VISION_CONFIDENCE
            )

            return result, raw_data, raw_text

        except Exception as e:
            last_error = str(e)
            print(f"视觉提取错误，第 {attempt + 1}/{max_retries} 次尝试失败：{e}")
            time.sleep(2)

    print(f"视觉提取最终失败：{last_error}")
    return {}, {}, ""


# ================= 6. 主程序 =================

def main():
    # ---- FIELDS 过滤：只提取指定字段 ----
    fields_filter = os.getenv("FIELDS", "").strip()
    if fields_filter:
        selected = [f.strip() for f in fields_filter.split(",") if f.strip()]
        invalid = [f for f in selected if f not in FIELD_CONFIG]
        if invalid:
            print(f"[警告] 以下字段不在配置中，将被忽略: {invalid}")
        valid = [f for f in selected if f in FIELD_CONFIG]
        if not valid:
            print("[错误] 没有有效的目标字段，退出。")
            return
        TARGET_FIELDS[:] = valid
        print(f"[模式] 单字段/部分字段提取，目标字段: {TARGET_FIELDS}")

    # ---- 停止信号文件 ----
    STOP_FILE = os.getenv("STOP_FILE", "")
    if STOP_FILE:
        # 清除上次的停止信号
        if os.path.exists(STOP_FILE):
            os.remove(STOP_FILE)

    enable_vision = ask_enable_vision()
    output_dir = os.path.dirname(OUTPUT_FILE)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    if RESUME_FROM_OUTPUT and os.path.exists(OUTPUT_FILE):
        print(f"检测到已存在输出文件，将从 {OUTPUT_FILE} 继续处理。")
        df = pd.read_excel(OUTPUT_FILE)
    else:
        print(f"读取原始文件：{INPUT_FILE}")
        df = pd.read_excel(INPUT_FILE)

    missing_text_cols = [col for col in TEXT_COLS if col not in df.columns]

    if missing_text_cols:
        raise ValueError(f"Excel 中缺少以下文本列：{missing_text_cols}")

    for field in TARGET_FIELDS + AUX_FIELDS:
        if field not in df.columns:
            df[field] = ""

    print(f"当前产品配置：{CURRENT_PRODUCT} / {PRODUCT_NAME}")
    print(f"开始处理，共 {len(df)} 条商品数据。")
    print(f"当前目标字段数量：{len(TARGET_FIELDS)}")
    print(f"图片识别状态：{'启用' if enable_vision else '关闭'}")
    print(f"图片可补字段数量：{len(VISION_ALLOWED_FIELDS)}")
    print(f"图片批量大小：{VISION_BATCH_SIZE}")

    for index, row in tqdm(df.iterrows(), total=len(df), desc="AI处理进度"):
        already_done = True

        for field in TARGET_FIELDS:
            if is_empty(row.get(field, "")):
                already_done = False
                break

        if already_done:
            continue

        extracted_data = {}
        text_fields = []
        vision_fields_all = []
        vision_batch_logs = []

        missing_fields = get_missing_fields(row, extracted_data)

        text_data = extract_text_features(row, missing_fields=missing_fields)

        if text_data:
            extracted_data.update(text_data)
            text_fields.extend(list(text_data.keys()))
            print(f"\n第 {index + 1} 行文本提取成功：{text_data}")

        missing_fields = get_missing_fields(row, extracted_data)

        vision_missing_fields = [
            field for field in missing_fields
            if field in VISION_ALLOWED_FIELDS
        ]

        if enable_vision and vision_missing_fields:
            all_imgs = get_valid_image_urls(row, df.columns)

            if all_imgs:
                limited_imgs = all_imgs[:MAX_VISION_IMAGES_PER_ROW]
                empty_batch_count = 0

                print(f"\n第 {index + 1} 行文本后仍缺失：{missing_fields}")
                print(f"其中允许图片补全字段：{vision_missing_fields}")
                print(f"共找到 {len(all_imgs)} 张图片，本次最多识别前 {MAX_VISION_IMAGES_PER_ROW} 张。")

                for i in range(0, len(limited_imgs), VISION_BATCH_SIZE):
                    missing_fields = get_missing_fields(row, extracted_data)

                    vision_missing_fields = [
                        field for field in missing_fields
                        if field in VISION_ALLOWED_FIELDS
                    ]

                    if not vision_missing_fields:
                        break

                    if empty_batch_count >= MAX_EMPTY_VISION_BATCHES:
                        print(f"连续 {MAX_EMPTY_VISION_BATCHES} 批图片未补出有效字段，停止该商品图片识别。")
                        break

                    batch_imgs = limited_imgs[i:i + VISION_BATCH_SIZE]

                    print(f"正在分析第 {i // VISION_BATCH_SIZE + 1} 批图片，共 {len(batch_imgs)} 张。")

                    vision_data, vision_raw_data, vision_raw_text = extract_vision_features(
                        batch_imgs,
                        vision_missing_fields,
                        max_retries=VISION_MAX_RETRIES
                    )

                    batch_log = {
                        "批次": i // VISION_BATCH_SIZE + 1,
                        "图片数量": len(batch_imgs),
                        "尝试补全字段": vision_missing_fields,
                        "通过过滤后的结果": vision_data,
                        "模型原始JSON": vision_raw_data
                    }

                    vision_batch_logs.append(batch_log)

                    print(f"\n第 {index + 1} 行，第 {i // VISION_BATCH_SIZE + 1} 批图片识别过滤后结果：")
                    print(json.dumps(vision_data, ensure_ascii=False, indent=2))

                    if vision_data:
                        extracted_data.update(vision_data)
                        vision_fields_all.extend(list(vision_data.keys()))
                        empty_batch_count = 0
                        print(f"本批次视觉补全成功：{vision_data}")
                    else:
                        empty_batch_count += 1
                        print(f"本批次没有补出有效字段，连续空结果批次数：{empty_batch_count}")

                    time.sleep(0.2)

            else:
                print(f"\n第 {index + 1} 行仍缺失：{missing_fields}，但未找到有效图片链接。")

        elif missing_fields:
            if not enable_vision:
                print(f"\n第 {index + 1} 行文本后仍缺失：{missing_fields}，图片识别已关闭，保留空值。")
            else:
                blocked_fields = [field for field in missing_fields if field not in VISION_ALLOWED_FIELDS]

                if blocked_fields:
                    print(f"\n第 {index + 1} 行仍缺失：{missing_fields}")
                    print(f"其中这些字段不允许图片阶段补全，保留空值：{blocked_fields}")

        for field in TARGET_FIELDS:
            value = extracted_data.get(field, "")

            if not is_empty(value) and is_empty(df.at[index, field]):
                df.at[index, field] = value

        final_missing_fields = []

        for field in TARGET_FIELDS:
            if is_empty(df.at[index, field]):
                final_missing_fields.append(field)

        df.at[index, "文本提取字段"] = "；".join(sorted(set(text_fields)))
        df.at[index, "图片识别提取字段"] = "；".join(sorted(set(vision_fields_all)))
        df.at[index, "图片识别批次日志"] = json.dumps(vision_batch_logs, ensure_ascii=False)
        df.at[index, "最终缺失字段"] = "；".join(final_missing_fields)
        df.at[index, "提取完整状态"] = "是" if not final_missing_fields else "否"

        if (index + 1) % SAVE_EVERY == 0:
            os.makedirs(os.path.dirname(OUTPUT_FILE) or ".", exist_ok=True)
            df.to_excel(OUTPUT_FILE, index=False)
            print(f"\n已临时保存到：{OUTPUT_FILE}")

        time.sleep(0.3)

        # 检查停止信号
        if STOP_FILE and os.path.exists(STOP_FILE):
            os.remove(STOP_FILE)
            print(f"\n[停止] 收到停止信号，保存已处理数据后退出。")
            break

    os.makedirs(os.path.dirname(OUTPUT_FILE) or ".", exist_ok=True)
    df.to_excel(OUTPUT_FILE, index=False)
    print(f"\n处理完成！结果已保存至：{OUTPUT_FILE}")


if __name__ == "__main__":
    main()
