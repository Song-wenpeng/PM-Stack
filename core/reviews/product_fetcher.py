"""亚马逊商品详情抓取：五点描述与主副图 URL。

供市场规划模块在字段提取前补齐 Excel 的「五点描述」和 image_1..N 列。
浏览器启动方式与评论爬虫一致（Playwright 控制系统 Edge），但使用全新
浏览器上下文，不占用评论爬虫的登录目录。
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

from .config import DEFAULT_MARKETPLACE, MARKETPLACES, PAGE_LOAD_TIMEOUT, PLAYWRIGHT_BROWSER_CHANNEL

ASIN_PATTERN = re.compile(r"[A-Z0-9]{10}")

MARKETPLACE_LOCALES = {
    "amazon.com": ("en-US", "en_US", "USD"),
    "amazon.co.uk": ("en-GB", "en_GB", "GBP"),
    "amazon.de": ("de-DE", "de_DE", "EUR"),
    "amazon.co.jp": ("ja-JP", "ja_JP", "JPY"),
    "amazon.com.au": ("en-AU", "en_AU", "AUD"),
}

EXTRACT_JS = """
() => {
  const captcha = !!document.querySelector(
    'form[action*="validateCaptcha"], #captchacharacters');
  const titleEl = document.getElementById('productTitle');
  const bullets = [...document.querySelectorAll('#feature-bullets li span.a-list-item')]
    .map(e => e.textContent.replace(/\\s+/g, ' ').trim()).filter(Boolean);
  let images = [];
  for (const s of document.querySelectorAll('script:not([src])')) {
    const txt = s.textContent || '';
    const idx = txt.indexOf("'colorImages'");
    if (idx === -1) continue;
    const start = txt.indexOf('[', idx);
    if (start === -1) continue;
    let depth = 0, end = -1, inStr = false, esc = false;
    for (let i = start; i < txt.length; i++) {
      const c = txt[i];
      if (inStr) {
        if (esc) { esc = false; }
        else if (c === '\\\\') { esc = true; }
        else if (c === "'") { inStr = false; }
        continue;
      }
      if (c === "'") { inStr = true; continue; }
      if (c === '[') { depth++; }
      else if (c === ']') { depth--; if (depth === 0) { end = i; break; } }
    }
    if (end === -1) continue;
    try {
      const arr = JSON.parse(txt.slice(start, end + 1).replace(/'/g, '"'));
      images = arr.filter(e => !e.videoUrl)
        .map(e => e.hiRes || e.large || '').filter(Boolean);
    } catch (e) { /* 内嵌 JSON 结构变化时走下面的 DOM 兜底 */ }
    break;
  }
  if (images.length === 0) {
    const main = document.getElementById('landingImage');
    if (main) {
      const u = main.getAttribute('data-old-hires') || main.getAttribute('src');
      if (u) images.push(u);
    }
    for (const img of document.querySelectorAll('#altImages li img')) {
      const u = img.getAttribute('data-old-hires') || img.getAttribute('src');
      if (u && !images.includes(u)) images.push(u);
    }
  }
  return {
    captcha: captcha,
    title: titleEl ? titleEl.textContent.trim() : '',
    bullets: bullets,
    images: images,
    finalUrl: location.href
  };
}
"""


class ProductFetchError(RuntimeError):
    """页面加载、验证码或页面结构导致抓取结果不可信。"""


def resolve_asin_and_url(asin_or_url: str, marketplace: str = DEFAULT_MARKETPLACE) -> tuple:
    """把 ASIN 或商品链接归一化为 (ASIN, dp 链接)。"""
    value = (asin_or_url or "").strip()
    match = ASIN_PATTERN.search(value.upper())
    if not match:
        raise ProductFetchError(f"无法从输入中识别 ASIN：{asin_or_url}")
    base_url = MARKETPLACES.get(marketplace, MARKETPLACES[DEFAULT_MARKETPLACE])
    return match.group(0), f"{base_url}/dp/{match.group(0)}"


def normalize_amazon_image_url(image_url: str) -> str:
    """剥掉亚马逊图片 URL 的尺寸后缀取原图。

    覆盖两种形态：.../I/x._AC_SL1500_.jpg 和 .../I/x.jpg._AC_SL1500_.jpg -> .../I/x.jpg
    """
    return re.sub(
        r"(\._[^/]+_)+\.(jpg|jpeg|png)$",
        r".\2",
        image_url,
        flags=re.IGNORECASE,
    )


class ProductFetcherSession:
    """可复用的抓取会话：启动一次 Edge，连续抓取多个商品。"""

    def __init__(
        self,
        marketplace: str = DEFAULT_MARKETPLACE,
        headless: bool = True,
        log_callback: Optional[Callable[[str], None]] = None,
    ):
        self.marketplace = marketplace
        self.headless = headless
        self._log_callback = log_callback
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    def _log(self, message: str) -> None:
        if self._log_callback:
            self._log_callback(message)

    def start(self) -> "ProductFetcherSession":
        if self._page is not None:
            return self
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise ProductFetchError("缺少 Playwright。请执行：pip install -r requirements.txt") from exc

        locale, lc_main, currency = MARKETPLACE_LOCALES.get(
            self.marketplace, MARKETPLACE_LOCALES[DEFAULT_MARKETPLACE])
        base_url = MARKETPLACES.get(self.marketplace, MARKETPLACES[DEFAULT_MARKETPLACE])
        domain = "." + urlparse(base_url).netloc

        self._playwright = sync_playwright().start()
        try:
            self._browser = self._playwright.chromium.launch(
                channel=PLAYWRIGHT_BROWSER_CHANNEL,
                headless=self.headless,
                timeout=30_000,
            )
            self._context = self._browser.new_context(locale=locale)
            self._context.set_default_timeout(15_000)
            self._context.set_default_navigation_timeout(PAGE_LOAD_TIMEOUT * 1000)
            self._context.add_cookies([
                {"name": "lc-main", "value": lc_main, "domain": domain, "path": "/"},
                {"name": "i18n-prefs", "value": currency, "domain": domain, "path": "/"},
            ])
            self._page = self._context.new_page()
        except Exception as exc:
            self.close()
            raise ProductFetchError(f"无法启动系统 Edge：{exc}") from exc
        self._log("[初始化] Playwright 已连接系统 Edge（无头）" if self.headless
                  else "[初始化] Playwright 已连接系统 Edge")
        return self

    def fetch(self, asin_or_url: str) -> Dict[str, Any]:
        """抓取单个商品的标题、五点描述和主副图 URL 列表。"""
        self.start()
        asin, url = resolve_asin_and_url(asin_or_url, self.marketplace)
        self._log(f"[抓取] 打开商品页 {url}")
        try:
            self._page.goto(url, wait_until="domcontentloaded")
            self._page.wait_for_selector(
                "#productTitle, #feature-bullets, #imageBlock", timeout=20_000)
            data = self._page.evaluate(EXTRACT_JS)
        except ProductFetchError:
            raise
        except Exception as exc:
            raise ProductFetchError(f"商品页加载失败：{exc}") from exc

        if data.get("captcha"):
            raise ProductFetchError("遇到亚马逊验证码页，请稍后重试。")
        if not data.get("title") and not data.get("images"):
            raise ProductFetchError("页面结构异常，未找到标题和图片，可能商品已下架。")

        images: List[str] = []
        for raw in data.get("images", []):
            normalized = normalize_amazon_image_url(raw)
            if normalized not in images:
                images.append(normalized)
        result = {
            "asin": asin,
            "url": data.get("finalUrl") or url,
            "title": data.get("title", ""),
            "bullets": data.get("bullets", []),
            "images": images,
        }
        self._log(f"[抓取] 完成：五点 {len(result['bullets'])} 条，图片 {len(images)} 张")
        return result

    def close(self) -> None:
        page, context, browser, playwright = (
            self._page, self._context, self._browser, self._playwright)
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        for label, resource, method in (
            ("页面", page, "close"),
            ("上下文", context, "close"),
            ("浏览器", browser, "close"),
            ("Playwright", playwright, "stop"),
        ):
            if resource is None:
                continue
            try:
                getattr(resource, method)()
            except Exception as exc:
                self._log(f"[警告] {label}清理失败：{exc}")

    def __enter__(self) -> "ProductFetcherSession":
        return self.start()

    def __exit__(self, *exc_info) -> None:
        self.close()


def fetch_product_details(
    asin_or_url: str,
    marketplace: str = DEFAULT_MARKETPLACE,
    headless: bool = True,
    log_callback: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """一次性抓取单个商品（内部启动并关闭一个会话）。"""
    with ProductFetcherSession(marketplace, headless, log_callback) as session:
        return session.fetch(asin_or_url)


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else ""
    if not target:
        print("用法：python -m core.reviews.product_fetcher <ASIN或商品链接> [--headed]")
        sys.exit(1)
    fetched = fetch_product_details(
        target,
        headless="--headed" not in sys.argv,
        log_callback=print,
    )
    print(json.dumps(fetched, ensure_ascii=False, indent=2))
