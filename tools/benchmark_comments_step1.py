# -*- coding: utf-8 -*-
"""Run repeatable Step 1 concurrency benchmarks without exposing the API key."""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.config_manager import ConfigManager


def find_default_input():
    candidates = sorted(
        PROJECT_ROOT.glob(
            "测试数据集/VOC/Strip/**/B07WZP86CW-US-Reviews-*.xlsx"
        )
    )
    for path in candidates:
        if "_AI" not in path.name:
            return path
    raise FileNotFoundError("未找到默认的 B07WZP86CW 原始评论文件")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=None)
    parser.add_argument("--product", default="power strip")
    parser.add_argument("--concurrency", nargs="+", type=int, default=[1, 4, 8, 12])
    parser.add_argument("--rpm", type=int, default=900)
    parser.add_argument("--tpm", type=int, default=90000)
    return parser.parse_args()


def main():
    args = parse_args()
    input_path = (args.input or find_default_input()).resolve()
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    manager = ConfigManager()
    api_key = manager.get("api_key")
    if not api_key:
        raise ValueError("本机 PM Stack 配置中没有可用的 API Key")

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = PROJECT_ROOT / "测试数据集" / f"并发压测_{run_id}"
    output_dir.mkdir(parents=True, exist_ok=False)
    config_path = PROJECT_ROOT / "scripts" / "product_configs.json"
    script_path = PROJECT_ROOT / "scripts" / "comments_step_1_fast.py"
    stop_path = Path(os.getenv("TEMP", str(output_dir))) / "comment_stop.signal"
    try:
        stop_path.unlink()
    except FileNotFoundError:
        pass

    base_env = dict(os.environ)
    base_env.update({
        "API_KEY": str(api_key),
        "BASE_URL": str(manager.get("base_url") or "https://api.siliconflow.cn/v1"),
        "MODEL_NAME": str(manager.get("model_name") or "deepseek-ai/DeepSeek-V3"),
        "RAW_INPUT_FILE": str(input_path),
        "CONFIG_FILE": str(config_path),
        "CURRENT_PRODUCT": args.product,
        "TARGET_SHEETS": "",
        "STEP1_RPM_LIMIT": str(max(0, args.rpm)),
        "STEP1_TPM_LIMIT": str(max(0, args.tpm)),
        "STEP1_MAX_FAILURE_RATE": "0",
        "STEP1_REQUEST_TIMEOUT": "90",
        "STEP1_PROGRESS_EVERY": "20",
        "STEP1_CHECKPOINT_EVERY": "20",
        "PYTHONIOENCODING": "utf-8",
    })

    summary = {
        "input": str(input_path),
        "product": args.product,
        "model": base_env["MODEL_NAME"],
        "rpm_limit": args.rpm,
        "tpm_limit": args.tpm,
        "runs": [],
    }
    print(f"BENCHMARK_DIR={output_dir}", flush=True)
    print(f"INPUT={input_path}", flush=True)

    for concurrency in args.concurrency:
        concurrency = max(1, min(32, int(concurrency)))
        output_path = output_dir / f"step1_c{concurrency}.xlsx"
        log_path = output_dir / f"step1_c{concurrency}.log"
        env = dict(base_env)
        env["STEP1_CONCURRENCY"] = str(concurrency)
        env["STEP1_OUTPUT_FILE"] = str(output_path)

        print(f"BENCHMARK_START concurrency={concurrency}", flush=True)
        started = time.monotonic()
        with log_path.open("w", encoding="utf-8") as log_file:
            process = subprocess.Popen(
                [sys.executable, str(script_path)],
                cwd=str(PROJECT_ROOT),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            for line in process.stdout:
                log_file.write(line)
                # 保留关键进度与指标，减少终端噪声。
                if (
                    line.startswith("进度:")
                    or "真实 API 请求" in line
                    or "Token:" in line
                    or "实际总耗时" in line
                    or "有效吞吐" in line
                    or line.startswith("[限流]")
                    or line.startswith("[需补跑]")
                ):
                    print(f"c{concurrency} {line.rstrip()}", flush=True)
            return_code = process.wait()

        elapsed = time.monotonic() - started
        run_result = {
            "concurrency": concurrency,
            "elapsed_seconds": round(elapsed, 3),
            "return_code": return_code,
            "output": str(output_path),
            "log": str(log_path),
        }
        summary["runs"].append(run_result)
        print(
            f"BENCHMARK_DONE concurrency={concurrency} "
            f"elapsed={elapsed:.1f}s return_code={return_code}",
            flush=True,
        )
        if return_code != 0:
            break

    summary_path = output_dir / "benchmark_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"SUMMARY={summary_path}", flush=True)
    if any(run["return_code"] != 0 for run in summary["runs"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
