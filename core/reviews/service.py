"""Collection orchestration shared by the PyQt UI and tests."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Tuple

from .normalizer import normalize_reviews, utc_now
from .scraper import CollectionCancelled


LogCallback = Optional[Callable[[str], None]]


def _log(callback: LogCallback, message: str) -> None:
    if callback:
        callback(message)


def collect_product(
    store,
    scraper,
    asin: str,
    marketplace: str,
    pages: int,
    max_per_star: int,
    incremental: bool,
    *,
    mode: str = "star",
    repository=None,
    log_callback: LogCallback = None,
) -> Tuple[int, int]:
    """Scrape one product, commit locally, and opportunistically sync it."""
    known_ids = store.known_review_ids(asin, marketplace) if incremental else None
    if incremental:
        _log(log_callback, f"[增量] {asin} 本地已有 {len(known_ids)} 条关联评论")

    started = utc_now()
    try:
        if mode == "flat":
            title, raw_reviews = scraper.scrape_reviews(
                asin, max_pages=pages, sort_by="recent", known_ids=known_ids,
            )
        else:
            title, by_star = scraper.scrape_reviews_by_star(
                asin,
                max_pages=pages,
                max_reviews_per_star=max_per_star,
                known_ids=known_ids,
            )
            raw_reviews = [
                review
                for star in sorted(by_star, reverse=True)
                for review in (by_star.get(star) or [])
            ]
    except CollectionCancelled:
        raise
    except Exception as exc:
        finished = utc_now()
        run = {
            "started_at": started,
            "finished_at": finished,
            "new_reviews": 0,
            "duplicate_reviews": 0,
            "status": "failed",
            "error": str(exc),
        }
        try:
            store.upsert_product(asin, marketplace)
            store.log_run(asin, marketplace, 0, 0, "failed", str(exc), started)
            store.enqueue_collection(asin, marketplace, "", [], run=run)
            if repository:
                repository.sync_pending()
        except Exception as record_error:
            _log(log_callback, f"[警告] 保存或同步失败记录时出错：{record_error}")
        raise

    normalized = normalize_reviews(asin, marketplace, raw_reviews)
    parent_asin = next((r["parent_asin"] for r in normalized if r["parent_asin"]), "")
    categories = list(getattr(scraper, "last_product_categories", []) or [])
    store.upsert_product(
        asin,
        marketplace,
        title=title,
        parent_asin=parent_asin,
        categories=categories,
    )
    new_count, duplicate_count = store.add_reviews(asin, marketplace, normalized)

    warnings = list(getattr(scraper, "last_warnings", []) or [])
    status = "partial" if warnings else "ok"
    error = " | ".join(warnings)
    run: Dict[str, Any] = {
        "started_at": started,
        "finished_at": utc_now(),
        "new_reviews": new_count,
        "duplicate_reviews": duplicate_count,
        "status": status,
        "error": error,
    }
    store.log_run(
        asin,
        marketplace,
        new_count,
        duplicate_count,
        status,
        error=error,
        started_at=started,
    )
    store.enqueue_collection(
        asin,
        marketplace,
        title,
        normalized,
        parent_asin=parent_asin,
        categories=categories,
        run=run,
    )

    for warning in warnings:
        _log(log_callback, f"[部分成功] {warning}")
    if repository:
        sync = repository.sync_pending()
        if sync["synced"]:
            _log(log_callback, f"[云同步] 已提交 {sync['synced']} 个批次")
        if sync["error"]:
            _log(log_callback, f"[离线队列] {sync['error']}")

    _log(
        log_callback,
        f"[入库] {asin}: 抓取 {len(normalized)} 条，新增 {new_count} 条，已存在 {duplicate_count} 条",
    )
    return new_count, duplicate_count


__all__ = ["collect_product", "CollectionCancelled"]

