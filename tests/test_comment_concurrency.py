# -*- coding: utf-8 -*-
"""Regression tests for the concurrent comment-analysis test path."""

from tests import support

import importlib.util
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pandas as pd

from scripts import comments_step_1_fast as fast


TEST_CONFIG = {
    "fields": [
        {"key": "tag", "type": "string", "excel_col": "标签"},
    ],
}


class ConcurrentStepOneTests(unittest.TestCase):
    @staticmethod
    def _response(tag):
        return SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content=json.dumps({"tag": tag})),
            )],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            ),
        )

    def test_results_keep_input_order_and_resume_skips_successes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            checkpoint_path = str(Path(temp_dir) / "step1.checkpoint.json")
            signature = {"case": "ordered-resume"}
            checkpoint = fast.CheckpointStore(checkpoint_path, signature)
            frame = pd.DataFrame({"内容": ["slow", "fast", "middle"]})
            delays = {"slow": 0.04, "fast": 0.005, "middle": 0.02}

            def extractor(comment, config, limiter, metrics, stop_event):
                time.sleep(delays[comment])
                return {"tag": comment}, ""

            with mock.patch.object(fast, "CONCURRENCY", 3), mock.patch.object(
                fast, "CHECKPOINT_EVERY", 1,
            ):
                result, stats = fast.process_sheet_concurrent(
                    frame,
                    TEST_CONFIG,
                    sheet_name="reviews",
                    checkpoint=checkpoint,
                    extractor=extractor,
                    stop_checker=lambda: False,
                )

            self.assertEqual(result["标签"].tolist(), ["slow", "fast", "middle"])
            self.assertEqual(result["_处理状态"].tolist(), ["", "", ""])
            self.assertEqual(stats["succeeded"], 3)
            self.assertTrue(Path(checkpoint_path).exists())

            restored = fast.CheckpointStore(checkpoint_path, signature)
            self.assertTrue(restored.loaded)

            def should_not_run(*_args, **_kwargs):
                raise AssertionError("successful checkpoint rows must not call the API")

            resumed, resumed_stats = fast.process_sheet_concurrent(
                frame,
                TEST_CONFIG,
                sheet_name="reviews",
                checkpoint=restored,
                extractor=should_not_run,
                stop_checker=lambda: False,
            )
            self.assertEqual(resumed["标签"].tolist(), ["slow", "fast", "middle"])
            self.assertEqual(resumed_stats["resumed"], 3)

    def test_stop_preserves_results_from_requests_already_in_flight(self):
        frame = pd.DataFrame({"内容": ["a", "b", "c", "d", "e"]})
        completed = []
        started = time.monotonic()

        def extractor(comment, config, limiter, metrics, stop_event):
            time.sleep(0.02 if comment == "a" else 0.05)
            completed.append(comment)
            return {"tag": comment}, ""

        def stop_checker():
            return time.monotonic() - started >= 0.025

        with mock.patch.object(fast, "CONCURRENCY", 2):
            result, stats = fast.process_sheet_concurrent(
                frame,
                TEST_CONFIG,
                extractor=extractor,
                stop_checker=stop_checker,
            )

        self.assertTrue(stats["stopped"])
        for comment in completed:
            row = result.loc[frame["内容"] == comment].iloc[0]
            self.assertEqual(row["标签"], comment)
            self.assertEqual(row["_处理状态"], "")
        self.assertGreater(stats["stopped_rows"], 0)

    def test_429_retry_uses_real_request_metrics(self):
        class RateLimitError(Exception):
            status_code = 429
            response = SimpleNamespace(headers={"Retry-After": "0"})

        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"tag": "ok"}'))],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            ),
        )
        create = mock.Mock(side_effect=[RateLimitError("limited"), response])
        fake_client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        )
        metrics = fast.RequestMetrics()

        with mock.patch.object(fast, "get_client", return_value=fake_client), \
                mock.patch.object(fast, "MAX_RETRIES", 2), \
                mock.patch.object(fast, "RATE_LIMIT_WAIT", 0), \
                mock.patch.object(fast, "RETRY_JITTER", 0):
            result, status = fast.call_ai_extract(
                "review",
                TEST_CONFIG,
                limiter=fast.RollingWindowRateLimiter(0, 0),
                metrics=metrics,
            )

        snapshot = metrics.snapshot()
        self.assertEqual(result["tag"], "ok")
        self.assertEqual(status, "")
        self.assertEqual(snapshot["api_requests"], 2)
        self.assertEqual(snapshot["retries"], 1)
        self.assertEqual(snapshot["rate_limits"], 1)
        self.assertEqual(snapshot["total_tokens"], 15)

    def test_failure_rate_gate_is_strict_by_default(self):
        self.assertTrue(fast.failure_rate_exceeded(1, 100, 0))
        self.assertFalse(fast.failure_rate_exceeded(0, 100, 0))
        self.assertFalse(fast.failure_rate_exceeded(1, 100, 0.01))

    def test_main_blocks_step_two_then_retries_only_failed_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path = root / "input.xlsx"
            output_path = root / "step1.xlsx"
            config_path = root / "product_configs.json"
            stop_path = root / "stop.signal"
            pd.DataFrame({"内容": ["good", "bad"]}).to_excel(
                input_path,
                sheet_name="reviews",
                index=False,
            )
            config_path.write_text(
                json.dumps({"demo": TEST_CONFIG}),
                encoding="utf-8",
            )

            first_calls = []

            def first_create(**kwargs):
                prompt = kwargs["messages"][-1]["content"]
                first_calls.append(prompt)
                if "bad" in prompt:
                    return SimpleNamespace(
                        choices=[SimpleNamespace(
                            message=SimpleNamespace(content="not-json"),
                        )],
                        usage=None,
                    )
                return self._response("ok")

            first_client = SimpleNamespace(
                chat=SimpleNamespace(
                    completions=SimpleNamespace(create=first_create),
                ),
            )
            common = {
                "API_KEY": "test-key",
                "INPUT_FILE": str(input_path),
                "OUTPUT_FILE": str(output_path),
                "CONFIG_FILE": str(config_path),
                "CURRENT_PRODUCT": "demo",
                "TARGET_SHEETS": [],
                "STOP_FILE": str(stop_path),
                "CONCURRENCY": 2,
                "RPM_LIMIT": 0,
                "TPM_LIMIT": 0,
                "CHECKPOINT_EVERY": 1,
                "MAX_RETRIES": 1,
                "MAX_FAILURE_RATE": 0,
                "RESUME_ONLY": False,
            }
            with mock.patch.multiple(fast, **common), mock.patch.object(
                fast, "get_client", return_value=first_client,
            ):
                with self.assertRaisesRegex(SystemExit, "2"):
                    fast.main()

            checkpoint_path = Path(f"{output_path}.checkpoint.json")
            self.assertTrue(output_path.exists())
            self.assertTrue(checkpoint_path.exists())
            first_output = pd.read_excel(output_path, sheet_name="reviews")
            self.assertEqual(
                first_output["_处理状态"].fillna("").tolist(),
                ["", "AI提取失败"],
            )
            self.assertEqual(len(first_calls), 2)

            retry_calls = []

            def retry_create(**kwargs):
                prompt = kwargs["messages"][-1]["content"]
                retry_calls.append(prompt)
                return self._response("fixed")

            retry_client = SimpleNamespace(
                chat=SimpleNamespace(
                    completions=SimpleNamespace(create=retry_create),
                ),
            )
            with mock.patch.multiple(fast, **common), mock.patch.object(
                fast, "get_client", return_value=retry_client,
            ):
                fast.main()

            final_output = pd.read_excel(output_path, sheet_name="reviews")
            self.assertEqual(
                final_output["_处理状态"].fillna("").tolist(),
                ["", ""],
            )
            self.assertEqual(final_output["标签"].tolist(), ["ok", "fixed"])
            self.assertEqual(len(retry_calls), 1)
            self.assertIn("bad", retry_calls[0])
            self.assertFalse(checkpoint_path.exists())


