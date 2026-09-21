# -*- coding: utf-8 -*-
"""
exstract_from_description_fast.py — 字段提取并发版

与原版 exstract_from_description.py 保持相同的输入输出格式与 prompt 逻辑，
将"逐行串行调用"改为线程池并发调用，加速处理：

1. EXTRACT_CONCURRENCY 个线程并发处理行（默认 4，受 RPM/TPM 限速保护）。
2. 文本与视觉模型分别独立限速。
3. 429 限流错误单独退避，普通错误短退避。
4. 断点文件保存每行结果，支持中断后续跑。
5. 输出 Excel 追加"_处理状态"列标记失败/停止条目。
6. 支持停止信号文件（与软件"停止"按钮共用）。
7. 图片批内并行下载。
"""

import os
import re
import io
import json
import queue
import time
import random
import base64
import hashlib
import tempfile
import threading
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests
from openai import OpenAI
from PIL import Image

# ================= 1. 环境变量配置 =================

API_KEY = os.getenv("API_KEY") or os.getenv("SILICONFLOW_API_KEY")
BASE_URL = os.getenv("BASE_URL", "https://api.siliconflow.cn/v1")

if not API_KEY:
    raise ValueError("未读取到 API Key，请检查环境变量 API_KEY 是否已正确配置。")

MODEL_TEXT = os.getenv("MODEL_TEXT", os.getenv("MODEL_NAME", "deepseek-ai/DeepSeek-V3"))

# 视觉模型：优先使用独立配置，回退到通用配置
VISION_API_KEY = os.getenv("VISION_API_KEY") or API_KEY
VISION_BASE_URL = os.getenv("VISION_BASE_URL") or BASE_URL
MODEL_VISION = os.getenv("MODEL_VISION", "Qwen/Qwen3-VL-30B-A3B-Instruct")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

INPUT_FILE = os.getenv("INPUT_FILE", "")
OUTPUT_FILE = os.getenv("OUTPUT_FILE", "")

CONFIG_FILE = os.getenv("CONFIG_FILE", os.path.join(SCRIPT_DIR, "product_field_config.json"))
CURRENT_PRODUCT = os.getenv("CURRENT_PRODUCT", "")

# ---- 并发参数 ----
CONCURRENCY = min(16, max(1, int(os.getenv("EXTRACT_CONCURRENCY", "4"))))
RPM_LIMIT = max(0, int(os.getenv("EXTRACT_RPM_LIMIT", "60")))
TPM_LIMIT = max(0, int(os.getenv("EXTRACT_TPM_LIMIT", "0")))
VISION_RPM_LIMIT = max(0, int(os.getenv("EXTRACT_VISION_RPM_LIMIT", "20")))
ESTIMATED_TOKENS = max(1, int(os.getenv("EXTRACT_ESTIMATED_TOKENS", "2000")))
RATE_LIMIT_WAIT = max(0.0, float(os.getenv("EXTRACT_RATE_LIMIT_WAIT", "30")))
RETRY_JITTER = max(0.0, float(os.getenv("EXTRACT_RETRY_JITTER", "1.5")))
REQUEST_TIMEOUT = max(5.0, float(os.getenv("EXTRACT_REQUEST_TIMEOUT", "120")))
PROGRESS_EVERY = max(1, int(os.getenv("EXTRACT_PROGRESS_EVERY", "5")))
CHECKPOINT_EVERY = max(1, int(os.getenv("EXTRACT_CHECKPOINT_EVERY", "5")))
MAX_TEXT_RETRIES = int(os.getenv("EXTRACT_MAX_RETRIES", "3"))
MAX_VISION_RETRIES = int(os.getenv("EXTRACT_VISION_MAX_RETRIES", "2"))

# 视觉相关
ENABLE_VISION_DEFAULT = os.getenv("ENABLE_VISION", "1").strip().lower() not in ("0", "false", "no", "n")
VISION_BATCH_SIZE = 3
MAX_VISION_IMAGES_PER_ROW = 9
MAX_EMPTY_VISION_BATCHES = 3
MIN_VISION_CONFIDENCE = 0.75
# 视觉图片尺寸：上限封顶 token 消耗，下限过滤无法识别的缩略图
VISION_MAX_SIZE = min(2000, max(256, int(os.getenv("EXTRACT_VISION_MAX_SIZE", "1568"))))
VISION_MIN_SIZE = max(0, int(os.getenv("EXTRACT_VISION_MIN_SIZE", "300")))

# 每处理多少行保存一次 Excel
SAVE_EVERY = max(1, int(os.getenv("EXTRACT_SAVE_EVERY", "10")))

STOP_FILE = os.getenv("STOP_FILE", "")

# ---- 商品资料补抓（缺五点描述/主副图时按详情页链接实时抓取）----
ENABLE_FETCH = os.getenv("ENABLE_FETCH", "0").strip().lower() in ("1", "true", "yes", "y")
FETCH_LINK_CANDIDATES = ["商品详情页链接", "详情页链接", "商品链接", "链接"]
FETCH_DELAY = max(0.0, float(os.getenv("FETCH_DELAY", "1")))
FETCH_WORKERS = max(1, min(8, int(os.getenv(
    "FETCH_WORKERS", str(min(CONCURRENCY, 4))))))
# 预抓缓冲深度：抓取线程提前抓好后面若干行放进缓冲，提取 worker 到了直接取、不再等抓取，
# 从而把"抓取"和"提取"解耦成两级流水线（总耗时≈行数×max(抓取/抓取线程, 提取/提取并发)）。
FETCH_LOOKAHEAD = max(FETCH_WORKERS, min(30, int(os.getenv(
    "FETCH_LOOKAHEAD", str(FETCH_WORKERS * 3)))))
# 固定文本列
TEXT_COLS = ["商品标题", "详细参数", "SKU", "五点描述"]

# 固定图片列
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

# ---- 延迟创建客户端 ----
_text_client = None
_vision_client = None
_client_lock = threading.Lock()


