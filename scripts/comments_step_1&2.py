# -*- coding: utf-8 -*-
"""
comments_step_1&2.py

批量运行 comments_step_1.py 和 comments_step_2.py。

特点：
1. 子脚本路径按当前脚本目录查找，避免工作目录变化导致找不到脚本。
2. 自动创建输出目录。
3. 支持通过任务字段 SKIP_STEP1 / SKIP_STEP2 临时跳过某一步。
4. 支持自动识别子脚本文件名：
   - comments_step_1.py / comments_step_1_stat_strategy.py / comments_step_1_modified.py
   - comments_step_2.py / comments_step_2_stat_strategy.py / comments_step_2_modified.py
   也可通过环境变量 STEP1_SCRIPT / STEP2_SCRIPT 指定。
"""

import os
import subprocess
import sys
from pathlib import Path

print("脚本已启动")

SCRIPT_DIR = Path(__file__).resolve().parent

# ================= 公共配置 =================
COMMON_CONFIG = {
    "API_ENV_NAME": "API_KEY",
    "BASE_URL": "https://api.siliconflow.cn/v1",
    "MODEL_NAME": "deepseek-ai/DeepSeek-V3",
    "CONFIG_FILE": "./product_configs.json",
    "COMMENT_COLUMN": "内容",
}

# ================= 待处理任务列表 =================
# 你可以在这里复制/新增更多 ASIN 任务。
TASKS = [
    # {
    #     "CURRENT_PRODUCT": "vacuum auto switch",
    #     "RAW_INPUT_FILE": "./联动插座_US_评论/评论数据_B0BFDB9MSB.xlsx",
    #     "STEP1_OUTPUT_FILE": "./联动插座_US_评论/评论数据_B0BFDB9MSB_AI处理_stat.xlsx",
    #     "STEP2_OUTPUT_FILE": "./联动插座_US_评论/评论数据_B0BFDB9MSB_AI总结_stat.xlsx",
    #     "TARGET_SHEETS": "5 star,4 star,3 star,2 star,1 star",
    # },
    {
        "CURRENT_PRODUCT": "vacuum auto switch",
        "RAW_INPUT_FILE": "./联动插座_US_评论/评论数据_B0CBJ6QHKT.xlsx",
        "STEP1_OUTPUT_FILE": "./联动插座_US_评论/评论数据_B0CBJ6QHKT_AI处理_stat.xlsx",
        "STEP2_OUTPUT_FILE": "./联动插座_US_评论/评论数据_B0CBJ6QHKT_AI总结_stat.xlsx",
        "TARGET_SHEETS": "5 star,4 star,3 star,2 star,1 star",
    },
    {
        "CURRENT_PRODUCT": "vacuum auto switch",
        "RAW_INPUT_FILE": "./联动插座_US_评论/评论数据_B07YK9VBQK.xlsx",
        "STEP1_OUTPUT_FILE": "./联动插座_US_评论/评论数据_B07YK9VBQK_AI处理_stat.xlsx",
        "STEP2_OUTPUT_FILE": "./联动插座_US_评论/评论数据_B07YK9VBQK_AI总结_stat.xlsx",
        "TARGET_SHEETS": "5 star,4 star,3 star,2 star,1 star",
    },
]


def find_script(env_name: str, candidates: list) -> Path:
    """优先使用环境变量指定脚本；否则按候选文件名在当前目录查找。"""
    env_value = os.getenv(env_name)
    if env_value:
        p = Path(env_value)
        if not p.is_absolute():
            p = SCRIPT_DIR / p
        if p.exists():
            return p
        raise FileNotFoundError(f"{env_name} 指定的脚本不存在：{p}")

    for name in candidates:
        p = SCRIPT_DIR / name
        if p.exists():
            return p

    raise FileNotFoundError(f"未找到子脚本，候选文件名：{candidates}")


def build_env(task: dict) -> dict:
    env = os.environ.copy()
    env.update(COMMON_CONFIG)
    env.update({k: str(v) for k, v in task.items()})
    return env


def ensure_parent_dir(file_path: str):
    if not file_path:
        return
    parent = Path(file_path).expanduser().resolve().parent
    parent.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    print("进入主程序")

    api_env_name = COMMON_CONFIG["API_ENV_NAME"]
    print(f"准备检查环境变量: {api_env_name}")
    print(f"环境变量是否存在: {bool(os.getenv(api_env_name))}")

    if not os.getenv(api_env_name):
        raise ValueError(f"未检测到环境变量 {api_env_name}，请先设置后再运行。")

    step1_script = find_script(
        "STEP1_SCRIPT",
        ["comments_step_1.py", "comments_step_1_stat_strategy.py", "comments_step_1_modified.py"],
    )
    step2_script = find_script(
        "STEP2_SCRIPT",
        ["comments_step_2.py", "comments_step_2_stat_strategy.py", "comments_step_2_modified.py"],
    )

    scripts = [
        (step1_script, "SKIP_STEP1"),
        (step2_script, "SKIP_STEP2"),
    ]

    print(f"Step1脚本: {step1_script}")
    print(f"Step2脚本: {step2_script}")

    # 优先使用环境变量（GUI 调用），否则使用硬编码 TASKS
    if os.getenv("RAW_INPUT_FILE"):
        tasks = [{
            "CURRENT_PRODUCT": os.getenv("CURRENT_PRODUCT", ""),
            "RAW_INPUT_FILE": os.getenv("RAW_INPUT_FILE", ""),
            "STEP1_OUTPUT_FILE": os.getenv("STEP1_OUTPUT_FILE", ""),
            "STEP2_OUTPUT_FILE": os.getenv("STEP2_OUTPUT_FILE", ""),
            "TARGET_SHEETS": os.getenv("TARGET_SHEETS", ""),
        }]
        print(f"模式: 环境变量传入（GUI 调用）")
    else:
        tasks = TASKS
        print(f"模式: 硬编码任务列表")

    print(f"TASKS 数量 = {len(tasks)}")

    for i, task in enumerate(tasks, start=1):
        print("\n" + "=" * 70)
        print(f"开始处理第 {i}/{len(tasks)} 个任务")
        print(f"品类: {task['CURRENT_PRODUCT']}")
        print(f"输入文件: {task['RAW_INPUT_FILE']}")
        print("=" * 70)

        if not os.path.exists(task["RAW_INPUT_FILE"]):
            print(f"[FAIL] 输入文件不存在：{task['RAW_INPUT_FILE']}")
            sys.exit(1)

        ensure_parent_dir(task.get("STEP1_OUTPUT_FILE", ""))
        ensure_parent_dir(task.get("STEP2_OUTPUT_FILE", ""))

        env = build_env(task)

        for script_path, skip_flag in scripts:
            if str(task.get(skip_flag, "")).lower() in ("1", "true", "yes", "y"):
                print(f"\n========== 跳过 {script_path.name}：{skip_flag}=True ==========")
                continue

            print(f"\n========== 开始运行 {script_path.name} ==========")
            result = subprocess.run([sys.executable, str(script_path)], env=env)
            print(f"{script_path.name} 返回码: {result.returncode}")

            if result.returncode != 0:
                print(f"\n[FAIL] {script_path.name} 运行失败，流程中止。")
                sys.exit(result.returncode)

        print(f"\n[OK] 当前任务处理完成：{task['RAW_INPUT_FILE']}")

    print("\n[OK] 所有任务已全部处理完成。")
