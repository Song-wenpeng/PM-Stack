# -*- coding: utf-8 -*-
"""
comments_step_1_fast.py — comments_step_1.py 的并发测试版（方案A）

与原版保持相同的输入输出格式与 prompt 逻辑，仅把“逐条串行调用”
改为线程池并发调用，用于验证加速效果：

1. STEP1_CONCURRENCY 个线程并发请求（默认 8，受 RPM/TPM 全局限速保护）。
2. 429 限流错误单独退避（默认 30s 起步），普通错误沿用短退避。
3. 结果严格按原行序写回，末尾追加“_处理状态”列标记失败/停止条目
   （comments_step_2.py 只读取配置内字段，不受该列影响）。
4. 支持停止信号文件（与软件“停止”按钮共用 comment_stop.signal）。
5. 结束时打印吞吐统计，方便和原版对比。
"""

import os
import re
import json
import time
import random
import hashlib
import tempfile
import threading
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Dict, Any, Deque, List, Optional, Tuple

import pandas as pd
from openai import OpenAI

# ================= 环境变量配置 =================
API_ENV_NAME = os.getenv("API_ENV_NAME", "SILICONFLOW_API_KEY")
# 兼容软件设置面板注入的 API_KEY（get_env_dict 使用该变量名）
API_KEY = os.getenv(API_ENV_NAME) or os.getenv("API_KEY")

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

TEMPERATURE = float(os.getenv("STEP1_TEMPERATURE", "0.2"))
MAX_TOKENS = int(os.getenv("STEP1_MAX_TOKENS", "1200"))
MAX_RETRIES = int(os.getenv("STEP1_MAX_RETRIES", "3"))

# ---- 并发版新增参数 ----
CONCURRENCY = min(32, max(1, int(os.getenv("STEP1_CONCURRENCY", "8"))))
RPM_LIMIT = max(0, int(os.getenv("STEP1_RPM_LIMIT", "900")))
TPM_LIMIT = max(0, int(os.getenv("STEP1_TPM_LIMIT", "90000")))
ESTIMATED_TOKENS = max(1, int(os.getenv("STEP1_ESTIMATED_TOKENS", "1500")))
RATE_LIMIT_WAIT = max(0.0, float(os.getenv("STEP1_RATE_LIMIT_WAIT", "30")))
RETRY_JITTER = max(0.0, float(os.getenv("STEP1_RETRY_JITTER", "1.5")))
REQUEST_TIMEOUT = max(5.0, float(os.getenv("STEP1_REQUEST_TIMEOUT", "90")))
PROGRESS_EVERY = max(1, int(os.getenv("STEP1_PROGRESS_EVERY", "20")))
CHECKPOINT_EVERY = max(1, int(os.getenv("STEP1_CHECKPOINT_EVERY", "20")))
MAX_FAILURE_RATE = min(1.0, max(0.0, float(os.getenv("STEP1_MAX_FAILURE_RATE", "0"))))
RESUME_ONLY = os.getenv("STEP1_RESUME_ONLY", "0").strip().lower() in (
    "1", "true", "yes", "y",
)

STOP_FILE = os.path.join(tempfile.gettempdir(), "comment_stop.signal")

client = None


def get_client():
    """延迟创建客户端，避免导入模块时要求存在 API Key。"""
    global client
    if client is None:
        if not API_KEY:
            raise ValueError(
                f"未检测到环境变量 {API_ENV_NAME} 或 API_KEY，请先设置后再运行。")
        client = OpenAI(
            api_key=API_KEY,
            base_url=BASE_URL,
            timeout=REQUEST_TIMEOUT,
        )
    return client


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


# ================= 工具函数（与原版一致） =================
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