def get_text_client():
    global _text_client
    if _text_client is None:
        with _client_lock:
            if _text_client is None:
                _text_client = OpenAI(
                    api_key=API_KEY, base_url=BASE_URL, timeout=REQUEST_TIMEOUT)
    return _text_client


def get_vision_client():
    global _vision_client
    if _vision_client is None:
        with _client_lock:
            if _vision_client is None:
                _vision_client = OpenAI(
                    api_key=VISION_API_KEY, base_url=VISION_BASE_URL,
                    timeout=REQUEST_TIMEOUT)
    return _vision_client


# ================= 1.5 商品资料补抓（独立抓取线程池，线程内自建自关无头 Edge） =================

class FetchPool:
    """抓取线程池：Playwright 对象只能由创建它的线程关闭，因此每个抓取线程
    在自己的线程内创建并关闭 Edge 会话；工作线程提交 ASIN 请求并等待结果。"""

    def __init__(self, workers, checkpoint, checkpoint_path, lock, stop_check=None):
        self._queue = queue.Queue()
        self._checkpoint = checkpoint
        self._checkpoint_path = checkpoint_path
        self._lock = lock
        self._stop_check = stop_check
        self._inflight: Dict[str, Any] = {}
        self._threads = [
            threading.Thread(target=self._loop, daemon=True, name=f"fetch-{i}")
            for i in range(max(1, workers))
        ]
        for thread in self._threads:
            thread.start()

    def _save_checkpoint(self):
        try:
            with open(self._checkpoint_path, "w", encoding="utf-8") as fh:
                json.dump(self._checkpoint, fh, ensure_ascii=False)
        except Exception as exc:
            print(f"[警告] 抓取断点保存失败：{exc}", flush=True)

    def _loop(self):
        session = None
        try:
            while True:
                item = self._queue.get()
                if item is None:
                    break
                asin, future = item
                # 收到停止信号后，把缓冲里排队但还没开始的抓取直接标记跳过，快速排空队列，
                # 避免停止后还白抓一大批（预抓的行本来就是"提前量"，丢了不影响已完成结果）。
                if self._stop_check is not None and self._stop_check():
                    future.set_result({"ok": False, "stopped": True})
                    continue
                if session is None:
                    from core.reviews.product_fetcher import ProductFetcherSession
                    session = ProductFetcherSession(
                        headless=True, log_callback=lambda m: print(m, flush=True))
                    session.start()
                result = None
                for attempt in (1, 2):
                    try:
                        result = {"ok": True, **session.fetch(asin)}
                        break
                    except Exception as exc:
                        print(f"[抓取] {asin} 第 {attempt} 次尝试失败：{exc}", flush=True)
                        if attempt == 1:
                            time.sleep(max(FETCH_DELAY, 3))
                if result is None:
                    result = {"ok": False}
                with self._lock:
                    self._checkpoint[asin] = result
                    self._save_checkpoint()
                future.set_result(result)
                if FETCH_DELAY:
                    time.sleep(FETCH_DELAY)
        finally:
            if session is not None:
                session.close()

    def request(self, asin):
        """提交抓取请求，返回 Future；同一 ASIN 的在途请求复用同一个 Future。"""
        with self._lock:
            future = self._inflight.get(asin)
            if future is None:
                future = Future()
                self._inflight[asin] = future
                self._queue.put((asin, future))
            return future

    def shutdown(self):
        for _ in self._threads:
            self._queue.put(None)
        for thread in self._threads:
            thread.join(timeout=60)


def apply_fetch_to_row(row, entry):
    """把抓取结果写入行字典（五点描述 + image_1..9），只改字典不碰 DataFrame。"""
    bullets = entry.get("bullets") or []
    if bullets and is_empty(row.get("五点描述")):
        row["五点描述"] = "About this item\n" + "\n".join(bullets)
    images = entry.get("images") or []
    for j, col in enumerate(IMAGE_COLS, 1):
        if is_empty(row.get(col)) and j <= len(images):
            row[col] = images[j - 1]


# ================= 2. 读取字段配置 =================

def load_product_config(config_file, product_name=None):
    if not os.path.exists(config_file):
        raise FileNotFoundError(f"字段配置文件不存在：{config_file}")
    with open(config_file, "r", encoding="utf-8") as f:
        config = json.load(f)
    if not product_name:
        product_name = config.get("current_product")
    if not product_name:
        raise ValueError("配置文件中未设置 current_product，也未指定 CURRENT_PRODUCT。")
    products = config.get("products", {})
    if product_name not in products:
        raise ValueError(f"配置文件中不存在产品配置：{product_name}")
    product_config = products[product_name]
    missing_keys = [k for k in ("target_fields", "field_config") if k not in product_config]
    if missing_keys:
        raise ValueError(f"产品配置缺少必要字段：{missing_keys}")
    return product_name, product_config


# ================= 3. 工具函数 =================

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
        try:
            data = json.loads(match.group(0))
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
                ".jpg" in lower_url or ".jpeg" in lower_url
                or ".png" in lower_url or ".webp" in lower_url
                or "media-amazon" in lower_url
                or "ssl-images-amazon" in lower_url
                or "/images/" in lower_url
            )
            if is_likely_image and url not in urls:
                urls.append(url)
    return urls


def normalize_amazon_image_url(image_url: str) -> str:
    """剥掉亚马逊图片 URL 的尺寸后缀，取原图。

    例如 .../I/71abc.jpg._AC_SL1500_.jpg -> .../I/71abc.jpg
    以及 .../I/71abc._SX342_.jpg -> .../I/71abc.jpg
    """
    # 匹配 .jpg/.png 后面的 ._XXX_ 尺寸段，直到最后一个扩展名
    normalized = re.sub(
        r"(\.(?:jpg|jpeg|png))(\._[^/]+_)+\.jpg$",
        r"\1",
        image_url,
        flags=re.IGNORECASE,
    )
    return normalized


