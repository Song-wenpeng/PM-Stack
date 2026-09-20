"""Authenticated loopback bridge for the user's normal browser extension."""
from __future__ import annotations

import hmac
import json
import re
import secrets
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace
from urllib.parse import urlparse

from .normalizer import extract_asin
from .service import collect_product
from .store import ReviewStore

MARKETS = {"amazon.com", "amazon.co.uk", "amazon.de", "amazon.co.jp", "amazon.com.au"}
ORIGIN = re.compile(r"chrome-extension://[a-p]{32}")
PORT = 18765


def default_browser():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice") as key:
            progid = winreg.QueryValueEx(key, "ProgId")[0]
        if "MSEdge" in progid:
            return "Microsoft Edge"
        if "Chrome" in progid:
            return "Google Chrome"
        return str(progid) + "（第一版仅支持 Edge / Chrome）"
    except (ImportError, OSError):
        return "未识别（可在 Edge / Chrome 中连接扩展）"


def validate_reviews(rows):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        raise ValueError("需要 1–100 条实际评论；空白、登录或未知页面不会记为采集成功")
    result = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("评论格式错误")
        rating = row.get("rating")
        if isinstance(rating, bool) or not isinstance(rating, (int, float)) or not 1 <= rating <= 5:
            raise ValueError("评论星级无效")
        content = row.get("content", "")
        if not isinstance(content, str) or not content.strip() or len(content) > 30000:
            raise ValueError("评论正文为空或过长")
        clean = {"rating": rating, "content": content,
                 "verified_purchase": row.get("verified_purchase") is True}
        for field in ("review_id", "element_id", "reviewer_name", "title", "date", "helpful_votes"):
            value = row.get(field, "")
            if not isinstance(value, str) or len(value) > 2000:
                raise ValueError("评论字段无效")
            clean[field] = value
        result.append(clean)
    return result


