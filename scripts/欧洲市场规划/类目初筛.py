# -*- coding: utf-8 -*-
import os
import math
import time
import json
import re
import pandas as pd
from openai import OpenAI
from tqdm import tqdm

# ================= 配置区 =================
API_KEY = os.getenv("API_KEY") or os.getenv("SILICONFLOW_API_KEY")
BASE_URL = os.getenv("BASE_URL", "https://api.siliconflow.cn/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "deepseek-ai/DeepSeek-V3")

INPUT_FILE = os.getenv("CATEGORY_INPUT_FILE", "./欧洲市场规划/德国站类目_匹配度评估_中间结果.xlsx")
OUTPUT_FILE = os.getenv("CATEGORY_OUTPUT_FILE", "./欧洲市场规划/德国站类目_匹配度评估_AI.xlsx")
CHECKPOINT_FILE = os.getenv("CATEGORY_CHECKPOINT_FILE", INPUT_FILE)
for path in (OUTPUT_FILE, CHECKPOINT_FILE):
    path_dir = os.path.dirname(path)
    if path_dir:
        os.makedirs(path_dir, exist_ok=True)

BATCH_SIZE = 20
SLEEP_SECONDS = 1.0
CHECKPOINT_EVERY = 5

COMPANY_PROFILE = """
我们公司的主要产品线包括：

1. 连接类：
线盘、延长线、普通插排、工具排插、高功率线、RV线、GFCI线、户外插座盒、功能插座

2. 墙装类：
电工面板、入墙插座、入墙开关

3. 控制类：
室内/户外遥控插座、遥控接线模块、室内/户外定时器、入墙定时器、地插定时器、
室内/户外调光器、入墙调光器、感应开关、光感灯头、遥控灯头、普通灯头、灯头转换插座

4. 能控/低压类：
AC/AC变压器、AC/DC变压器、变压器光控开关、温控插座、温控器、电量计

5. 庭院/户外相邻类：
水管定时器、水管盘、水管、喷水枪、通风扇、温控器

6. 工具与附件类：
电量计、测量工具、气管、变压器零件、配件

我们的核心能力：
- 家用/庭院/车库/户外场景下的电源连接、分配与控制
- 防水场景、户外供电、轻电子控制
- 遥控、定时、调光、光感、温控等终端零售型产品
- 亚马逊零售逻辑下可解释、用户可直接购买使用的产品

我们的弱项或谨慎方向：
- 配电箱、断路器、建筑布线主材、专业配电保护器件
- 强安装型建筑电工产品
- 高专业门槛 DIN 导轨系统
- 重软件、强App、复杂智能家居主设备
- 逆变器、整机wallbox、整套储能、工业强电系统

评估时，请重点看：
这个类目是否属于终端零售型的连接、分配、控制、户外、防水、轻智能电工产品；
而不是工程安装型、专业配电型、系统集成型产品。
"""

OUTPUT_FIELDS = [
    "电工归属",
    "匹配度等级",
    "是否建议进入下一轮",
    "产品相邻性",
    "供应链复用度",
    "场景一致性",
    "认证与安装复杂度适配度",
    "品牌延展性",
    "零售友好度",
    "总分",
    "百分制得分",
    "主要匹配理由",
    "主要风险或不确定性",
    "判断信心",
    "简短结论"
]

if not API_KEY:
    raise ValueError("未找到 API Key，请先在设置中配置 API Key。")

client = OpenAI(
    api_key=API_KEY,
    base_url=BASE_URL
)

def safe_str(v):
    return str(v).strip() if pd.notna(v) else ""

def safe_json_loads(content: str):
    content = content.strip()

    try:
        return json.loads(content)
    except:
        pass

    cleaned = re.sub(r"^```json\s*|\s*```$", "", content, flags=re.DOTALL).strip()
    try:
        return json.loads(cleaned)
    except:
        pass

    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if match:
        return json.loads(match.group())

    raise ValueError("模型返回内容无法解析为 JSON")

def evaluate_categories_batch(batch_items):
    input_json = json.dumps(batch_items, ensure_ascii=False, indent=2)

    prompt = f"""
你是一名跨境电商类目评估顾问，擅长根据公司现有产品线、供应链、技术边界、品牌定位和零售渠道特点，
对亚马逊德国站类目进行结构化匹配度判断。

【公司能力画像】
{COMPANY_PROFILE}

【任务】
请对下面输入的每个类目做公司匹配度评估。
注意：这不是市场规模评估，而是判断“这个类目与我们公司的资源和技术是否匹配，是否值得进入下一轮调研”。

【输入字段说明】
我会提供以下类目信息：
- Node root
- 根节点翻译
- 网址链接
- Node ID
- Node Path（德文路径）
- 二级类目
- 类目路径_中文

请优先结合“类目路径_中文”和“Node Path”理解该类目的真实含义。

【评分维度】
请对每个类目按以下 6 个维度打分，每项 0-5 分：
1. 产品相邻性
2. 供应链复用度
3. 场景一致性
4. 认证与安装复杂度适配度
5. 品牌延展性
6. 零售友好度

总分 = 6项相加，满分30分
百分制得分 = 总分 * 100 / 30

【输出要求】
请对每个类目输出以下字段：
- row_index
- 电工归属：核心电工 / 相邻电工 / 非电工
- 匹配度等级：高匹配 / 中匹配 / 低匹配 / 不匹配
- 是否建议进入下一轮：建议重点验证 / 可观察 / 暂不建议
- 产品相邻性
- 供应链复用度
- 场景一致性
- 认证与安装复杂度适配度
- 品牌延展性
- 零售友好度
- 总分
- 百分制得分
- 主要匹配理由（中文，3条，用“；”分隔）
- 主要风险或不确定性（中文，3条，用“；”分隔）
- 判断信心：高 / 中 / 低
- 简短结论（中文一句话）

【判断规则】
1. 只能基于输入信息和合理常识判断，不得脑补我们没有提供的能力
2. 不要把“电工相关”直接等同于“适合我们做”
3. 如果类目明显偏工程安装、专业配电、重系统集成，应显著降分
4. 如果信息不足，请降低判断信心
5. 输出必须是合法 JSON，且只输出 JSON，不要输出其他文字

【返回 JSON 格式示例】
{{
  "results": [
    {{
      "row_index": 0,
      "电工归属": "核心电工",
      "匹配度等级": "高匹配",
      "是否建议进入下一轮": "建议重点验证",
      "产品相邻性": 5,
      "供应链复用度": 4,
      "场景一致性": 5,
      "认证与安装复杂度适配度": 4,
      "品牌延展性": 5,
      "零售友好度": 5,
      "总分": 28,
      "百分制得分": 93.3,
      "主要匹配理由": "与现有连接类产品接近；可复用户外和防水能力；终端零售属性强",
      "主要风险或不确定性": "德国站本地认证要求可能更高；需验证价格带；需验证头部品牌集中度",
      "判断信心": "高",
      "简短结论": "该类目与公司现有连接和控制能力高度接近，建议进入下一轮验证。"
    }}
  ]
}}

【待评估类目】
{input_json}
"""

    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": "你是一个严格的结构化类目评估器，只输出合法 JSON。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=5000
            )

            content = response.choices[0].message.content.strip()
            parsed = safe_json_loads(content)

            if "results" not in parsed or not isinstance(parsed["results"], list):
                raise ValueError("返回 JSON 中缺少 results 数组")

            return parsed["results"]

        except Exception as e:
            if attempt == 2:
                print(f"批量评估失败（最终）: {e}")
                return []
            time.sleep(2 + attempt)