def get_image_base64_from_url(image_url):
    """下载并归一化图片。

    返回 dict: {"status": "ok"|"small"|"error", "data": base64_url, "info": 尺寸信息}
    - small: 分辨率过低，跳过以免浪费 API 调用
    - error: 下载/解码失败
    """
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/114.0.0.0 Safari/537.36"
            )
        }
        target_url = normalize_amazon_image_url(image_url)
        response = requests.get(target_url, headers=headers, timeout=15)
        response.raise_for_status()
        img = Image.open(io.BytesIO(response.content))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        original_size = img.size
        # 小图保护：分辨率过低无法识别，跳过以免浪费 API 调用
        if VISION_MIN_SIZE and max(original_size) < VISION_MIN_SIZE:
            return {"status": "small", "data": None, "info": {
                "url": image_url,
                "original_size": f"{original_size[0]}x{original_size[1]}",
            }}
        if max(img.size) > VISION_MAX_SIZE:
            ratio = VISION_MAX_SIZE / max(img.size)
            new_size = tuple(int(dim * ratio) for dim in img.size)
            img = img.resize(new_size, Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        img.save(buffer, format="WEBP", quality=85)
        base64_str = base64.b64encode(buffer.getvalue()).decode("utf-8")
        size_info = {
            "url": image_url,
            "normalized_url": target_url,
            "original_size": f"{original_size[0]}x{original_size[1]}",
            "sent_size": f"{img.size[0]}x{img.size[1]}",
        }
        return {"status": "ok", "data": f"data:image/webp;base64,{base64_str}",
                "info": size_info}
    except Exception:
        return {"status": "error", "data": None, "info": {"url": image_url}}


# ================= 4. 限速器与指标 =================

class RollingWindowRateLimiter:
    """滑动窗口限速器，约束 RPM 和可选 TPM。"""

    def __init__(self, rpm: int, tpm: int = 0, window_seconds: float = 60.0):
        self.rpm = max(0, int(rpm))
        self.tpm = max(0, int(tpm))
        self.window_seconds = max(0.01, float(window_seconds))
        self._records: deque = deque()
        self._lock = threading.Lock()

    def _prune(self, now: float):
        cutoff = now - self.window_seconds
        while self._records and self._records[0][0] <= cutoff:
            self._records.popleft()

    def acquire(self, estimated_tokens: int = 1,
                stop_event: Optional[threading.Event] = None) -> Optional[list]:
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
                    wait_seconds = max(0.01, self._records[0][0] + self.window_seconds - now)
                else:
                    wait_seconds = 0.05
            pause = min(wait_seconds, 0.25)
            if stop_event is not None:
                if stop_event.wait(pause):
                    return None
            else:
                time.sleep(pause)

    def reconcile(self, reservation, actual_tokens):
        if not reservation or actual_tokens is None:
            return
        with self._lock:
            reservation[1] = float(max(0, int(actual_tokens)))


class RequestMetrics:
    """线程安全的请求指标。"""

    def __init__(self):
        self._lock = threading.Lock()
        self.api_requests = 0
        self.api_seconds = 0.0
        self.retries = 0
        self.rate_limits = 0

    def record_attempt(self, elapsed: float, rate_limited: bool = False):
        with self._lock:
            self.api_requests += 1
            self.api_seconds += max(0.0, elapsed)
            if rate_limited:
                self.rate_limits += 1

    def record_retry(self):
        with self._lock:
            self.retries += 1

    def snapshot(self):
        with self._lock:
            return {
                "api_requests": self.api_requests,
                "api_seconds": self.api_seconds,
                "retries": self.retries,
                "rate_limits": self.rate_limits,
            }


# ================= 5. 断点存储 =================

class CheckpointStore:
    """按行保存提取结果；输入或配置变化时自动判定为无效。"""

    VERSION = 1

    def __init__(self, path: str, signature: Dict[str, Any]):
        self.path = os.path.abspath(path)
        self.signature = signature
        self.loaded = False
        self.load_warning = ""
        self.data = {"version": self.VERSION, "signature": signature, "rows": {}}
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if (saved.get("version") == self.VERSION
                    and saved.get("signature") == self.signature
                    and isinstance(saved.get("rows"), dict)):
                self.data = saved
                self.loaded = True
            else:
                self.load_warning = "已有断点与本次输入或配置不一致，已忽略"
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self.load_warning = f"断点文件无法读取，已忽略: {exc}"

    def successful_rows(self) -> Dict[int, Dict[str, Any]]:
        result = {}
        for raw_index, record in self.data.get("rows", {}).items():
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

    def update(self, index: int, result: Dict[str, Any], status: str):
        with self._lock:
            self.data.setdefault("rows", {})[str(index)] = {
                "result": result, "status": status}

    def save(self):
        with self._lock:
            directory = os.path.dirname(self.path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            temp_path = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", suffix=".tmp",
                    prefix=".pmstack-extract-", dir=directory or None,
                    delete=False,
                ) as tmp:
                    temp_path = tmp.name
                    json.dump(self.data, tmp, ensure_ascii=False)
                    tmp.flush()
                    os.fsync(tmp.fileno())
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
        except OSError:
            pass


# ================= 6. AI 调用 =================

def is_rate_limit_error(e: Exception) -> bool:
    status = getattr(e, "status_code", None)
    if status == 429:
        return True
    name = type(e).__name__
    if "RateLimit" in name:
        return True
    return "429" in str(e) or "Rate limit" in str(e) or "rate_limit" in str(e)


def retry_after_seconds(error: Exception) -> Optional[float]:
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
    seconds = max(0.0, float(seconds))
    if stop_event is None:
        time.sleep(seconds)
        return False
    return stop_event.wait(seconds)


def extract_usage(response) -> Optional[int]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    total = int(getattr(usage, "total_tokens", 0) or 0)
    return total if total > 0 else None


def extract_text_features_concurrent(
    row: Dict[str, Any],
    missing_fields: List[str],
    product_name: str,
    field_config: Dict[str, str],
    limiter: RollingWindowRateLimiter,
    metrics: RequestMetrics,
    stop_event: threading.Event,
) -> Dict[str, Any]:
    """并发版文本提取，带限速和重试。"""
    text_content = build_text_from_row(row)
    if is_empty(text_content) or not missing_fields:
        return {}

    field_details = "\n".join([
        f"- {field}: {field_config.get(field, '无具体说明，请根据商品信息提取。')}"
        for field in missing_fields
    ])
    example_json = json.dumps(
        {field: "示例值" for field in missing_fields}, ensure_ascii=False)

    prompt = f"""你是一个严格的电商产品参数提取助手。

当前产品类型：{product_name}

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
7. 字段值尽量使用中文表述；规格数值、单位、型号可以保留原文。"""

    for attempt in range(1, MAX_TEXT_RETRIES + 1):
        if stop_event.is_set():
            return {}
        reservation = limiter.acquire(ESTIMATED_TOKENS, stop_event)
        if reservation is None:
            return {}
        started = time.monotonic()
        try:
            response = get_text_client().chat.completions.create(
                model=MODEL_TEXT,
                messages=[
                    {"role": "system",
                     "content": "你是一个结构化商品参数提取器，只输出 JSON，不推测。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0,
                max_tokens=1200,
            )
            elapsed = time.monotonic() - started
            usage = extract_usage(response)
            limiter.reconcile(reservation, usage)
            metrics.record_attempt(elapsed)
            content = response.choices[0].message.content.strip()
            data = parse_json_from_ai(content)
            return filter_valid_fields(data, missing_fields)
        except Exception as e:
            elapsed = time.monotonic() - started
            rate_limited = is_rate_limit_error(e)
            metrics.record_attempt(elapsed, rate_limited=rate_limited)
            if attempt >= MAX_TEXT_RETRIES:
                print(f"[文本提取失败] 行重试耗尽: {e}", flush=True)
                return {}
            if rate_limited:
                server_wait = retry_after_seconds(e)
                delay = (server_wait if server_wait is not None
                         else RATE_LIMIT_WAIT * attempt) + random.uniform(0, RETRY_JITTER)
                print(f"[限流] 文本提取 429，等待 {delay:.1f}s", flush=True)
            else:
                delay = 1.2 * attempt + random.uniform(0, min(RETRY_JITTER, 0.8))
            metrics.record_retry()
            if wait_interruptibly(delay, stop_event):
                return {}
    return {}


def download_images_parallel(urls: List[str]):
    """并行下载图片并转 base64。

    返回 dict:
    - base64_images: 有效图片的 data URL 列表
    - size_infos: 与 base64_images 一一对应的尺寸信息
    - skipped_small: 因分辨率过低跳过的数量
    - failed: 下载失败的数量
    """
    results = [None] * len(urls)
    with ThreadPoolExecutor(max_workers=min(len(urls), 4)) as dl_pool:
        futures = {dl_pool.submit(get_image_base64_from_url, url): i
                   for i, url in enumerate(urls)}
        for future in futures:
            idx = futures[future]
            try:
                results[idx] = future.result()
            except Exception:
                results[idx] = {"status": "error", "data": None, "info": {}}
    base64_images, size_infos, skipped_small, failed = [], [], 0, 0
    for r in results:
        if r is None or r["status"] == "error":
            failed += 1
        elif r["status"] == "small":
            skipped_small += 1
        else:
            base64_images.append(r["data"])
            size_infos.append(r["info"])
    return {
        "base64_images": base64_images,
        "size_infos": size_infos,
        "skipped_small": skipped_small,
        "failed": failed,
    }


def extract_vision_features_concurrent(
    image_urls: List[str],
    missing_fields: List[str],
    vision_allowed_fields: List[str],
    vision_field_config: Dict[str, str],
    field_config: Dict[str, str],
    product_name: str,
    limiter: RollingWindowRateLimiter,
    metrics: RequestMetrics,
    stop_event: threading.Event,
) -> Tuple[Dict[str, Any], Dict[str, Any], str, List[Dict[str, Any]]]:
    """并发版视觉提取。返回 (过滤结果, 原始JSON, 原始文本, 图片尺寸信息)。"""
    if not image_urls or not missing_fields or not vision_allowed_fields:
        return {}, {}, "", []

    vision_fields = [f for f in missing_fields if f in vision_allowed_fields]
    if not vision_fields:
        return {}, {}, "", []

    field_details = "\n".join([
        f"- {field}: {vision_field_config.get(field, field_config.get(field, '无具体说明，请根据图片信息提取。'))}"
        for field in vision_fields
    ])
    example_json = {
        field: {"value": "", "evidence": "", "confidence": 0}
        for field in vision_fields
    }
    prompt_text = f"""你是一个非常严格的电商产品图片 OCR 与参数提取助手。

当前产品类型：{product_name}

你只能基于以下两类证据提取信息：
1. 图片中清晰可见的文字；
2. 图片中肉眼可以直接数出的硬件结构，例如插孔数量、USB 接口数量、开关数量。

严禁事项：
1. 严禁根据产品类别推测功能。
2. 严禁根据同类产品常见配置推测参数。
3. 严禁看到手机 App 图标就推断支持定时、功耗监测、远程控制。
4. 严禁看到 USB 接口就推断 USB 功率。
5. 严禁在图片没有明确文字证据时填写功率、线缆长度、安全保护等字段。
6. 对于可以肉眼数出的接口数量，evidence 必须写清楚"图片中可见几个"。

本次只需要补全以下字段：
{field_details}

输出要求：
1. 每个字段都必须返回 value、evidence、confidence。
2. value 是提取值。
3. evidence 必须说明图片中的具体依据，例如"图片中可见4个AC插座"或"包装文字显示5V/2.1A"。
4. 如果没有清晰证据，value 和 evidence 必须为空字符串，confidence 为 0。
5. 只输出 JSON，不要输出解释、分析、Markdown 代码块。

请严格按以下 JSON 格式输出：
{json.dumps(example_json, ensure_ascii=False)}"""

    # 并行下载图片
    dl = download_images_parallel(image_urls)
    base64_images = dl["base64_images"]
    size_infos = dl["size_infos"]
    if dl["skipped_small"]:
        print(f"[视觉] 跳过 {dl['skipped_small']} 张分辨率过低图片", flush=True)
    if not base64_images:
        return {}, {}, "", size_infos

    content_list = [
        {"type": "image_url", "image_url": {"url": b64, "detail": "high"}}
        for b64 in base64_images
    ]
    content_list.append({"type": "text", "text": prompt_text})

    for attempt in range(1, MAX_VISION_RETRIES + 1):
        if stop_event.is_set():
            return {}, {}, "", size_infos
        reservation = limiter.acquire(ESTIMATED_TOKENS * 2, stop_event)
        if reservation is None:
            return {}, {}, "", size_infos
        started = time.monotonic()
        try:
            response = get_vision_client().chat.completions.create(
                model=MODEL_VISION,
                messages=[{"role": "user", "content": content_list}],
                max_tokens=1500,
                temperature=0,
            )
            elapsed = time.monotonic() - started
            usage = extract_usage(response)
            limiter.reconcile(reservation, usage)
            metrics.record_attempt(elapsed)
            raw_text = response.choices[0].message.content.strip()
            raw_data = parse_json_from_ai(raw_text)
            result = filter_valid_vision_fields_with_evidence(
                raw_data, vision_fields, min_confidence=MIN_VISION_CONFIDENCE)
            return result, raw_data, raw_text, size_infos
        except Exception as e:
            elapsed = time.monotonic() - started
            rate_limited = is_rate_limit_error(e)
            metrics.record_attempt(elapsed, rate_limited=rate_limited)
            if attempt >= MAX_VISION_RETRIES:
                print(f"[视觉提取失败] 重试耗尽: {e}", flush=True)
                return {}, {}, "", size_infos
            if rate_limited:
                server_wait = retry_after_seconds(e)
                delay = (server_wait if server_wait is not None
                         else RATE_LIMIT_WAIT * attempt) + random.uniform(0, RETRY_JITTER)
            else:
                delay = 2.0 * attempt + random.uniform(0, min(RETRY_JITTER, 0.8))
            metrics.record_retry()
            if wait_interruptibly(delay, stop_event):
                return {}, {}, "", size_infos
    return {}, {}, "", size_infos


# ================= 7. 单行处理 =================

def process_single_row(
    index: int,
    row: Dict[str, Any],
    df_columns: List[str],
    target_fields: List[str],
    field_config: Dict[str, str],
    product_name: str,
    vision_allowed_fields: List[str],
    vision_field_config: Dict[str, str],
    enable_vision: bool,
    text_limiter: RollingWindowRateLimiter,
    vision_limiter: RollingWindowRateLimiter,
    text_metrics: RequestMetrics,
    vision_metrics: RequestMetrics,
    stop_event: threading.Event,
) -> Tuple[int, Dict[str, Any], str]:
    """处理单行：文本提取 + 可选视觉补全。返回 (index, 结果dict, 状态)。"""
    if stop_event.is_set():
        return index, {}, "已停止"

    # 检查是否已完成
    already_done = all(not is_empty(row.get(f, "")) for f in target_fields)
    if already_done:
        return index, {"_skipped": True}, ""

    extracted_data = {}
    text_fields = []
    vision_fields_all = []
    vision_batch_logs = []

    # 计算缺失字段
    missing_fields = [f for f in target_fields if is_empty(row.get(f, ""))]

    # 文本提取
    text_data = extract_text_features_concurrent(
        row, missing_fields, product_name, field_config,
        text_limiter, text_metrics, stop_event)
    if text_data:
        extracted_data.update(text_data)
        text_fields.extend(text_data.keys())

    # 重新计算缺失
    missing_fields = [
        f for f in target_fields
        if is_empty(row.get(f, "")) and is_empty(extracted_data.get(f, ""))
    ]

    # 视觉补全
    vision_missing = [f for f in missing_fields if f in vision_allowed_fields]
    if enable_vision and vision_missing and not stop_event.is_set():
        all_imgs = get_valid_image_urls(row, df_columns)
        if all_imgs:
            limited_imgs = all_imgs[:MAX_VISION_IMAGES_PER_ROW]
            empty_batch_count = 0
            for i in range(0, len(limited_imgs), VISION_BATCH_SIZE):
                if stop_event.is_set():
                    break
                # 重新计算视觉缺失
                cur_missing = [
                    f for f in target_fields
                    if is_empty(row.get(f, "")) and is_empty(extracted_data.get(f, ""))
                ]
                cur_vision_missing = [f for f in cur_missing if f in vision_allowed_fields]
                if not cur_vision_missing:
                    break
                if empty_batch_count >= MAX_EMPTY_VISION_BATCHES:
                    break

                batch_imgs = limited_imgs[i:i + VISION_BATCH_SIZE]
                vision_data, vision_raw, vision_raw_text, vision_size_infos = extract_vision_features_concurrent(
                    batch_imgs, cur_vision_missing, vision_allowed_fields,
                    vision_field_config, field_config, product_name,
                    vision_limiter, vision_metrics, stop_event)

                batch_log = {
                    "批次": i // VISION_BATCH_SIZE + 1,
                    "图片数量": len(batch_imgs),
                    "尝试补全字段": cur_vision_missing,
                    "通过过滤后的结果": vision_data,
                    "图片尺寸信息": vision_size_infos,
                    "模型原始JSON": vision_raw,
                }
                vision_batch_logs.append(batch_log)

                if vision_data:
                    extracted_data.update(vision_data)
                    vision_fields_all.extend(vision_data.keys())
                    empty_batch_count = 0
                else:
                    empty_batch_count += 1

    # 构建结果
    result = {
        "_extracted": extracted_data,
        "_text_fields": text_fields,
        "_vision_fields": vision_fields_all,
        "_vision_logs": vision_batch_logs,
    }

    if stop_event.is_set():
        return index, result, "已停止"
    return index, result, ""


# ================= 8. 并发主循环 =================

def fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m}m{s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m"


def check_stop_file() -> bool:
    return bool(STOP_FILE) and os.path.exists(STOP_FILE)


def build_run_signature(product_config: Dict[str, Any]) -> Dict[str, Any]:
    input_stat = os.stat(INPUT_FILE)
    config_payload = json.dumps(
        product_config, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")
    return {
        "input_file": os.path.abspath(INPUT_FILE),
        "input_size": input_stat.st_size,
        "input_mtime_ns": input_stat.st_mtime_ns,
        "product": CURRENT_PRODUCT,
        "model_text": MODEL_TEXT,
        "model_vision": MODEL_VISION,
        "config_sha256": hashlib.sha256(config_payload).hexdigest(),
    }


def main():
    global CURRENT_PRODUCT

    if not INPUT_FILE:
        raise ValueError("未检测到环境变量 INPUT_FILE")
    if not OUTPUT_FILE:
        # 默认输出路径
        base, ext = os.path.splitext(INPUT_FILE)
        OUTPUT_FILE_LOCAL = f"{base}_打标{ext or '.xlsx'}"
    else:
        OUTPUT_FILE_LOCAL = OUTPUT_FILE

    # 加载配置
    CURRENT_PRODUCT, product_config = load_product_config(CONFIG_FILE, CURRENT_PRODUCT)
    product_name = product_config.get("name", CURRENT_PRODUCT)
    target_fields = list(product_config["target_fields"])
    field_config = dict(product_config["field_config"])
    vision_allowed_fields = list(product_config.get("vision_allowed_fields", []))
    vision_field_config = dict(product_config.get("vision_field_config", {}))

    # FIELDS 过滤
    fields_filter = os.getenv("FIELDS", "").strip()
    if fields_filter:
        selected = [f.strip() for f in fields_filter.split(",") if f.strip()]
        invalid = [f for f in selected if f not in field_config]
        if invalid:
            print(f"[警告] 以下字段不在配置中，将被忽略: {invalid}", flush=True)
        valid = [f for f in selected if f in field_config]
        if not valid:
            print("[错误] 没有有效的目标字段，退出。", flush=True)
            return
        target_fields = valid
        print(f"[模式] 部分字段提取，目标字段: {target_fields}", flush=True)

    enable_vision = ENABLE_VISION_DEFAULT

    # 清除停止信号
    if STOP_FILE and os.path.exists(STOP_FILE):
        os.remove(STOP_FILE)

    # 读取输入
    print(f"读取文件：{INPUT_FILE}", flush=True)
    df = pd.read_excel(INPUT_FILE)

    missing_text_cols = [col for col in TEXT_COLS if col not in df.columns]
    if missing_text_cols:
        if not ENABLE_FETCH:
            raise ValueError(f"Excel 中缺少以下文本列：{missing_text_cols}")
        for col in missing_text_cols:
            df[col] = ""
        print(f"[补抓] 自动补建缺失文本列：{missing_text_cols}", flush=True)

    for field in target_fields + AUX_FIELDS:
        if field not in df.columns:
            df[field] = ""
    df["_处理状态"] = ""

    output_dir = os.path.dirname(OUTPUT_FILE_LOCAL)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    n = len(df)
    print(f"当前产品配置：{CURRENT_PRODUCT} / {product_name}", flush=True)
    print(f"共 {n} 条商品数据，目标字段 {len(target_fields)} 个", flush=True)
    print(f"并发数: {CONCURRENCY} | 文本RPM: {RPM_LIMIT or '关闭'} | "
          f"视觉RPM: {VISION_RPM_LIMIT or '关闭'}", flush=True)
    print(f"图片识别：{'启用' if enable_vision else '关闭'} | "
          f"可补字段: {len(vision_allowed_fields)}", flush=True)

    # 断点
    checkpoint_path = os.getenv("EXTRACT_CHECKPOINT_FILE") or f"{OUTPUT_FILE_LOCAL}.checkpoint.json"
    signature = build_run_signature(product_config)
    checkpoint = CheckpointStore(checkpoint_path, signature)
    if checkpoint.load_warning:
        print(f"[提示] {checkpoint.load_warning}", flush=True)
    if checkpoint.loaded:
        print(f"发现有效断点，将跳过已成功条目: {checkpoint.path}", flush=True)

    # 限速器与指标
    text_limiter = RollingWindowRateLimiter(RPM_LIMIT, TPM_LIMIT)
    vision_limiter = RollingWindowRateLimiter(VISION_RPM_LIMIT, 0)
    text_metrics = RequestMetrics()
    vision_metrics = RequestMetrics()

    # 准备行数据
    rows_data = [row.to_dict() for _, row in df.iterrows()]
    df_columns = list(df.columns)
    stop_event = threading.Event()

    # ---- 补抓准备：缺资料的行登记 ASIN，工作线程里现抓现用 ----
    fetch_needed: Dict[int, str] = {}
    fetch_checkpoint: Dict[str, Any] = {}
    fetch_checkpoint_path = ""
    fetch_lock = threading.Lock()
    fetch_pool = None
    if ENABLE_FETCH:
        from core.reviews.product_fetcher import resolve_asin_and_url
        link_col = next((c for c in FETCH_LINK_CANDIDATES if c in df.columns), None)
        if link_col is None:
            raise ValueError(f"已启用补抓但未找到链接列，候选列名：{FETCH_LINK_CANDIDATES}")
        for col in IMAGE_COLS:
            if col not in df.columns:
                df[col] = ""
        movable = ["五点描述"] + IMAGE_COLS
        ordered = [c for c in df.columns if c not in movable]
        if "商品标题" in ordered:
            pos = ordered.index("商品标题") + 1
            ordered = ordered[:pos] + ["五点描述"] + ordered[pos:]
        else:
            ordered = ordered + ["五点描述"]
        anchor2 = "商品主图" if "商品主图" in ordered else "五点描述"
        pos2 = ordered.index(anchor2) + 1
        ordered = ordered[:pos2] + IMAGE_COLS + ordered[pos2:]
        df = df[ordered]
        df_columns = list(df.columns)

        fetch_checkpoint_path = f"{OUTPUT_FILE_LOCAL}.fetch_checkpoint.json"
        if os.path.exists(fetch_checkpoint_path):
            try:
                with open(fetch_checkpoint_path, encoding="utf-8") as fh:
                    fetch_checkpoint = json.load(fh)
            except Exception as exc:
                print(f"[警告] 抓取断点读取失败，忽略：{exc}", flush=True)
        reused = 0
        for idx, row in enumerate(rows_data):
            need = is_empty(row.get("五点描述")) or all(
                is_empty(row.get(c)) for c in IMAGE_COLS)
            if not need:
                continue
            link = str(row.get(link_col) or "").strip()
            if not link:
                continue
            try:
                asin, _ = resolve_asin_and_url(link)
            except Exception:
                continue
            entry = fetch_checkpoint.get(asin)
            if entry and entry.get("ok"):
                apply_fetch_to_row(row, entry)
                reused += 1
            else:
                fetch_needed[idx] = asin
        print(f"[补抓] 待抓取 {len(fetch_needed)} 行 | 断点复用 {reused} 行 | "
              f"提取并发 {CONCURRENCY} | 抓取线程 {FETCH_WORKERS} | "
              f"预抓缓冲 {FETCH_LOOKAHEAD}", flush=True)
        fetch_pool = FetchPool(
            FETCH_WORKERS, fetch_checkpoint, fetch_checkpoint_path, fetch_lock,
            stop_check=stop_event.is_set)
        print(f"[补抓] 抓取线程池已启动：{FETCH_WORKERS} 个抓取线程（解耦流水线，提前预抓）",
              flush=True)

    # 结果存储
    results: List[Optional[Dict[str, Any]]] = [None] * n
    statuses: List[str] = [""] * n

    stats = {
        "total": n, "completed": 0, "succeeded": 0, "failed": 0,
        "skipped": 0, "resumed": 0, "stopped": False,
    }
    start_time = time.time()

    pending = deque()
    unsaved_updates = 0
    save_lock = threading.Lock()

    def save_checkpoint(force=False):
        nonlocal unsaved_updates
        if not force and unsaved_updates < CHECKPOINT_EVERY:
            return
        checkpoint.save()
        unsaved_updates = 0

    def store_result(index: int, details: Dict[str, Any], status: str):
        nonlocal unsaved_updates
        results[index] = details
        statuses[index] = status
        checkpoint.update(index, details, status)
        unsaved_updates += 1
        save_checkpoint()

    def apply_row_to_df(index: int, result: Dict[str, Any], status: str):
        """把单行结果增量写回 DataFrame，便于周期性保存 Excel。"""
        if result.get("_skipped"):
            return
        extracted_data = result.get("_extracted", {})
        text_fields = result.get("_text_fields", [])
        vision_fields_all = result.get("_vision_fields", [])
        vision_batch_logs = result.get("_vision_logs", [])
        for field in target_fields:
            value = extracted_data.get(field, "")
            if not is_empty(value) and is_empty(df.at[index, field]):
                df.at[index, field] = value
        final_missing = [f for f in target_fields if is_empty(df.at[index, f])]
        df.at[index, "文本提取字段"] = "；".join(sorted(set(text_fields)))
        df.at[index, "图片识别提取字段"] = "；".join(sorted(set(vision_fields_all)))
        df.at[index, "图片识别批次日志"] = json.dumps(vision_batch_logs, ensure_ascii=False)
        df.at[index, "最终缺失字段"] = "；".join(final_missing)
        df.at[index, "提取完整状态"] = "是" if not final_missing else "否"
        df.at[index, "_处理状态"] = status

    def save_excel():
        try:
            df.to_excel(OUTPUT_FILE_LOCAL, index=False)
        except Exception as exc:
            print(f"[警告] 临时保存 Excel 失败（不影响断点续跑）: {exc}", flush=True)

    # 加载断点（需在 apply_row_to_df 定义之后）
    if checkpoint.loaded:
        for idx, details in checkpoint.successful_rows().items():
            if 0 <= idx < n:
                results[idx] = details
                statuses[idx] = ""
                apply_row_to_df(idx, details, "")
                stats["completed"] += 1
                stats["succeeded"] += 1
                stats["resumed"] += 1

    pending = deque(i for i, r in enumerate(results) if r is None)

    # ---- 解耦预抓：按提取消费顺序，提前把后面若干行的抓取请求排进抓取线程池 ----
    # 抓取线程在后台把这些行抓好放进各自 Future 缓冲；提取 worker 走到某行时
    # request(asin) 命中同一个（多半已完成的）Future，几乎不用等，实现两级流水线。
    prefetch_order: List[str] = []
    if ENABLE_FETCH and fetch_pool is not None:
        _seen_asin = set()
        for _idx in pending:
            _asin = fetch_needed.get(_idx)
            if _asin and _asin not in _seen_asin:
                _seen_asin.add(_asin)
                prefetch_order.append(_asin)
    prefetch_futures: Dict[str, Future] = {}
    prefetch_cursor = 0

    def pump_prefetch():
        """维持在途抓取请求数 ≤ FETCH_LOOKAHEAD，让抓取始终跑在提取前面。"""
        nonlocal prefetch_cursor
        if not prefetch_order or fetch_pool is None or stop_event.is_set():
            return
        outstanding = sum(1 for f in prefetch_futures.values() if not f.done())
        while prefetch_cursor < len(prefetch_order) and outstanding < FETCH_LOOKAHEAD:
            asin = prefetch_order[prefetch_cursor]
            prefetch_cursor += 1
            if asin in prefetch_futures:
                continue
            prefetch_futures[asin] = fetch_pool.request(asin)
            outstanding += 1
        if len(prefetch_futures) > FETCH_LOOKAHEAD * 4:
            for a in [a for a, f in prefetch_futures.items() if f.done()]:
                prefetch_futures.pop(a, None)

    def print_progress(force=False):
        done = stats["completed"]
        if not force and done % PROGRESS_EVERY != 0 and done != n:
            return
        elapsed = time.time() - start_time
        eta = elapsed / done * (n - done) if done and done < n else 0.0
        print(
            f"进度: {done}/{n} ({done * 100 // max(1, n)}%) | "
            f"跳过 {stats['skipped']} | 断点复用 {stats['resumed']} | "
            f"失败 {stats['failed']} | "
            f"已用 {fmt_duration(elapsed)} | 剩余约 {fmt_duration(eta)}",
            flush=True)

    def worker(index: int):
        row = rows_data[index]
        if ENABLE_FETCH and index in fetch_needed and not stop_event.is_set():
            asin = fetch_needed[index]
            with fetch_lock:
                entry = fetch_checkpoint.get(asin)
            if not (entry and entry.get("ok")):
                entry = fetch_pool.request(asin).result()
            if entry.get("ok"):
                apply_fetch_to_row(row, entry)
                print(f"[补抓] 第 {index + 1} 行 {asin}：五点 "
                      f"{len(entry.get('bullets') or [])} 条、图片 "
                      f"{len(entry.get('images') or [])} 张", flush=True)
            else:
                print(f"[补抓] 第 {index + 1} 行 {asin} 抓取失败，按现有列继续提取",
                      flush=True)
        return process_single_row(
            index, rows_data[index], df_columns, target_fields,
            field_config, product_name, vision_allowed_fields,
            vision_field_config, enable_vision,
            text_limiter, vision_limiter, text_metrics, vision_metrics,
            stop_event)

    # ---- 并发执行 ----
    executor = ThreadPoolExecutor(max_workers=CONCURRENCY)
    in_flight = {}

    def submit_until_full():
        while pending and len(in_flight) < CONCURRENCY and not stop_event.is_set():
            idx = pending.popleft()
            future = executor.submit(worker, idx)
            in_flight[future] = idx

    try:
        if check_stop_file():
            stop_event.set()
            stats["stopped"] = True
        pump_prefetch()
        submit_until_full()

        while in_flight:
            if check_stop_file() and not stop_event.is_set():
                stop_event.set()
                stats["stopped"] = True

            finished, _ = wait(tuple(in_flight), timeout=0.2,
                               return_when=FIRST_COMPLETED)
            if not finished:
                continue

            for future in finished:
                idx = in_flight.pop(future)
                try:
                    _, result, status = future.result()
                except Exception as exc:
                    print(f"[失败] 第 {idx + 1} 行异常: {exc}", flush=True)
                    result, status = {}, "AI提取失败"

                if ENABLE_FETCH and idx in fetch_needed:
                    for col in ["五点描述"] + IMAGE_COLS:
                        value = rows_data[idx].get(col)
                        if not is_empty(value) and is_empty(df.at[idx, col]):
                            df.at[idx, col] = value
                store_result(idx, result, status)
                apply_row_to_df(idx, result, status)
                stats["completed"] += 1
                if status == "AI提取失败":
                    stats["failed"] += 1
                elif status == "已停止":
                    stats["stopped"] = True
                elif result.get("_skipped"):
                    stats["skipped"] += 1
                    stats["succeeded"] += 1
                else:
                    stats["succeeded"] += 1
                print_progress()
                if stats["completed"] % SAVE_EVERY == 0:
                    save_excel()
                    print(f"已临时保存到：{OUTPUT_FILE_LOCAL}", flush=True)

            pump_prefetch()
            submit_until_full()
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
        if fetch_pool is not None:
            fetch_pool.shutdown()

    if stop_event.is_set():
        stats["stopped"] = True

    # 未提交的行标记为已停止
    for idx in list(pending):
        store_result(idx, {}, "已停止")
        apply_row_to_df(idx, {}, "已停止")
        stats["completed"] += 1

    # 兜底
    for idx, r in enumerate(results):
        if r is None:
            status = "已停止" if stats["stopped"] else "AI提取失败"
            store_result(idx, {}, status)
            apply_row_to_df(idx, {}, status)
            stats["completed"] += 1

    save_checkpoint(force=True)
    print_progress(force=True)

    # 最终保存
    df.to_excel(OUTPUT_FILE_LOCAL, index=False)

    # ---- 统计 ----
    elapsed = time.time() - start_time
    print("\n" + "=" * 50, flush=True)
    t_snap = text_metrics.snapshot()
    v_snap = vision_metrics.snapshot()
    print(f"文本 API: {t_snap['api_requests']} 次 | 重试 {t_snap['retries']} | "
          f"429 {t_snap['rate_limits']}", flush=True)
    print(f"视觉 API: {v_snap['api_requests']} 次 | 重试 {v_snap['retries']} | "
          f"429 {v_snap['rate_limits']}", flush=True)
    print(f"总耗时: {fmt_duration(elapsed)} | 并发数: {CONCURRENCY}", flush=True)
    if stats["resumed"] > 0:
        print(f"断点复用: {stats['resumed']} 条", flush=True)
    if stats["failed"] > 0:
        print(f"[警告] 失败 {stats['failed']} 条，断点保留: {checkpoint.path}", flush=True)
    print("=" * 50, flush=True)

    if stats["stopped"]:
        print(f"\n[停止] 用户中止，已完成条目已保存: {OUTPUT_FILE_LOCAL}", flush=True)
        print(f"下次运行可从断点继续: {checkpoint.path}", flush=True)
        raise SystemExit(1)

    # 全部成功则删除断点
    if stats["failed"] == 0:
        checkpoint.remove()

    print(f"\n处理完成！结果已保存至：{OUTPUT_FILE_LOCAL}", flush=True)


if __name__ == "__main__":
    main()