# ================= 并发控制与指标 =================
class RollingWindowRateLimiter:
    """同时约束每分钟请求数和估算 Token 数的滑动窗口限速器。"""

    def __init__(self, rpm: int, tpm: int, window_seconds: float = 60.0):
        self.rpm = max(0, int(rpm))
        self.tpm = max(0, int(tpm))
        self.window_seconds = max(0.01, float(window_seconds))
        self._records: Deque[List[float]] = deque()
        self._lock = threading.Lock()

    def _prune(self, now: float):
        cutoff = now - self.window_seconds
        while self._records and self._records[0][0] <= cutoff:
            self._records.popleft()

    def acquire(
        self,
        estimated_tokens: int,
        stop_event: Optional[threading.Event] = None,
    ) -> Optional[List[float]]:
        """获得一次请求额度；停止时返回 None。"""
        if self.rpm <= 0 and self.tpm <= 0:
            return []

        token_reservation = max(1, int(estimated_tokens))
        if self.tpm > 0:
            token_reservation = min(token_reservation, self.tpm)

        while True:
            if stop_event is not None and stop_event.is_set():
                return None

            now = time.monotonic()
            with self._lock:
                self._prune(now)
                request_ok = self.rpm <= 0 or len(self._records) < self.rpm
                used_tokens = sum(item[1] for item in self._records)
                token_ok = self.tpm <= 0 or used_tokens + token_reservation <= self.tpm
                if request_ok and token_ok:
                    reservation = [now, float(token_reservation)]
                    self._records.append(reservation)
                    return reservation

                if self._records:
                    wait_seconds = max(
                        0.01,
                        self._records[0][0] + self.window_seconds - now,
                    )
                else:
                    wait_seconds = 0.05

            # 以短片段等待，使“停止”按钮无需等完整窗口。
            pause = min(wait_seconds, 0.25)
            if stop_event is not None:
                if stop_event.wait(pause):
                    return None
            else:
                time.sleep(pause)

    def reconcile(self, reservation: Optional[List[float]], actual_tokens: Optional[int]):
        """服务端返回 usage 时，用真实 Token 数修正预留值。"""
        if not reservation or actual_tokens is None:
            return
        with self._lock:
            reservation[1] = float(max(0, int(actual_tokens)))


class RequestMetrics:
    """线程安全的真实 HTTP 尝试次数与 Token 指标。"""

    def __init__(self):
        self._lock = threading.Lock()
        self.api_requests = 0
        self.api_seconds = 0.0
        self.retries = 0
        self.rate_limits = 0
        self.backoff_seconds = 0.0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.usage_reports = 0

    def record_attempt(
        self,
        elapsed: float,
        usage: Optional[Dict[str, int]] = None,
        rate_limited: bool = False,
    ):
        with self._lock:
            self.api_requests += 1
            self.api_seconds += max(0.0, float(elapsed))
            if rate_limited:
                self.rate_limits += 1
            if usage:
                self.prompt_tokens += int(usage.get("prompt_tokens", 0) or 0)
                self.completion_tokens += int(usage.get("completion_tokens", 0) or 0)
                self.total_tokens += int(usage.get("total_tokens", 0) or 0)
                self.usage_reports += 1

    def record_retry(self, backoff_seconds: float):
        with self._lock:
            self.retries += 1
            self.backoff_seconds += max(0.0, float(backoff_seconds))

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "api_requests": self.api_requests,
                "api_seconds": self.api_seconds,
                "retries": self.retries,
                "rate_limits": self.rate_limits,
                "backoff_seconds": self.backoff_seconds,
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": self.total_tokens,
                "usage_reports": self.usage_reports,
            }


def extract_usage(response: Any) -> Optional[Dict[str, int]]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    result = {
        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
    }
    return result if any(result.values()) else None


def retry_after_seconds(error: Exception) -> Optional[float]:
    """读取服务端 Retry-After（秒数或 HTTP 日期）。"""
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None) or getattr(error, "headers", None)
    if not headers:
        return None
    value = headers.get("retry-after") or headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        try:
            retry_at = parsedate_to_datetime(str(value))
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def wait_interruptibly(seconds: float, stop_event: Optional[threading.Event]) -> bool:
    """等待并返回是否被停止信号中断。"""
    seconds = max(0.0, float(seconds))
    if stop_event is None:
        time.sleep(seconds)
        return False
    return stop_event.wait(seconds)


