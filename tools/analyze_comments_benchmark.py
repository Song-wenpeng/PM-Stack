# -*- coding: utf-8 -*-
"""Validate row integrity and cross-run consistency for Step 1 benchmarks."""

import argparse
import json
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_all_sheets(path: Path, require_comment_column: bool = False) -> pd.DataFrame:
    with pd.ExcelFile(path) as workbook:
        frames = []
        for name in workbook.sheet_names:
            frame = pd.read_excel(workbook, sheet_name=name)
            if require_comment_column and "内容" not in frame.columns:
                continue
            frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def normalized(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("benchmark_dir", type=Path)
    args = parser.parse_args()
    benchmark_dir = args.benchmark_dir.resolve()
    summary_path = benchmark_dir / "benchmark_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    # Step 1 按设计会跳过不含评论列的说明/元数据 Sheet。
    input_frame = load_all_sheets(
        Path(summary["input"]),
        require_comment_column=True,
    )
    config = json.loads(
        (PROJECT_ROOT / "scripts" / "product_configs.json").read_text(encoding="utf-8")
    )[summary["product"]]
    field_columns = [field["excel_col"] for field in config["fields"]]

    frames = {}
    validations = []
    for run in summary["runs"]:
        concurrency = int(run["concurrency"])
        frame = load_all_sheets(Path(run["output"]))
        frames[concurrency] = frame
        status = normalized(frame["_处理状态"]) if "_处理状态" in frame else pd.Series(dtype=str)
        comments_match = (
            "内容" in frame
            and "内容" in input_frame
            and normalized(frame["内容"]).tolist() == normalized(input_frame["内容"]).tolist()
        )
        validations.append({
            "concurrency": concurrency,
            "row_count": len(frame),
            "input_row_count": len(input_frame),
            "row_count_matches": len(frame) == len(input_frame),
            "comment_order_matches": bool(comments_match),
            "failed_or_stopped_rows": int((status != "").sum()),
            "missing_field_columns": [name for name in field_columns if name not in frame],
        })

    baseline_concurrency = min(frames)
    baseline = frames[baseline_concurrency]
    agreements = []
    for concurrency, frame in sorted(frames.items()):
        if concurrency == baseline_concurrency:
            continue
        comparable_fields = [
            field for field in field_columns if field in baseline and field in frame
        ]
        field_agreement = {}
        equal_cells = 0
        total_cells = 0
        for field in comparable_fields:
            left = normalized(baseline[field])
            right = normalized(frame[field])
            count = min(len(left), len(right))
            matches = int((left.iloc[:count].reset_index(drop=True) == right.iloc[:count].reset_index(drop=True)).sum())
            field_agreement[field] = round(matches / max(1, count), 4)
            equal_cells += matches
            total_cells += count
        agreements.append({
            "baseline_concurrency": baseline_concurrency,
            "concurrency": concurrency,
            "overall_exact_cell_agreement": round(equal_cells / max(1, total_cells), 4),
            "field_exact_agreement": field_agreement,
        })

    summary["validation"] = {
        "runs": validations,
        "cross_run_exact_agreement": agreements,
        "note": "Exact agreement is conservative because the model is nondeterministic at temperature 0.2.",
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary["validation"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
