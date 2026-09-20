"""Opt-in browser integration test: isolated profile, synthetic pages and temporary DB only."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_browser_dir = ROOT / ".runtime-local" / "browsers"
_browser_dir.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(_browser_dir))
from playwright.sync_api import sync_playwright, expect
from core.reviews.extension_bridge import ExtensionBridge
from core.reviews.store import ReviewStore

HTML = """<html><body><a data-hook="product-link">Synthetic product</a>
<div data-hook="review" id="customer_review-RTEST0001">
<i data-hook="review-star-rating"><span>5.0 out of 5 stars</span></i>
<span data-hook="review-title">Test</span><span class="a-profile-name">Test user</span>
<span data-hook="review-date">Reviewed in the United States on September 1, 2026</span>
<span data-hook="review-body">Synthetic browser integration fixture</span>
</div></body></html>"""

def main():
    with tempfile.TemporaryDirectory(prefix="pm-extension-test-") as directory:
        db = str(Path(directory) / "reviews.db")
        bridge = ExtensionBridge(db)
        bridge.start()
        try:
            with sync_playwright() as playwright:
                extension = str(ROOT / "browser-extension")
                context = playwright.chromium.launch_persistent_context(
                    str(Path(directory) / "browser"), channel="chromium", headless=True,
                    args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"])
                try:
                    worker = context.service_workers[0] if context.service_workers else context.wait_for_event("serviceworker")
                    extension_id = worker.url.split("/")[2]
                    popup = context.new_page()
                    popup.goto(f"chrome-extension://{extension_id}/popup.html")
                    popup.locator("#token").fill(bridge.token)
                    popup.locator("#connect").click()
                    expect(popup.locator("#status")).to_contain_text("已连接", timeout=15000)
                    assert bridge.snapshot()["connected"]
                    cookie_seen = []
                    def fixture(route):
                        cookie_seen.append("pm_test_loggedin=yes" in route.request.headers.get("cookie", ""))
                        route.fulfill(status=200, content_type="text/html", body=HTML)
                    context.route("https://www.amazon.com/**", fixture)
                    context.add_cookies([{"name":"pm_test_loggedin","value":"yes",
                                         "domain":"www.amazon.com","path":"/","secure":True}])
                    def collect():
                        bridge.submit("B0DDG2KQQ9", "amazon.com")
                        deadline = time.monotonic() + 35
                        while time.monotonic() < deadline:
                            popup.locator("#check").click()
                            popup.wait_for_timeout(500)
                            snapshot = bridge.snapshot()["job"]
                            if snapshot["status"] in ("done", "error"):
                                assert snapshot["status"] == "done", snapshot
                                return snapshot
                        raise AssertionError(bridge.snapshot())
                    first, second = collect(), collect()
                    assert first["new"] == 1 and second["duplicates"] == 1
                    assert cookie_seen and all(cookie_seen), "Browser's existing session was not reused"
                    # An authenticated-looking login page must never be saved as reviews.
                    context.unroute("https://www.amazon.com/**")
                    context.route("https://www.amazon.com/**", lambda route: route.fulfill(
                        content_type="text/html", body='<input id="ap_email"><h1>Sign in</h1>'))
                    bridge.submit("B0DDG2KQQ9", "amazon.com")
                    for _ in range(30):
                        popup.locator("#check").click()
                        popup.wait_for_timeout(300)
                        if bridge.snapshot()["job"]["status"] == "waiting":
                            break
                    assert bridge.snapshot()["job"]["status"] == "waiting"
                    # User completes login in the same tab; the extension resumes the task.
                    context.unroute("https://www.amazon.com/**")
                    context.route("https://www.amazon.com/**", fixture)
                    active = worker.evaluate("chrome.storage.session.get('active')")
                    tabs = [p for p in context.pages if "amazon.com" in p.url]
                    assert tabs and active["active"]
                    for tab in tabs:
                        tab.goto(bridge.snapshot()["job"]["url"])
                    for _ in range(30):
                        popup.locator("#check").click()
                        popup.wait_for_timeout(300)
                        if bridge.snapshot()["job"]["status"] == "done":
                            break
                    assert bridge.snapshot()["job"]["status"] == "done"
                    store = ReviewStore(db)
                    try: assert store.total_reviews() == 1
                    finally: store.close()
                    popup.locator("#check").click()
                    expect(popup.locator("#status")).to_contain_text("重复", timeout=5000)
                    popup.set_viewport_size({"width":370,"height":440})
                    popup.screenshot(path=str(_browser_dir.parent / "extension-popup.png"))
                    result = {"extension_loaded":True,"pairing":True,"same_browser_session":True,
                              "page_to_sqlite":True,"deduplication":True,"login_pause_resume":True,
                              "real_amazon_reviews":False}
                    (_browser_dir.parent / "extension-browser-result.json").write_text(
                        json.dumps(result, indent=2), encoding="utf-8")
                    print(json.dumps(result))
                finally:
                    context.close()
        finally:
            bridge.stop()

if __name__ == "__main__":
    main()
