from tests import support

import unittest
from unittest.mock import Mock, patch

from core.reviews.normalizer import normalize_marketplace
from core.reviews.scraper import AmazonReviewScraper, ScrapeError
from core.reviews.service import collect_product


class ReviewStartupTests(unittest.TestCase):
    def test_marketplace_prefix_only(self):
        for source, expected in [("https://www.amazon.com/", "amazon.com"),
                                 ("WWW.amazon.de/", "amazon.de"),
                                 ("ww.amazon.com", "ww.amazon.com")]:
            self.assertEqual(normalize_marketplace(source), expected)

    def test_old_runtime_has_actionable_error(self):
        with patch("core.reviews.scraper.sys.version_info", (3, 8, 0)):
            with self.assertRaisesRegex(ScrapeError, "start-pm-stack.bat"):
                AmazonReviewScraper()._init_driver()

    def test_launch_failure_survives_cleanup_failure(self):
        driver = Mock()
        original = RuntimeError("Target closed: test browser launch failure")
        driver.chromium.launch_persistent_context.side_effect = original
        driver.stop.side_effect = ValueError("set_wakeup_fd only works in main thread")
        scraper = AmazonReviewScraper(log_callback=Mock())
        with patch("playwright.sync_api.sync_playwright") as factory:
            factory.return_value.start.return_value = driver
            with self.assertRaises(ScrapeError) as raised:
                scraper._init_driver()
        self.assertIs(raised.exception.__cause__, original)
        self.assertIn("test browser launch failure", str(raised.exception))
        self.assertIsNone(scraper.playwright)
        driver.stop.assert_called_once()
        scraper.close()
        driver.stop.assert_called_once()

    def test_cleanup_attempts_both_resources(self):
        scraper = AmazonReviewScraper()
        context, driver = Mock(), Mock()
        context.close.side_effect = RuntimeError("context closed")
        scraper.context, scraper.playwright = context, driver
        scraper.close()
        driver.stop.assert_called_once()
        self.assertIsNone(scraper.context)

    def test_failed_run_preserves_scrape_error_when_store_fails(self):
        original = ScrapeError("original launch failure")
        scraper, store, log = Mock(), Mock(), Mock()
        scraper.scrape_reviews_by_star.side_effect = original
        store.upsert_product.side_effect = RuntimeError("database locked")
        with self.assertRaises(ScrapeError) as raised:
            collect_product(store, scraper, "B0DDG2KQQ9", "amazon.com", 1, 1,
                            False, log_callback=log)
        self.assertIs(raised.exception, original)
        self.assertIn("database locked", log.call_args.args[0])

    def test_failed_run_recorded_without_masking_error(self):
        original = ScrapeError("original launch failure")
        scraper, store = Mock(), Mock()
        scraper.scrape_reviews_by_star.side_effect = original
        with self.assertRaises(ScrapeError) as raised:
            collect_product(store, scraper, "B0DDG2KQQ9", "amazon.com", 1, 1, False)
        self.assertIs(raised.exception, original)
        self.assertEqual(store.log_run.call_args.args[4], "failed")
        store.enqueue_collection.assert_called_once()


if __name__ == "__main__":
    unittest.main()