# ================= AI 调用（并发版） =================
def is_rate_limit_error(e: Exception) -> bool:
    """识别 429 限流错误。"""
    status = getattr(e, "status_code", None)
    if status == 429:
        return True
    name = type(e).__name__
    if "RateLimit" in name:
        return True
    return "429" in str(e) or "Rate limit" in str(e) or "rate_limit" in str(e)


def call_ai_extract(
    comment: str,
    config: Dict[str, Any],
    limiter: Optional[RollingWindowRateLimiter] = None,
    metrics: Optional[RequestMetrics] = None,
    stop_event: Optional[threading.Event] = None,
) -> Tuple[Dict[str, Any], str]:
    """调用 AI 提取评论信息。返回 (结果, 状态文本)。

    与原版不同：重试耗尽后不静默吞掉失败，而是返回失败标记，
    由调用方写入“_处理状态”列，便于识别和补跑。
    """
    if pd.isna(comment) or not str(comment).strip():
        return get_default_result(config), ""

    comment = str(comment).strip()
    prompt = build_prompt(config, comment)

    limiter = limiter or RollingWindowRateLimiter(0, 0)
    metrics = metrics or RequestMetrics()

    for attempt in range(1, MAX_RETRIES + 1):
        if stop_event is not None and stop_event.is_set():
            return get_default_result(config), "已停止"

        reservation = limiter.acquire(ESTIMATED_TOKENS, stop_event)
        if reservation is None:
            return get_default_result(config), "已停止"

        started = time.monotonic()
        attempt_recorded = False
        try:
            response = get_client().chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": config.get("system_prompt", "你是专业的用户评论分析专家。")},
                    {"role": "user", "content": prompt},
                ],
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS,
                timeout=REQUEST_TIMEOUT,
            )

            elapsed = time.monotonic() - started
            usage = extract_usage(response)
            limiter.reconcile(
                reservation,
                usage.get("total_tokens") if usage else None,
            )
            metrics.record_attempt(elapsed, usage=usage)
            attempt_recorded = True
            content = response.choices[0].message.content
            data = extract_json_object(content)
            return normalize_result(data, config), ""

        except Exception as e:
            elapsed = time.monotonic() - started
            rate_limited = is_rate_limit_error(e)
            if not attempt_recorded:
                metrics.record_attempt(elapsed, rate_limited=rate_limited)

            if attempt >= MAX_RETRIES:
                kind = "限流" if rate_limited else "失败"
                print(f"[{kind}] 第 {attempt}/{MAX_RETRIES} 次调用失败: {e}", flush=True)
                return get_default_result(config), "AI提取失败"

            if rate_limited:
                server_wait = retry_after_seconds(e)
                base_wait = server_wait if server_wait is not None else RATE_LIMIT_WAIT * attempt
                delay = base_wait + random.uniform(0.0, RETRY_JITTER)
                print(
                    f"[限流] 第 {attempt}/{MAX_RETRIES} 次触发 429，"
                    f"等待 {delay:.1f}s 后重试",
                    flush=True,
                )
            else:
                delay = 1.2 * attempt + random.uniform(0.0, min(RETRY_JITTER, 0.8))
                print(
                    f"[第 {attempt}/{MAX_RETRIES} 次失败] API 调用或解析错误: {e}; "
                    f"{delay:.1f}s 后重试",
                    flush=True,
                )

            metrics.record_retry(delay)
            if wait_interruptibly(delay, stop_event):
                return get_default_result(config), "已停止"


def serialize_for_excel(value: Any) -> str:
    """写入 Excel 前处理列表字段。"""
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    return value


