"""Amazon 评论采集器（Playwright + 系统 Microsoft Edge）。

Playwright 直接控制系统 Edge，不再依赖 msedgedriver.exe。浏览器登录状态保存
在当前用户的 LocalAppData 专用目录。采集器只负责获取原始评论；标准化、去重
和同步由 review_normalizer / ReviewStore / ReviewRepository 负责。
"""

from __future__ import annotations

import os
import random
import re
import sys
import time
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from .config import (
    BROWSER_USER_DATA_DIR,
    CLICK_DELAY_MAX,
    CLICK_DELAY_MIN,
    DEBUG_DIR,
    DEBUG_SAVE_PAGE,
    DEFAULT_MARKETPLACE,
    LOAD_MORE_DELAY_MAX,
    LOAD_MORE_DELAY_MIN,
    MARKETPLACES,
    MAX_DELAY,
    MAX_REVIEW_PAGES,
    MAX_REVIEWS_PER_STAR,
    MIN_DELAY,
    PAGE_LOAD_TIMEOUT,
    PLAYWRIGHT_BROWSER_CHANNEL,
    STAR_FILTER_MAP,
    STAR_LEVELS,
)
from .normalizer import extract_asin, extract_review_id


class ScrapeError(RuntimeError):
    """页面加载、登录、验证或页面结构导致采集结果不可信。"""


class CollectionCancelled(RuntimeError):
    """Raised when the user cooperatively cancels a collection task."""


