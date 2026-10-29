# -*- coding: utf-8 -*-
import os
import sys
import math
import time
import json
import re
import hashlib
from collections import Counter
from io import BytesIO
from pathlib import Path

import pandas as pd

# Direct CLI and the embedded runner both use the same safe I/O implementation.
if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core.report_io import (category_output_path, category_checkpoint_path,
                            normalized_path, require_distinct, write_json, write_excel,
                            SafeWriteError)

BATCH_SIZE = 20
SLEEP_SECONDS = 1.0
PROMPT_VERSION = 1
DEFAULT_INPUT = './欧洲市场规划/德国站类目_匹配度评估_中间结果.xlsx'

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

STATUS = '处理状态'
ERROR = '错误原因'
PARAM_HASH = '类目评估参数指纹'
ROW_HASH = '类目评估行指纹'
SUCCESS, FAILED, REVIEW, CONFIRMED, PENDING = '成功', '可重试失败', '待人工审核', '人工确认', '待处理'
STATE_FIELDS = [STATUS, ERROR, PARAM_HASH, ROW_HASH]
INPUT_FIELDS = ['Node root', '是否考虑', '网址链接', 'Node ID', 'Node Path', '二级类目', '类目路径_中文']
ENUMS = {
    '电工归属': {'核心电工', '相邻电工', '非电工'},
    '匹配度等级': {'高匹配', '中匹配', '低匹配', '不匹配'},
    '是否建议进入下一轮': {'建议重点验证', '可观察', '暂不建议'},
    '判断信心': {'高', '中', '低'},
}
SCORE_FIELDS = OUTPUT_FIELDS[3:9]


def safe_str(v):
    return str(v).strip() if pd.notna(v) else ''


def fingerprint(payload):
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                     allow_nan=False).encode('utf-8')).hexdigest()


def validate_result(result):
    """Return a non-sensitive reason, never raw model content or request errors."""
    if not isinstance(result, dict) or any(field not in result for field in OUTPUT_FIELDS):
        return '缺少必需字段'
    for field, choices in ENUMS.items():
        if not isinstance(result[field], str) or result[field] not in choices:
            return f'{field}枚举非法'
    for field in SCORE_FIELDS + ['总分', '百分制得分']:
        value = result[field]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f'{field}必须为有限数值'
        # Bound integers before converting to float (JSON integers can be enormous).
        upper = 5 if field in SCORE_FIELDS else 30 if field == '总分' else 100
        if not 0 <= value <= upper or not math.isfinite(value):
            return f'{field}必须为0到{upper}之间的有限数值'
    total = sum(result[field] for field in SCORE_FIELDS)
    if not math.isclose(result['总分'], total, abs_tol=0.001):
        return '总分与六项评分不一致'
    if not math.isclose(result['百分制得分'], total * 100 / 30, abs_tol=0.11):
        return '百分制得分与总分不一致'
    for field in ['主要匹配理由', '主要风险或不确定性', '简短结论']:
        if not isinstance(result[field], str) or not result[field].strip():
            return f'{field}必须为非空文本'
        if len(result[field]) > 32767:
            return f'{field}超过Excel单元格文本上限'
        if re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]', result[field]):
            return f'{field}含有Excel不支持的字符'
    return ''


def validate_batch(payload, indexes):
    """Keep valid partial rows; duplicates invalidate that row, never last-wins."""
    if not isinstance(payload, dict) or not isinstance(payload.get('results'), list):
        return {}, {idx: '返回结构缺少results数组' for idx in indexes}, ['返回结构非法']
    results = payload['results']
    ids = [r.get('row_index') for r in results if isinstance(r, dict) and type(r.get('row_index')) is int]
    counts = Counter(ids)
    valid, errors, issues = {}, {}, []
    for result in results:
        if not isinstance(result, dict) or type(result.get('row_index')) is not int:
            issues.append('row_index必须为整数（不接受布尔、字符串或小数）')
            continue
        idx = result['row_index']
        if idx not in indexes:
            issues.append('返回了不属于当前批次的行号')
            continue
        reason = '重复row_index' if counts[idx] > 1 else validate_result(result)
        if reason:
            errors[idx] = reason
        else:
            valid[idx] = {field: result[field] for field in OUTPUT_FIELDS}
    for idx in indexes:
        if idx not in valid and idx not in errors:
            errors[idx] = '模型遗漏该行或行号非法'
    return valid, errors, issues

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