class ExtensionBridge:
    def __init__(self, db_path=None, port=PORT):
        self.db_path, self.port = db_path, port
        store = ReviewStore(db_path)
        try:
            self.token = store.get_setting("extension_pairing_token", "")
            if not self.token:
                self.token = secrets.token_urlsafe(32)
                store.set_setting("extension_pairing_token", self.token)
        finally:
            store.close()
        self.lock = threading.RLock()
        self.job = None
        self.last_seen = 0.0
        self.client = None
        self.server = None

    def start(self):
        if self.server:
            return
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(5)

            def log_message(self, *args):
                pass  # Never log pairing credentials or captured data.

            def reply(self, status, payload, cors=False):
                raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                if cors:
                    self.send_header("Access-Control-Allow-Origin", self.headers["Origin"])
                    self.send_header("Vary", "Origin")
                    self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
                    self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
                self.end_headers()
                self.wfile.write(raw)

            def origin_ok(self):
                return (bool(ORIGIN.fullmatch(self.headers.get("Origin", "")))
                        and self.headers.get("Host") == f"127.0.0.1:{bridge.port}")

            def do_OPTIONS(self):
                self.reply(204 if self.origin_ok() else 403, {}, self.origin_ok())

            def do_POST(self):
                if not self.origin_ok():
                    self.reply(403, {"error": "Only the paired browser extension may connect"})
                    return
                if not hmac.compare_digest(self.headers.get("Authorization", ""),
                                           "Bearer " + bridge.token):
                    self.reply(401, {"error": "连接码不正确，请从 PM Stack 重新复制"}, True)
                    return
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= 1_000_000:
                        raise ValueError("请求大小无效")
                    body = json.loads(self.rfile.read(size))
                    if not isinstance(body, dict):
                        raise ValueError("请求格式无效")
                    with bridge.lock:
                        response = bridge.handle(self.path, body)
                    self.reply(200, response, True)
                except (ValueError, KeyError, TypeError) as exc:
                    self.reply(400, {"error": str(exc)}, True)
                except Exception:
                    self.reply(500, {"error": "本地保存失败，请重试；已保存评论会自动去重"}, True)

        self.server = HTTPServer(("127.0.0.1", self.port), Handler)
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(timeout=6)
            self.server = None

    def submit(self, value, marketplace):
        asin = extract_asin(value)
        if not re.fullmatch(r"[A-Z0-9]{10}", asin) or marketplace not in MARKETS:
            raise ValueError("请输入有效 ASIN，并选择支持的 Amazon 站点")
        if "://" in value:
            parsed = urlparse(value)
            if parsed.scheme != "https" or parsed.hostname not in (marketplace, "www." + marketplace):
                raise ValueError("链接站点与所选站点不一致")
        with self.lock:
            if self.job and self.job["status"] in ("queued", "running", "waiting"):
                raise ValueError("请先完成或取消当前任务")
            self.job = {"id": uuid.uuid4().hex, "asin": asin, "marketplace": marketplace,
                        "url": f"https://www.{marketplace}/product-reviews/{asin}/?sortBy=recent&pageNumber=1",
                        "status": "queued", "message": "等待扩展领取，可点击扩展的“立即检查任务”"}
            return dict(self.job)

    def cancel(self):
        with self.lock:
            if self.job and self.job["status"] in ("queued", "running", "waiting"):
                self.job.update(status="cancelled", message="任务已取消；浏览器标签页保留")

    def snapshot(self):
        with self.lock:
            return {"connected": time.monotonic() - self.last_seen < 75,
                    "job": dict(self.job) if self.job else None}

    def handle(self, path, body):
        client = body.get("client", "")
        if not isinstance(client, str) or not re.fullmatch(r"[a-zA-Z0-9-]{16,80}", client):
            raise ValueError("扩展连接标识无效")
        if path == "/poll":
            if self.client and client != self.client:
                raise ValueError("已有另一个浏览器配置连接；请先在 PM Stack 断开连接")
            self.client = client
            self.last_seen = time.monotonic()
            if self.job and self.job["status"] == "queued":
                self.job.update(status="running", message="扩展已领取，正在打开评论页")
            return {"job": dict(self.job) if self.job else None}
        if path != "/result":
            raise ValueError("未知接口")
        if client != self.client or not self.job or body.get("id") != self.job["id"]:
            raise ValueError("任务已过期或连接不匹配")
        job = self.job
        if job["status"] in ("done", "cancelled", "error"):
            return {"job": dict(job)}
        if job["status"] not in ("running", "waiting"):
            raise ValueError("任务尚未领取")
        status = body.get("status")
        if status in ("waiting", "error"):
            message = str(body.get("message", ""))[:500]
            job.update(status=status, message=message)
            return {"job": dict(job)}
        if status != "ready":
            raise ValueError("结果状态无效")
        parsed = urlparse(str(body.get("url", "")))
        if (parsed.scheme != "https" or parsed.hostname != "www." + job["marketplace"]
                or not re.fullmatch(r"/product-reviews/" + job["asin"] + r"/?", parsed.path)):
            raise ValueError("结果不是本次指定商品的评论页")
        rows = validate_reviews(body.get("reviews"))
        title = body.get("title", "")
        if not isinstance(title, str) or len(title) > 2000:
            raise ValueError("商品标题无效")
        # Same normalization, idempotent review IDs, run log and outbox as existing collection.
        adapter = SimpleNamespace(last_warnings=[], last_product_categories=[],
                                  scrape_reviews=lambda *args, **kwargs: (title, rows))
        store = ReviewStore(self.db_path)
        try:
            new, duplicates = collect_product(store, adapter, job["asin"], job["marketplace"],
                                              1, 100, True, mode="flat")
        finally:
            store.close()
        job.update(status="done", message=f"本页新增 {new} 条，重复 {duplicates} 条",
                   new=new, duplicates=duplicates)
        return {"job": dict(job)}