class AmazonReviewScraper:
    """基于 Playwright 的 Amazon 评论采集器。"""

    def __init__(
        self,
        marketplace: Optional[str] = None,
        headless: bool = False,
        *,
        should_stop: Optional[Callable[[], bool]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
    ):
        self.marketplace = marketplace or DEFAULT_MARKETPLACE
        self.base_url = MARKETPLACES.get(self.marketplace, MARKETPLACES[DEFAULT_MARKETPLACE])
        self.headless = headless
        self.playwright = None
        self.context = None
        self.page = None
        self.last_warnings: List[str] = []
        self.last_product_title = "未知商品"
        self.last_product_categories: List[Dict[str, Any]] = []
        self._timeout_error = Exception
        self._should_stop = should_stop or (lambda: False)
        self._log_callback = log_callback

    def _log(self, *parts: Any) -> None:
        message = " ".join(str(part) for part in parts)
        if self._log_callback:
            self._log_callback(message)

    def _check_cancelled(self) -> None:
        if self._should_stop():
            raise CollectionCancelled("用户已停止评论采集")

    def _interruptible_sleep(self, seconds: float) -> None:
        deadline = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < deadline:
            self._check_cancelled()
            time.sleep(min(0.2, max(0.0, deadline - time.monotonic())))

    def _init_driver(self) -> None:
        """兼容旧方法名：启动 Playwright persistent context。"""
        self._check_cancelled()
        if self.context is not None:
            return
        if sys.version_info < (3, 12):
            raise ScrapeError(
                "评论采集需要 Python 3.12 或更新版本。请使用 start-pm-stack.bat 启动；"
                "如果使用 EXE，请安装用新环境重新打包的版本。"
            )
        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "缺少 Playwright。请执行：pip install -r requirements.txt"
            ) from exc

        os.makedirs(BROWSER_USER_DATA_DIR, exist_ok=True)
        self._timeout_error = PlaywrightTimeoutError
        try:
            self.playwright = sync_playwright().start()
            self.context = self.playwright.chromium.launch_persistent_context(
                user_data_dir=BROWSER_USER_DATA_DIR,
                channel=PLAYWRIGHT_BROWSER_CHANNEL,
                headless=self.headless,
                timeout=30_000,
                no_viewport=True,
                args=["--start-maximized"],
                locale=self._locale_for_marketplace(),
            )
        except Exception as exc:
            self.close()
            message = str(exc)
            if "user data directory" in message.lower() or "processsingleton" in message.lower():
                raise ScrapeError(
                    "PM Stack 的 Edge 登录目录正在被占用。请关闭程序打开的 Edge 后重试。"
                ) from exc
            raise ScrapeError(
                "无法启动系统 Microsoft Edge。请关闭之前由采集器打开的 Edge 后重试，"
                "并确认 Edge 已安装。浏览器目录：" + BROWSER_USER_DATA_DIR
                + "。原始错误：" + message
            ) from exc

        self.context.set_default_timeout(15_000)
        self.context.set_default_navigation_timeout(PAGE_LOAD_TIMEOUT * 1000)
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self._log("[初始化] Playwright 已连接系统 Microsoft Edge")
        self._log(f"[初始化] 浏览器登录目录: {BROWSER_USER_DATA_DIR}")

    def _locale_for_marketplace(self) -> str:
        return {
            "amazon.de": "de-DE",
            "amazon.co.uk": "en-GB",
            "amazon.com": "en-US",
            "amazon.co.jp": "ja-JP",
            "amazon.com.au": "en-AU",
        }.get(self.marketplace, "en-US")

    def close(self) -> None:
        context, playwright = self.context, self.playwright
        self.context = None
        self.page = None
        self.playwright = None
        # Attempt both cleanup steps; never hide the original scrape error.
        for label, resource, method in (
            ("浏览器", context, "close"),
            ("Playwright", playwright, "stop"),
        ):
            if resource is None:
                continue
            try:
                getattr(resource, method)()
            except Exception as exc:
                self._log(f"[警告] {label}清理失败：{exc}")
        if context is not None or playwright is not None:
            self._log("[关闭] 浏览器资源清理结束")

    def __enter__(self):
        self._init_driver()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _random_delay(self, min_delay: Optional[float] = None, max_delay: Optional[float] = None):
        lower = MIN_DELAY if min_delay is None else min_delay
        upper = MAX_DELAY if max_delay is None else max_delay
        delay = random.uniform(lower, upper)
        self._log(f"  等待 {delay:.1f} 秒...")
        self._interruptible_sleep(delay)

    def _goto(self, url: str, *, label: str = "页面") -> None:
        self._check_cancelled()
        try:
            self.page.goto(url, wait_until="domcontentloaded")
            try:
                self.page.wait_for_load_state("networkidle", timeout=5_000)
            except self._timeout_error:
                pass
        except self._timeout_error as exc:
            raise ScrapeError(f"{label}加载超时：{url}") from exc
        except Exception as exc:
            raise ScrapeError(f"{label}加载失败：{exc}") from exc

    def _body_text(self) -> str:
        try:
            return self.page.locator("body").inner_text(timeout=3_000).lower()
        except Exception:
            return ""

    def _is_captcha(self) -> bool:
        selectors = (
            "form[action*='validateCaptcha']",
            "img[src*='captcha']",
            "#captchacharacters",
            "input[name='cvf_captcha_input']",
        )
        for selector in selectors:
            try:
                locator = self.page.locator(selector)
                if locator.count() and locator.first.is_visible():
                    return True
            except Exception:
                continue
        texts = (
            "enter the characters you see below",
            "type the characters you see in this image",
            "geben sie die zeichen ein",
            "zeichen in diesem bild",
            "画像に表示されている文字を入力",
            "文字を入力してください",
        )
        body = self._body_text()
        return any(text in body for text in texts)

    def _is_signin_page(self) -> bool:
        try:
            current_url = (self.page.url or "").lower()
            if "/ap/signin" in current_url or "openid.mode=checkid_setup" in current_url:
                return True
            for selector in (
                "form[name='signIn']", "#ap_email", "input[name='email']",
            ):
                locator = self.page.locator(selector)
                if locator.count() and locator.first.is_visible():
                    return True
        except Exception:
            return False
        return False

    def _check_signin(self) -> None:
        if not self._is_signin_page():
            return
        if self.headless:
            raise ScrapeError(
                "Amazon 评论页要求登录。请关闭无头模式，在弹出的 Edge 中完成一次登录。"
            )

        self._log("\n" + "!" * 60)
        self._log("[登录] Amazon 评论页要求登录，请在 Edge 中完成，程序最多等待 5 分钟。")
        self._log("!" * 60)
        deadline = time.time() + 300
        while time.time() < deadline:
            self._interruptible_sleep(2)
            if self._is_captcha():
                self._check_captcha()
            if not self._is_signin_page():
                try:
                    self.page.wait_for_load_state("domcontentloaded", timeout=5_000)
                except self._timeout_error:
                    pass
                self._log("[登录] 登录完成，继续采集")
                return
        raise ScrapeError("等待 Amazon 登录超时")

    def _check_captcha(self) -> bool:
        if not self._is_captcha():
            return True
        if self.headless:
            raise ScrapeError("无头模式遇到验证码，无法人工处理。请关闭无头模式后重试。")

        self._log("\n" + "!" * 60)
        self._log("[验证码] 请在 Edge 中手动完成验证，程序最多等待 5 分钟。")
        self._log("!" * 60)
        deadline = time.time() + 300
        while time.time() < deadline:
            self._interruptible_sleep(2)
            if not self._is_captcha():
                self._log("[验证码] 验证已通过，继续采集")
                return True
        raise ScrapeError("等待验证码超时")

    def _debug_review_page(self, label: str = "debug") -> None:
        self._log(f"[调试] {label} | URL: {self.page.url if self.page else '-'}")
        if not DEBUG_SAVE_PAGE or not self.page:
            return
        try:
            os.makedirs(DEBUG_DIR, exist_ok=True)
            safe_label = re.sub(r"[^0-9A-Za-z_-]+", "_", label)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            html_path = os.path.join(DEBUG_DIR, f"debug_{safe_label}_{timestamp}.html")
            png_path = os.path.join(DEBUG_DIR, f"debug_{safe_label}_{timestamp}.png")
            with open(html_path, "w", encoding="utf-8") as stream:
                stream.write(self.page.content())
            self.page.screenshot(path=png_path, full_page=True)
            self._log(f"[调试] 已保存: {html_path}")
            self._log(f"[调试] 已保存: {png_path}")
        except Exception as exc:
            self._log(f"[调试] 保存页面失败: {exc}")

    def _load_product_page(self, asin: str) -> None:
        url = f"{self.base_url}/dp/{asin}"
        self._log(f"  [商品页] 访问: {url}")
        self._goto(url, label="商品页")
        self._check_captcha()

    def _parse_product_title(self) -> str:
        for selector in (
            "#productTitle",
            "a[data-hook='product-link']",
            ".product-title-word-break",
            "h1",
        ):
            try:
                locator = self.page.locator(selector).first
                text = locator.inner_text(timeout=2_000).strip()
                if text:
                    return text
            except Exception:
                continue
        return "未知商品"

    @staticmethod
    def _category_id_from_href(href: str) -> str:
        parsed = urlparse(unquote(str(href or "")))
        query = parse_qs(parsed.query)
        node_values = query.get("node") or []
        if node_values and re.fullmatch(r"\d+", node_values[0]):
            return node_values[0]
        for value in query.get("rh") or []:
            matches = re.findall(r"(?:^|[,;:])n:(\d+)", value)
            if matches:
                return matches[-1]
        match = re.search(r"/(?:b|browse)/[^/?#]*/(\d{4,})(?:[/?#]|$)", parsed.path)
        return match.group(1) if match else ""

    def _parse_product_categories(self) -> List[Dict[str, Any]]:
        selectors = (
            "#wayfinding-breadcrumbs_feature_div a",
            "#wayfinding-breadcrumbs_container a",
        )
        nodes: List[Dict[str, str]] = []
        for selector in selectors:
            try:
                anchors = self.page.locator(selector)
                for index in range(min(anchors.count(), 20)):
                    anchor = anchors.nth(index)
                    name = anchor.inner_text(timeout=1_000).strip()
                    href = anchor.get_attribute("href") or ""
                    if not name:
                        continue
                    node = {"id": self._category_id_from_href(href), "name": name}
                    if node not in nodes:
                        nodes.append(node)
                if nodes:
                    break
            except Exception:
                continue
        if not nodes:
            return []
        leaf = nodes[-1]
        return [{
            "category_id": leaf["id"],
            "category_name": leaf["name"],
            "category_path": nodes,
            "is_primary": True,
            "source": "breadcrumb",
        }]

    def _click_more_reviews_from_product_page(self, asin: str) -> bool:
        self._load_product_page(asin)
        self.last_product_title = self._parse_product_title()
        self.last_product_categories = self._parse_product_categories()
        if self.last_product_categories:
            self._log(f"  [类目] {self.last_product_categories[0]['category_name']}")
        self._random_delay(1.0, 2.0)
        selectors = (
            "a[data-hook='see-all-reviews-link-foot']",
            "a[data-hook='see-all-reviews-link']",
            "a[href*='/product-reviews/']",
        )
        for selector in selectors:
            try:
                candidates = self.page.locator(selector)
                for index in range(min(candidates.count(), 10)):
                    candidate = candidates.nth(index)
                    href = candidate.get_attribute("href") or ""
                    if "/product-reviews/" not in href:
                        continue
                    candidate.scroll_into_view_if_needed()
                    self._interruptible_sleep(random.uniform(CLICK_DELAY_MIN, CLICK_DELAY_MAX))
                    candidate.click()
                    self.page.wait_for_load_state("domcontentloaded")
                    self._check_captcha()
                    self._check_signin()
                    return True
            except CollectionCancelled:
                raise
            except Exception:
                continue

        fallback_url = self.get_reviews_url(asin, page=1)
        self._log("  [提示] 未找到评论入口，使用评论 URL")
        self._goto(fallback_url, label="评论页")
        self._check_captcha()
        self._check_signin()
        return True

    def get_reviews_url(
        self,
        asin: str,
        page: int = 1,
        sort_by: str = "recent",
        star_filter: Optional[str] = None,
    ) -> str:
        sort_param = "recent" if sort_by == "recent" else "helpful"
        url = (
            f"{self.base_url}/product-reviews/{asin}"
            f"/ref=cm_cr_arp_d_viewopt_srt?reviewerType=all_reviews"
            f"&sortBy={sort_param}&pageNumber={int(page)}"
        )
        if star_filter:
            url += f"&filterByStar={star_filter}"
        return url

    def _goto_review_filter(
        self,
        asin: str,
        *,
        page: int = 1,
        sort_by: str = "recent",
        star: Optional[int] = None,
    ) -> None:
        star_filter = STAR_FILTER_MAP[star] if star else None
        url = self.get_reviews_url(asin, page=page, sort_by=sort_by, star_filter=star_filter)
        self._goto(url, label="评论筛选页")
        self._check_captcha()
        self._check_signin()

    def _page_is_known_empty(self) -> bool:
        body = self._body_text()
        empty_texts = (
            "no customer reviews",
            "no reviews",
            "there are 0 reviews",
            "keine kundenrezensionen",
            "keine rezensionen",
            "まだカスタマーレビューはありません",
            "レビューはまだありません",
        )
        return any(text in body for text in empty_texts)

    def _wait_for_reviews_loaded(self, timeout: float = 20) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._count_review_cards() > 0 or self._page_is_known_empty():
                return True
            if self._is_captcha():
                self._check_captcha()
            self._interruptible_sleep(0.4)
        return False

    def _count_review_cards(self) -> int:
        try:
            return int(
                self.page.evaluate(
                    """
                    () => {
                      const cards = document.querySelectorAll(
                        'div[data-hook="review"], div[id^="customer_review-"]'
                      );
                      return new Set(Array.from(cards)).size;
                    }
                    """
                )
                or 0
            )
        except Exception:
            return 0

    def _parse_reviews_on_page(
        self,
        asin: str,
        product_title: str = "",
        target_star: Optional[int] = None,
        page_number: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        raw_reviews = self.page.evaluate(
            """
            () => {
              const result = [];
              const seenNodes = new Set();
              const cards = document.querySelectorAll(
                'div[data-hook="review"], div[id^="customer_review-"]'
              );
              for (const card of cards) {
                if (seenNodes.has(card)) continue;
                seenNodes.add(card);
                const body = card.querySelector('[data-hook="review-body"]');
                const title = card.querySelector('[data-hook="review-title"]');
                const date = card.querySelector('[data-hook="review-date"]');
                if (!body && !title && !date) continue;
                const text = (selector) => {
                  const el = card.querySelector(selector);
                  return el ? (el.textContent || '').trim() : '';
                };
                const ratingEl = card.querySelector('i[data-hook="review-star-rating"] span')
                  || card.querySelector('i[data-hook="cmps-review-star-rating"] span')
                  || card.querySelector('span.a-icon-alt');
                const titleEl = card.querySelector('a[data-hook="review-title"]')
                  || card.querySelector('span[data-hook="review-title"]')
                  || card.querySelector('[data-hook="review-title"]');
                const linkEl = card.querySelector('a[data-hook="review-title"]')
                  || card.querySelector('a[data-hook="review-title-inflation"]');
                const images = [];
                for (const image of card.querySelectorAll(
                  'img[data-hook="review-image-tile"], '
                  + 'div[data-hook="review-image-tile-section"] img, '
                  + '.review-image-tile-section img'
                )) {
                  const src = image.src || image.getAttribute('data-src') || '';
                  if (src.includes('media-amazon.com/images')
                      && !src.toLowerCase().includes('profile')
                      && !src.toLowerCase().includes('avatar')
                      && !images.includes(src)) images.push(src);
                }
                result.push({
                  element_id: card.id || '',
                  reviewer_name: text('.a-profile-name'),
                  rating_text: ratingEl ? (ratingEl.textContent || '').trim() : '',
                  title_raw: titleEl ? (titleEl.textContent || '').trim() : '',
                  date: text('span[data-hook="review-date"]'),
                  verified_purchase: Boolean(card.querySelector('[data-hook="avp-badge"]')),
                  helpful_text: text('[data-hook="helpful-vote-statement"]'),
                  content: body ? (body.textContent || '').trim() : '',
                  review_href: linkEl ? (linkEl.getAttribute('href') || '') : '',
                  image_urls: images,
                });
              }
              return result;
            }
            """
        ) or []

        reviews: List[Dict[str, Any]] = []
        for raw in raw_reviews:
            rating_text = raw.get("rating_text", "")
            match = re.search(r"(\d+(?:[.,]\d+)?)", rating_text)
            rating = float(match.group(1).replace(",", ".")) if match else None
            title = str(raw.get("title_raw") or "").strip()
            if rating_text and title.startswith(rating_text):
                title = title[len(rating_text):].strip()
            href = raw.get("review_href") or ""
            review_url = urljoin(self.base_url, href) if href else ""
            reviews.append(
                {
                    "asin": asin,
                    "product_title": product_title,
                    "star_filter": f"{target_star} star" if target_star else "",
                    "page_number": page_number,
                    "element_id": raw.get("element_id", ""),
                    "review_id": extract_review_id(raw.get("element_id", ""), review_url),
                    "reviewer_name": raw.get("reviewer_name") or "匿名用户",
                    "rating": rating,
                    "title": title,
                    "date": raw.get("date", ""),
                    "verified_purchase": bool(raw.get("verified_purchase")),
                    "helpful_votes": raw.get("helpful_text", ""),
                    "content": raw.get("content", ""),
                    "review_url": review_url,
                    "review_image_count": len(raw.get("image_urls") or []),
                    "review_image_urls": " | ".join(raw.get("image_urls") or []),
                    "image_urls": raw.get("image_urls") or [],
                }
            )
        self._log(f"  [解析] 当前页面识别到 {len(reviews)} 条评论")
        return reviews

    @staticmethod
    def _review_key(review: Dict[str, Any]) -> str:
        return review.get("review_id") or "|".join(
            [
                str(review.get("reviewer_name", "")),
                str(review.get("date", "")),
                str(review.get("rating", "")),
                str(review.get("title", "")),
                str(review.get("content", "")),
            ]
        )

    def _dedupe_reviews(self, reviews: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        seen = set()
        result = []
        for review in reviews:
            key = self._review_key(review)
            if key in seen:
                continue
            seen.add(key)
            result.append(review)
        return result

    def _click_load_more(self) -> bool:
        selectors = (
            "button[data-hook='load-more-review-button']",
            "input[data-hook='load-more-review-button']",
            "a[data-hook='load-more-review-button']",
        )
        for selector in selectors:
            try:
                locator = self.page.locator(selector).first
                if locator.count() and locator.is_visible() and locator.is_enabled():
                    locator.scroll_into_view_if_needed()
                    locator.click()
                    return True
            except Exception:
                continue

        tokens = (
            "more", "weitere", "mehr", "もっと", "さらに", "レビューを表示",
            "afficher", "voir", "mostrar", "altre", "mais",
        )
        candidates = self.page.locator("a.a-button-text, button, input[type='submit']")
        try:
            count = min(candidates.count(), 80)
        except Exception:
            return False
        for index in range(count):
            candidate = candidates.nth(index)
            try:
                text = (
                    candidate.inner_text(timeout=500)
                    or candidate.get_attribute("value")
                    or candidate.get_attribute("aria-label")
                    or ""
                ).strip().lower()
                if not any(token in text for token in tokens):
                    continue
                if not candidate.is_visible() or not candidate.is_enabled():
                    continue
                candidate.scroll_into_view_if_needed()
                candidate.click()
                return True
            except Exception:
                continue
        return False

    def _find_and_click_load_more_button(self) -> bool:
        """兼容旧调试入口。"""
        return self._click_load_more()

    def _known_tail(self, reviews: List[Dict[str, Any]], known_ids: set) -> int:
        count = 0
        for review in reversed(reviews):
            review_id = review.get("review_id")
            if review_id and review_id in known_ids:
                count += 1
            else:
                break
        return count

    def _scrape_review_batches(
        self,
        asin: str,
        product_title: str,
        *,
        max_pages: int,
        max_reviews: int,
        sort_by: str,
        star: Optional[int] = None,
        known_ids: Optional[set] = None,
        known_stop_streak: int = 10,
    ) -> List[Dict[str, Any]]:
        collected: List[Dict[str, Any]] = []
        seen = set()
        for batch in range(1, max(1, int(max_pages)) + 1):
            self._check_cancelled()
            if not self._wait_for_reviews_loaded(timeout=15):
                self._debug_review_page(f"reviews_batch_{batch}_timeout")
                raise ScrapeError(f"第 {batch} 批评论加载超时")

            current = self._parse_reviews_on_page(
                asin, product_title=product_title, target_star=star, page_number=batch
            )
            if not current:
                if self._page_is_known_empty():
                    break
                self._debug_review_page(f"reviews_batch_{batch}_empty")
                raise ScrapeError(f"第 {batch} 批页面存在，但未识别到评论卡片")

            added = 0
            for review in current:
                key = self._review_key(review)
                if key in seen:
                    continue
                seen.add(key)
                collected.append(review)
                added += 1
            self._log(f"  [采集] 第 {batch} 批新增 {added} 条，累计 {len(collected)} 条")

            if known_ids and self._known_tail(current, known_ids) >= known_stop_streak:
                self._log("  [增量] 已连续进入历史采集区域，提前停止")
                break
            if len(collected) >= max_reviews:
                break
            if batch >= max_pages:
                break

            before = self._count_review_cards()
            clicked = self._click_load_more()
            if clicked:
                self._interruptible_sleep(random.uniform(LOAD_MORE_DELAY_MIN, LOAD_MORE_DELAY_MAX))
                deadline = time.time() + 10
                while time.time() < deadline and self._count_review_cards() <= before:
                    self._interruptible_sleep(0.4)
                if self._count_review_cards() > before:
                    continue
                self._log("  [加载更多] 点击后评论数量未增加，改用分页 URL")

            # 页面没有加载更多按钮或按钮失效时，自动回退到 pageNumber。
            self._goto_review_filter(asin, page=batch + 1, sort_by=sort_by, star=star)
            self._random_delay(0.8, 1.5)

        result = self._dedupe_reviews(collected)[:max_reviews]
        return result

    def scrape_reviews_by_star(
        self,
        asin: str,
        max_pages: Optional[int] = None,
        max_reviews_per_star: Optional[int] = None,
        sort_by: str = "recent",
        known_ids: Optional[set] = None,
    ):
        asin = extract_asin(asin)
        if not re.fullmatch(r"[A-Z0-9]{10}", asin):
            raise ValueError(f"ASIN 无效：{asin}")
        max_pages = max_pages or MAX_REVIEW_PAGES
        max_reviews_per_star = max_reviews_per_star or MAX_REVIEWS_PER_STAR
        self._init_driver()
        self.last_warnings = []

        self._log(f"\n{'=' * 60}")
        self._log(f"开始按星级采集 - {self.marketplace} / {asin}")
        self._log(f"{'=' * 60}")
        self._click_more_reviews_from_product_page(asin)
        product_title = self.last_product_title
        star_reviews: Dict[int, List[Dict[str, Any]]] = {}
        failed_stars = 0

        for star in STAR_LEVELS:
            self._check_cancelled()
            try:
                self._log(f"\n[星级] {star} star")
                self._goto_review_filter(asin, page=1, sort_by=sort_by, star=star)
                reviews = self._scrape_review_batches(
                    asin,
                    product_title,
                    max_pages=max_pages,
                    max_reviews=max_reviews_per_star,
                    sort_by=sort_by,
                    star=star,
                    known_ids=known_ids,
                )
                star_reviews[star] = reviews
                self._log(f"[完成] {star} star：{len(reviews)} 条")
            except ScrapeError as exc:
                failed_stars += 1
                warning = f"{star} star 采集失败：{exc}"
                self.last_warnings.append(warning)
                star_reviews[star] = []
                self._log(f"[警告] {warning}")

        if failed_stars == len(STAR_LEVELS):
            raise ScrapeError("所有星级均采集失败，请检查登录状态、验证码或页面结构")
        return product_title, star_reviews

    def scrape_multiple_products_by_star(
        self,
        asin_list: Iterable[str],
        max_pages: Optional[int] = None,
        max_reviews_per_star: Optional[int] = None,
        sort_by: str = "recent",
        delay_between_products: bool = True,
    ):
        asin_list = list(asin_list)
        results = {}
        self._init_driver()
        for index, asin in enumerate(asin_list, 1):
            self._check_cancelled()
            self._log(f"\n>>> 进度: {index}/{len(asin_list)}")
            normalized_asin = extract_asin(asin)
            results[normalized_asin] = self.scrape_reviews_by_star(
                normalized_asin,
                max_pages=max_pages,
                max_reviews_per_star=max_reviews_per_star,
                sort_by=sort_by,
            )
            if delay_between_products and index < len(asin_list):
                self._random_delay(10, 20)
        return results

    def scrape_reviews(
        self,
        asin: str,
        max_pages: Optional[int] = None,
        sort_by: str = "recent",
        known_ids: Optional[set] = None,
    ):
        asin = extract_asin(asin)
        if not re.fullmatch(r"[A-Z0-9]{10}", asin):
            raise ValueError(f"ASIN 无效：{asin}")
        max_pages = max_pages or MAX_REVIEW_PAGES
        self._init_driver()
        self.last_warnings = []
        self._click_more_reviews_from_product_page(asin)
        product_title = self.last_product_title
        self._goto_review_filter(asin, page=1, sort_by=sort_by)
        reviews = self._scrape_review_batches(
            asin,
            product_title,
            max_pages=max_pages,
            max_reviews=max_pages * 100,
            sort_by=sort_by,
            known_ids=known_ids,
        )
        return product_title, reviews

    def scrape_multiple_products(
        self,
        asin_list: Iterable[str],
        max_pages: Optional[int] = None,
        sort_by: str = "recent",
        delay_between_products: bool = True,
    ):
        asin_list = list(asin_list)
        results = {}
        self._init_driver()
        for index, asin in enumerate(asin_list, 1):
            normalized_asin = extract_asin(asin)
            results[normalized_asin] = self.scrape_reviews(
                normalized_asin, max_pages=max_pages, sort_by=sort_by
            )
            if delay_between_products and index < len(asin_list):
                self._random_delay(10, 20)
        return results


__all__ = ["AmazonReviewScraper", "ScrapeError"]