def evaluate_categories_batch(batch_items, client, model_name, company_profile, should_stop=lambda: False):
    input_json = json.dumps(batch_items, ensure_ascii=False, indent=2)

    prompt = f"""
你是一名跨境电商类目评估顾问，擅长根据公司现有产品线、供应链、技术边界、品牌定位和零售渠道特点，
对亚马逊德国站类目进行结构化匹配度判断。

【公司能力画像】
{company_profile}

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
        if should_stop():
            raise KeyboardInterrupt
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {'role': 'system', 'content': '你是一个严格的结构化类目评估器，只输出合法 JSON。'},
                    {'role': 'user', 'content': prompt}
                ],
                temperature=0.1,
                max_tokens=5000
            )
            return safe_json_loads(response.choices[0].message.content)
        except Exception:
            if attempt == 2:
                # Exception strings may contain request headers, keys or model text.
                raise ValueError('模型请求或JSON解析失败，请检查服务设置后重试') from None
            time.sleep(2 + attempt)


def row_fingerprint(row):
    return fingerprint({field: safe_str(row[field]) for field in INPUT_FIELDS + ['根节点 翻译']})


def prepare_rows(df, params_hash):
    for field in INPUT_FIELDS:
        if field not in df.columns:
            raise ValueError(f'Excel 中缺少必需列：{field}')
    if '根节点 翻译' not in df:
        df['根节点 翻译'] = ''
    for field in OUTPUT_FIELDS + STATE_FIELDS:
        if field not in df:
            df[field] = ''
        # pandas 3 rejects assigning text to a numeric column read from Excel.
        df[field] = df[field].astype(object)
    for idx, row in df.iterrows():
        status = safe_str(row[STATUS])
        if status == CONFIRMED:
            continue  # Human confirmation is authoritative, including custom conclusions.
        compatible = (not safe_str(row[PARAM_HASH]) or safe_str(row[PARAM_HASH]) == params_hash)
        compatible &= (not safe_str(row[ROW_HASH]) or safe_str(row[ROW_HASH]) == row_fingerprint(row))
        valid = not validate_result(row.to_dict())
        if compatible and valid and status in ('', SUCCESS):
            df.at[idx, STATUS] = REVIEW if row['判断信心'] == '低' else SUCCESS
            df.at[idx, ERROR] = '低信心，待人工审核或重新评估' if row['判断信心'] == '低' else ''
        elif status != REVIEW or not compatible or not valid:
            df.at[idx, STATUS] = PENDING
            df.at[idx, ERROR] = ''
            for field in OUTPUT_FIELDS:
                df.at[idx, field] = ''
        df.at[idx, PARAM_HASH] = params_hash
        df.at[idx, ROW_HASH] = row_fingerprint(row)


def restore_checkpoint(df, checkpoint, binding):
    if not checkpoint.exists():
        return
    try:
        saved = json.loads(checkpoint.read_text(encoding='utf-8'))
        if not isinstance(saved, dict) or saved.get('binding') != binding:
            print('断点与源内容/顺序或有效参数不一致，未复用旧断点。')
            return
        rows = saved.get('rows')
        if not isinstance(rows, dict):
            raise ValueError
        restored = 0
        for idx, row in df.iterrows():
            if row[STATUS] == CONFIRMED:
                continue
            record = rows.get(str(idx))
            if not isinstance(record, dict) or record.get(ROW_HASH) != row_fingerprint(row):
                continue
            if record.get(PARAM_HASH) != binding['params']:
                continue
            status = record.get(STATUS)
            if status not in (SUCCESS, FAILED, REVIEW) or not isinstance(record.get(ERROR), str):
                continue
            if status in (SUCCESS, REVIEW):
                if validate_result(record):
                    continue
                if (status == SUCCESS) != (record['判断信心'] != '低'):
                    continue
            for field in OUTPUT_FIELDS + STATE_FIELDS:
                value = record.get(field, '')
                df.at[idx, field] = '' if status == FAILED and field in OUTPUT_FIELDS else value
            restored += 1
        print(f'已恢复断点行数：{restored}')
    except (OSError, ValueError, TypeError):
        print('断点无法读取或结构无效，未复用；将按输入中的行状态继续。')


def run_screening(input_file, output_file='', checkpoint_file='', *, client=None,
                  model_name=None, base_url=None, company_profile=None, batch_size=BATCH_SIZE,
                  should_stop=None):
    source = normalized_path(input_file)
    output = category_output_path(source, output_file)
    checkpoint = category_checkpoint_path(source, checkpoint_file)
    require_distinct(source, output, checkpoint)  # Before mkdir, client or any write.
    if output.suffix.lower() != '.xlsx' or checkpoint.suffix.lower() != '.json':
        raise ValueError('结果必须为.xlsx，独立断点必须为.json；不再将工作簿用作断点。')
    if type(batch_size) is not int or batch_size <= 0:
        raise ValueError('批次大小必须为正整数')
    model_name = model_name or os.getenv('MODEL_NAME', 'deepseek-ai/DeepSeek-V3')
    base_url = base_url or os.getenv('BASE_URL', 'https://api.siliconflow.cn/v1')
    company_profile = COMPANY_PROFILE if company_profile is None else company_profile
    params_hash = fingerprint({'model': model_name, 'base_url': base_url, 'profile': company_profile,
                               'prompt_version': PROMPT_VERSION, 'temperature': 0.1,
                               'max_tokens': 5000, 'batch_size': batch_size})
    # Read the exact bytes being fingerprinted; never reopen a changed source to evaluate.
    contents = source.read_bytes()
    binding = {'source_path': str(source).casefold(),
               'source_sha256': hashlib.sha256(contents).hexdigest(), 'params': params_hash, 'schema': 2}
    df = pd.read_excel(BytesIO(contents))
    prepare_rows(df, params_hash)
    restore_checkpoint(df, checkpoint, binding)
    pending = [idx for idx, row in df.iterrows()
               if safe_str(row['是否考虑']) in ('1', '1.0') and row[STATUS] not in (SUCCESS, CONFIRMED)]
    summary = {'成功': 0, '失败': 0, '跳过': len(df) - len(pending), '待审': 0,
               '未处理': len(pending), '协议异常': 0, '已停止': False,
               '输出': str(output), '断点': str(checkpoint)}
    print(f'总行数：{len(df)}；待处理类目数：{len(pending)}；跳过：{summary["跳过"]}')
    print(f'输入只读；实际输出：{output}；独立断点：{checkpoint}')
    should_stop = should_stop or (lambda: False)
    owned_client = False
    save_errors = []

    def save_checkpoint():
        rows = {}
        for idx, row in df.iterrows():
            if row[STATUS] in (SUCCESS, FAILED, REVIEW):
                # Values here came from validated model JSON, or Excel scalar cells.
                rows[str(idx)] = {field: ('' if pd.isna(row[field]) else row[field])
                                  for field in OUTPUT_FIELDS + STATE_FIELDS}
        write_json(checkpoint, {'binding': binding, 'rows': rows}, protected_paths=(source, output))
        print(f'已保存独立断点：{checkpoint}')

    try:
        for start in range(0, len(pending), batch_size):
            if should_stop():
                summary['已停止'] = True
                break
            batch_idx = pending[start:start + batch_size]
            items = []
            for idx in batch_idx:
                row = df.loc[idx]
                item = {field: safe_str(row[field]) for field in INPUT_FIELDS if field != '是否考虑'}
                item.update(row_index=int(idx), 根节点翻译=safe_str(row['根节点 翻译']))
                items.append(item)
            try:
                if client is None:
                    key = os.getenv('API_KEY') or os.getenv('SILICONFLOW_API_KEY')
                    if not key:
                        raise ValueError('未配置API Key')
                    from openai import OpenAI
                    client = OpenAI(api_key=key, base_url=base_url, timeout=60.0, max_retries=0)
                    owned_client = True
                payload = evaluate_categories_batch(items, client, model_name, company_profile, should_stop)
                valid, errors, issues = validate_batch(payload, batch_idx)
            except Exception:
                valid, errors, issues = {}, {idx: '模型请求或解析失败；请检查服务设置后重试' for idx in batch_idx}, []
            summary['协议异常'] += len(issues)
            if issues:
                print('模型响应存在协议异常：' + '；'.join(sorted(set(issues))))
            for idx in batch_idx:
                for field in OUTPUT_FIELDS:
                    df.at[idx, field] = valid.get(idx, {}).get(field, '')
                if idx in errors:
                    status, reason = FAILED, errors[idx]
                    summary['失败'] += 1
                elif valid[idx]['判断信心'] == '低':
                    status, reason = REVIEW, '低信心，待人工审核或重新评估'
                    summary['待审'] += 1
                else:
                    status, reason = SUCCESS, ''
                    summary['成功'] += 1
                df.at[idx, STATUS], df.at[idx, ERROR] = status, reason
                summary['未处理'] -= 1
            save_checkpoint()  # Every completed batch; before sorting any result rows.
            if should_stop():
                summary['已停止'] = True
                break
            if start + batch_size < len(pending):
                time.sleep(SLEEP_SECONDS)
    except KeyboardInterrupt:
        summary['已停止'] = True
        print('收到停止请求，正在保存已处理行和独立断点。')
    except SafeWriteError as exc:
        save_errors.append(str(exc))
        print('批次断点保存受阻，停止后续请求并尝试另存已处理结果。')
    finally:
        if owned_client:
            try:
                client.close()
            except Exception:
                pass

    # Even when checkpoint replacement is blocked, try to deliver a separate result.
    try:
        save_checkpoint()
    except SafeWriteError as exc:
        save_errors.append(str(exc))
    order = pd.to_numeric(df['百分制得分'], errors='coerce').sort_values(ascending=False, kind='stable').index
    try:
        write_excel(output, {'Sheet1': df.loc[order]}, protected_paths=(source, checkpoint))
    except SafeWriteError as exc:
        save_errors.append(str(exc))
    for error in save_errors:
        print(error)
    summary['exit_code'] = (1 if save_errors else 130 if summary['已停止'] else
                            2 if summary['失败'] or summary['待审'] or summary['协议异常'] else 0)
    print('本次摘要：' + '；'.join(f'{key}={value}' for key, value in summary.items()))
    return summary


def main():
    source = os.getenv('CATEGORY_INPUT_FILE') or DEFAULT_INPUT
    output = os.getenv('CATEGORY_OUTPUT_FILE', '')
    checkpoint = os.getenv('CATEGORY_CHECKPOINT_FILE', '')
    # 两种停止信号都认：本模块 UI 的停止按钮，以及关窗时全局执行器发出的协作停止。
    stop_files = [text.strip() for text in (os.getenv('CATEGORY_STOP_FILE', ''),
                                            os.getenv('PM_STACK_STOP_FILE', ''))
                  if text.strip()]
    try:
        if stop_files:
            require_distinct(source, category_output_path(source, output),
                             category_checkpoint_path(source, checkpoint), *stop_files)
        result = run_screening(source, output, checkpoint,
                               should_stop=lambda: any(Path(path).exists() for path in stop_files))
        return result['exit_code']
    except (ValueError, SafeWriteError) as exc:
        print(f'类目筛选未完成：{exc}')
        return 1
    except Exception:
        print('类目筛选未完成：无法读取输入或保存任务，请检查文件和运行日志中的输出/断点位置。')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