# ================= 断点存储 =================
class CheckpointStore:
    """按行保存 Step 1 结果；输入或配置变化时自动判定为无效。"""

    VERSION = 1

    def __init__(self, path: str, signature: Dict[str, Any]):
        self.path = os.path.abspath(path)
        self.signature = signature
        self.loaded = False
        self.load_warning = ""
        self.data = {
            "version": self.VERSION,
            "signature": signature,
            "sheets": {},
        }
        self._load()

    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as checkpoint_file:
                saved = json.load(checkpoint_file)
            if (
                saved.get("version") == self.VERSION
                and saved.get("signature") == self.signature
                and isinstance(saved.get("sheets"), dict)
            ):
                self.data = saved
                self.loaded = True
            else:
                self.load_warning = "已有断点与本次输入、配置或模型不一致，已忽略"
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self.load_warning = f"断点文件无法读取，已忽略: {exc}"

    def successful_rows(self, sheet_name: str) -> Dict[int, Dict[str, Any]]:
        sheet = self.data.get("sheets", {}).get(sheet_name, {})
        records = sheet.get("rows", {}) if isinstance(sheet, dict) else {}
        result = {}
        for raw_index, record in records.items():
            if not isinstance(record, dict):
                continue
            if record.get("status", "") not in ("", "成功"):
                continue
            details = record.get("result")
            if not isinstance(details, dict):
                continue
            try:
                result[int(raw_index)] = details
            except (TypeError, ValueError):
                continue
        return result

    def update(self, sheet_name: str, index: int, result: Dict[str, Any], status: str):
        sheets = self.data.setdefault("sheets", {})
        sheet = sheets.setdefault(sheet_name, {"rows": {}})
        rows = sheet.setdefault("rows", {})
        rows[str(index)] = {"result": result, "status": status}

    def save(self):
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                suffix=".tmp",
                prefix=".pmstack-comments-",
                dir=directory or None,
                delete=False,
            ) as temp_file:
                temp_path = temp_file.name
                json.dump(self.data, temp_file, ensure_ascii=False)
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_path, self.path)
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    def remove(self):
        try:
            if os.path.exists(self.path):
                os.remove(self.path)
        except OSError as exc:
            print(f"[提示] 已完成，但无法删除断点文件: {exc}", flush=True)


def build_run_signature(config: Dict[str, Any]) -> Dict[str, Any]:
    input_stat = os.stat(INPUT_FILE)
    config_payload = json.dumps(
        config,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "input_file": os.path.abspath(INPUT_FILE),
        "input_size": input_stat.st_size,
        "input_mtime_ns": input_stat.st_mtime_ns,
        "product": CURRENT_PRODUCT,
        "model": MODEL_NAME,
        "comment_column": COMMENT_COLUMN,
        "target_sheets": list(TARGET_SHEETS),
        "config_sha256": hashlib.sha256(config_payload).hexdigest(),
    }


def failure_rate_exceeded(failed: int, completed: int, limit: float) -> bool:
    if failed <= 0:
        return False
    return failed / max(1, completed) > max(0.0, float(limit))


# ================= 并发处理 =================
def check_stop() -> bool:
    """检查停止信号文件。"""
    return os.path.exists(STOP_FILE)


def fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m}m{s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m"


def process_sheet_concurrent(
    df_sheet: pd.DataFrame,
    config: Dict[str, Any],
    sheet_name: str = "",
    checkpoint: Optional[CheckpointStore] = None,
    limiter: Optional[RollingWindowRateLimiter] = None,
    metrics: Optional[RequestMetrics] = None,
    extractor=call_ai_extract,
    stop_checker=check_stop,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """以有界任务窗口并发处理单个 sheet，保证停止后的在途结果仍会保存。"""
    n = len(df_sheet)
    comments: List[Any] = [row.get(COMMENT_COLUMN, "") for _, row in df_sheet.iterrows()]
    results: List[Optional[Dict[str, Any]]] = [None] * n
    statuses: List[str] = [""] * n
    limiter = limiter or RollingWindowRateLimiter(0, 0)
    metrics = metrics or RequestMetrics()

    stats = {
        "total": n,
        "completed": 0,
        "succeeded": 0,
        "failed": 0,
        "resumed": 0,
        "stopped_rows": 0,
        "stopped": False,
        "start": time.time(),
    }

    if checkpoint is not None:
        for index, details in checkpoint.successful_rows(sheet_name).items():
            if 0 <= index < n:
                results[index] = details
                statuses[index] = ""
                stats["completed"] += 1
                stats["succeeded"] += 1
                stats["resumed"] += 1

    pending = deque(index for index, result in enumerate(results) if result is None)
    stop_event = threading.Event()
    unsaved_updates = 0

    def save_checkpoint(force: bool = False):
        nonlocal unsaved_updates
        if checkpoint is None or (not force and unsaved_updates < CHECKPOINT_EVERY):
            return
        checkpoint.save()
        unsaved_updates = 0

    def store_result(index: int, details: Dict[str, Any], status: str):
        nonlocal unsaved_updates
        results[index] = details
        statuses[index] = status
        if checkpoint is not None:
            checkpoint.update(sheet_name, index, details, status)
            unsaved_updates += 1
            save_checkpoint()

    def worker(index: int) -> Tuple[int, Dict[str, Any], str]:
        if stop_event.is_set():
            return index, get_default_result(config), "已停止"
        comment = comments[index]
        if pd.isna(comment) or not str(comment).strip():
            return index, get_default_result(config), ""
        details, status = extractor(
            comment,
            config,
            limiter,
            metrics,
            stop_event,
        )
        return index, details, status

    def print_progress(force: bool = False):
        done = stats["completed"]
        if not force and done % PROGRESS_EVERY != 0 and done != n:
            return
        elapsed = time.time() - stats["start"]
        eta = elapsed / done * (n - done) if done and done < n and not stats["stopped"] else 0.0
        print(
            f"进度: {done}/{n} ({done * 100 // max(1, n)}%) | "
            f"断点复用 {stats['resumed']} | 失败 {stats['failed']} | "
            f"已用 {fmt_duration(elapsed)} | 预计剩余 {fmt_duration(eta)}",
            flush=True,
        )

    if n == 0:
        return df_sheet.copy(), stats

    executor = ThreadPoolExecutor(max_workers=CONCURRENCY)
    in_flight = {}

    def submit_until_full():
        while pending and len(in_flight) < CONCURRENCY and not stop_event.is_set():
            index = pending.popleft()
            future = executor.submit(worker, index)
            in_flight[future] = index

    try:
        if stop_checker():
            stop_event.set()
            stats["stopped"] = True
        submit_until_full()

        while in_flight:
            if stop_checker() and not stop_event.is_set():
                stop_event.set()
                stats["stopped"] = True

            finished, _ = wait(
                tuple(in_flight),
                timeout=0.2,
                return_when=FIRST_COMPLETED,
            )
            if not finished:
                continue

            for future in finished:
                index = in_flight.pop(future)
                try:
                    _, details, status = future.result()
                except Exception as exc:
                    print(f"[失败] 第 {index + 1} 行处理异常: {exc}", flush=True)
                    details, status = get_default_result(config), "AI提取失败"

                store_result(index, details, status)
                stats["completed"] += 1
                if status == "AI提取失败":
                    stats["failed"] += 1
                elif status == "已停止":
                    stats["stopped_rows"] += 1
                    stats["stopped"] = True
                else:
                    stats["succeeded"] += 1
                print_progress(force=stats["stopped"])

            submit_until_full()
    finally:
        # 已发出的请求最多只有 CONCURRENCY 个；等待其结束并保留已获得的结果。
        executor.shutdown(wait=True, cancel_futures=True)

    if stop_event.is_set():
        stats["stopped"] = True

    # 尚未提交的条目在输出中明确标记，断点续跑时会自动重试。
    for index in list(pending):
        details = get_default_result(config)
        store_result(index, details, "已停止")
        stats["completed"] += 1
        stats["stopped_rows"] += 1

    # 极端情况下的兜底，确保输出行数与输入严格一致。
    for index, details in enumerate(results):
        if details is None:
            default = get_default_result(config)
            store_result(index, default, "已停止" if stats["stopped"] else "AI提取失败")
            stats["completed"] += 1
            if stats["stopped"]:
                stats["stopped_rows"] += 1
            else:
                stats["failed"] += 1

    save_checkpoint(force=True)
    print_progress(force=True)

    rows = []
    for (_, row), details, status in zip(df_sheet.iterrows(), results, statuses):
        combined = row.to_dict()
        for field in config["fields"]:
            combined[field["excel_col"]] = serialize_for_excel(details[field["key"]])
        combined["_处理状态"] = status
        rows.append(combined)

    return pd.DataFrame(rows), stats


# ================= 主程序 =================
def main():
    if not API_KEY:
        raise ValueError(
            f"未检测到环境变量 {API_ENV_NAME} 或 API_KEY，请先设置后再运行。")
    if not INPUT_FILE:
        raise ValueError("未检测到环境变量 RAW_INPUT_FILE")
    if not OUTPUT_FILE:
        raise ValueError("未检测到环境变量 STEP1_OUTPUT_FILE")
    if not CURRENT_PRODUCT:
        raise ValueError("未检测到环境变量 CURRENT_PRODUCT")

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

    print(
        f"并发数: {CONCURRENCY} | RPM上限: {RPM_LIMIT or '关闭'} | "
        f"TPM上限: {TPM_LIMIT or '关闭'} | 模型: {MODEL_NAME}",
        flush=True,
    )

    with pd.ExcelFile(INPUT_FILE) as xls:
        all_sheet_names = list(xls.sheet_names)
    print(f"发现工作表: {all_sheet_names}", flush=True)

    if TARGET_SHEETS:
        sheet_names = [s for s in TARGET_SHEETS if s in all_sheet_names]
    else:
        sheet_names = all_sheet_names

    if not sheet_names:
        raise ValueError(f"没有可处理的工作表。TARGET_SHEETS={TARGET_SHEETS}，实际={all_sheet_names}")

    print(f"本次实际处理工作表: {sheet_names}", flush=True)

    checkpoint_path = os.getenv("STEP1_CHECKPOINT_FILE") or f"{OUTPUT_FILE}.checkpoint.json"
    checkpoint = CheckpointStore(checkpoint_path, build_run_signature(config))
    if checkpoint.load_warning:
        print(f"[提示] {checkpoint.load_warning}", flush=True)
    if RESUME_ONLY and not checkpoint.loaded:
        raise ValueError("没有找到与本次输入匹配的有效断点，无法仅补跑失败条目。")
    if checkpoint.loaded:
        print(f"发现有效断点，将跳过已成功条目: {checkpoint.path}", flush=True)

    limiter = RollingWindowRateLimiter(RPM_LIMIT, TPM_LIMIT)
    request_metrics = RequestMetrics()
    run_start = time.time()
    total_stats = {
        "total": 0,
        "completed": 0,
        "succeeded": 0,
        "failed": 0,
        "resumed": 0,
        "stopped_rows": 0,
    }
    stopped = False
    writer = None
    temp_output = None
    published = False
    try:
        suffix = os.path.splitext(OUTPUT_FILE)[1] or ".xlsx"
        with tempfile.NamedTemporaryFile(
            suffix=suffix,
            prefix=".pmstack-comments-output-",
            dir=output_dir or None,
            delete=False,
        ) as temp_file:
            temp_output = temp_file.name
        os.remove(temp_output)

        for sheet_name in sheet_names:
            if check_stop():
                stopped = True
                break

            print(f"\n开始处理工作表：{sheet_name}", flush=True)
            df_sheet = pd.read_excel(INPUT_FILE, sheet_name=sheet_name)

            if COMMENT_COLUMN not in df_sheet.columns:
                print(f"跳过工作表 '{sheet_name}'，缺少列 '{COMMENT_COLUMN}'", flush=True)
                continue

            df_result, stats = process_sheet_concurrent(
                df_sheet,
                config,
                sheet_name=sheet_name,
                checkpoint=checkpoint,
                limiter=limiter,
                metrics=request_metrics,
            )
            if writer is None:
                writer = pd.ExcelWriter(temp_output, engine="openpyxl")
            df_result.to_excel(writer, sheet_name=sheet_name, index=False)

            for k in (
                "total", "completed", "succeeded", "failed", "resumed", "stopped_rows",
            ):
                total_stats[k] += stats[k]
            stopped = stopped or stats["stopped"]

            sheet_time = time.time() - stats["start"]
            print(
                f"工作表 '{sheet_name}' 处理完成，共 {stats['total']} 条 | "
                f"失败 {stats['failed']} 条 | 耗时 {fmt_duration(sheet_time)}",
                flush=True,
            )
            if stats["stopped"]:
                break
    except Exception:
        if writer is not None:
            try:
                writer.close()
            except Exception:
                pass
            writer = None
        if temp_output and os.path.exists(temp_output):
            try:
                os.remove(temp_output)
            except OSError:
                pass
        raise

    if writer is not None:
        writer.close()
        writer = None
        os.replace(temp_output, OUTPUT_FILE)
        published = True
    elif not stopped:
        if temp_output and os.path.exists(temp_output):
            os.remove(temp_output)
        raise ValueError(f"所选工作表均缺少评论列 '{COMMENT_COLUMN}'，未生成输出文件。")

    if temp_output and os.path.exists(temp_output) and not published:
        try:
            os.remove(temp_output)
        except OSError:
            pass

    elapsed = time.time() - run_start

    # ---- 吞吐统计（方案A效果验证） ----
    if total_stats["completed"] > 0:
        print("\n" + "=" * 50, flush=True)
        metric = request_metrics.snapshot()
        if metric["api_requests"] > 0:
            avg_latency = metric["api_seconds"] / metric["api_requests"]
            serial_estimate = metric["api_seconds"] + metric["backoff_seconds"]
            print(f"并发数: {CONCURRENCY}", flush=True)
            print(
                f"真实 API 请求: {metric['api_requests']} 次 | 重试 {metric['retries']} 次 | "
                f"429 {metric['rate_limits']} 次 | 平均 HTTP 耗时 {avg_latency:.1f}s",
                flush=True,
            )
            if metric["usage_reports"] > 0:
                print(
                    f"Token: 输入 {metric['prompt_tokens']:,} | 输出 {metric['completion_tokens']:,} | "
                    f"合计 {metric['total_tokens']:,}",
                    flush=True,
                )
            print(f"实际总耗时: {fmt_duration(elapsed)} | 串行估算: {fmt_duration(serial_estimate)}", flush=True)
            if elapsed > 0:
                print(f"加速比: 约 {serial_estimate / elapsed:.1f} 倍", flush=True)
                print(
                    f"有效吞吐: {total_stats['succeeded'] / elapsed * 60:.1f} 条/分钟",
                    flush=True,
                )
        if total_stats["resumed"] > 0:
            print(f"断点复用: {total_stats['resumed']} 条（未重复调用 API）", flush=True)
        if total_stats["failed"] > 0:
            print(
                f"[警告] 失败 {total_stats['failed']} 条，已标记“_处理状态”，"
                f"断点保留在: {checkpoint.path}",
                flush=True,
            )
        print("=" * 50, flush=True)

    if stopped:
        if published:
            print(f"\n[停止] 用户中止，已完成条目已保存到：{OUTPUT_FILE}", flush=True)
            print(f"下次可从断点继续：{checkpoint.path}", flush=True)
        else:
            print("\n[停止] 用户中止，尚未处理任何条目，未生成输出文件。", flush=True)
        raise SystemExit(1)

    evaluated = total_stats["succeeded"] + total_stats["failed"]
    if failure_rate_exceeded(total_stats["failed"], evaluated, MAX_FAILURE_RATE):
        failure_rate = total_stats["failed"] / max(1, evaluated)
        print(
            f"\n[需补跑] Step 1 失败率 {failure_rate:.2%} 超过允许值 "
            f"{MAX_FAILURE_RATE:.2%}；为避免不完整数据进入 Step 2，本次退出码为 2。",
            flush=True,
        )
        raise SystemExit(2)

    if total_stats["failed"] == 0:
        checkpoint.remove()

    print(f"\n全部处理完成，结果已保存到：{OUTPUT_FILE}", flush=True)


if __name__ == "__main__":
    main()
