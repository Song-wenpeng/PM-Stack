from tests import support

import unittest

from core.reviews.scraper import AmazonReviewScraper


class ScraperCategoryTests(unittest.TestCase):
    def test_extracts_browse_node_from_common_amazon_links(self):
        cases = {
            "/b/ref=dp_bc_3?ie=UTF8&node=10967801": "10967801",
            "/s?i=electronics&rh=n%3A10967801": "10967801",
            "/b/Power-Strips/10967801/": "10967801",
        }
        for href, expected in cases.items():
            with self.subTest(href=href):
                self.assertEqual(AmazonReviewScraper._category_id_from_href(href), expected)


if __name__ == "__main__":
    unittest.main()