if __name__ == "__main__":
    df = pd.read_excel(INPUT_FILE)

    required_columns = ["Node root", "是否考虑", "网址链接", "Node ID", "Node Path", "二级类目", "类目路径_中文"]
    for col in required_columns:
        if col not in df.columns:
            raise ValueError(f"Excel 中缺少必需列：{col}")

    optional_columns = ["根节点 翻译"]
    for col in optional_columns:
        if col not in df.columns:
            df[col] = ""

    for col in OUTPUT_FIELDS:
        if col not in df.columns:
            df[col] = ""

    def is_done(row):
        return safe_str(row["匹配度等级"]) != ""

    # 只处理“是否考虑”=1 且还没处理过的
    pending_indexes = [
        idx for idx, row in df.iterrows()
        if safe_str(row["是否考虑"]) in ["1", "1.0"] and not is_done(row)
    ]

    print(f"总行数：{len(df)}")
    print(f"待处理类目数：{len(pending_indexes)}")

    total_batches = math.ceil(len(pending_indexes) / BATCH_SIZE) if pending_indexes else 0
    batch_counter = 0

    for start in tqdm(range(0, len(pending_indexes), BATCH_SIZE), total=total_batches, desc="AI评估进度"):
        batch_counter += 1
        batch_idx = pending_indexes[start:start + BATCH_SIZE]

        batch_items = []
        for idx in batch_idx:
            row = df.loc[idx]
            item = {
                "row_index": int(idx),
                "Node root": safe_str(row["Node root"]),
                "根节点翻译": safe_str(row["根节点 翻译"]),
                "网址链接": safe_str(row["网址链接"]),
                "Node ID": safe_str(row["Node ID"]),
                "Node Path": safe_str(row["Node Path"]),
                "二级类目": safe_str(row["二级类目"]),
                "类目路径_中文": safe_str(row["类目路径_中文"])
            }
            batch_items.append(item)

        ai_results = evaluate_categories_batch(batch_items)

        ai_map = {}
        for r in ai_results:
            if "row_index" in r:
                ai_map[int(r["row_index"])] = r

        for idx in batch_idx:
            if idx not in ai_map:
                df.at[idx, "匹配度等级"] = "人工审核"
                df.at[idx, "是否建议进入下一轮"] = "人工审核"
                df.at[idx, "判断信心"] = "人工审核"
                df.at[idx, "简短结论"] = "模型未正常返回该类目结果，建议人工复核。"
                continue

            r = ai_map[idx]
            for field in OUTPUT_FIELDS:
                df.at[idx, field] = r.get(field, "")

        if batch_counter % CHECKPOINT_EVERY == 0:
            df.to_excel(CHECKPOINT_FILE, index=False)
            print(f"已保存中间结果：{CHECKPOINT_FILE}")

        time.sleep(SLEEP_SECONDS)

    try:
        df["百分制得分_数值"] = pd.to_numeric(df["百分制得分"], errors="coerce")
        df = df.sort_values(by="百分制得分_数值", ascending=False)
        df.drop(columns=["百分制得分_数值"], inplace=True)
    except:
        pass

    df.to_excel(OUTPUT_FILE, index=False)
    print(f"处理完成，结果已保存到：{OUTPUT_FILE}")