class StepTwoFailureFilteringTests(unittest.TestCase):
    def test_failed_and_stopped_rows_are_excluded_from_summary_input(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path = root / "step1.xlsx"
            output_path = root / "step2.xlsx"
            config_path = root / "product_configs.json"
            pd.DataFrame({
                "内容": ["good", "failed", "stopped"],
                "标签": ["A", "B", "C"],
                "_处理状态": ["", "AI提取失败", "已停止"],
            }).to_excel(input_path, sheet_name="reviews", index=False)
            config_path.write_text(
                json.dumps({
                    "demo": {
                        "fields": [
                            {"key": "tag", "type": "string", "excel_col": "标签"},
                        ],
                        "stats_fields": ["标签"],
                    },
                }),
                encoding="utf-8",
            )

            module_path = Path(fast.__file__).with_name("comments_step_2.py")
            spec = importlib.util.spec_from_file_location(
                "comments_step_2_filter_test",
                module_path,
            )
            module = importlib.util.module_from_spec(spec)
            env = {
                "API_KEY": "test-key",
                "API_ENV_NAME": "API_KEY",
                "STEP1_OUTPUT_FILE": str(input_path),
                "STEP2_OUTPUT_FILE": str(output_path),
                "CURRENT_PRODUCT": "demo",
                "CONFIG_FILE": str(config_path),
                "STEP2_SKIP_FAILED_ROWS": "1",
            }
            with mock.patch.dict(os.environ, env, clear=False):
                spec.loader.exec_module(module)

            merged = module.merge_sheets(str(input_path), ["reviews"])
            self.assertEqual(merged["内容"].tolist(), ["good"])
            self.assertEqual(merged["标签"].tolist(), ["A"])
            self.assertNotIn("_处理状态", merged.columns)


if __name__ == "__main__":
    unittest.main(verbosity=2)
