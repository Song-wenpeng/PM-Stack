from tests import support

import json
import tempfile
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from core.reviews.extension_bridge import ExtensionBridge
from core.reviews.store import ReviewStore

CLIENT = "test-client-0000000001"
ROW = {"review_id":"RTEST0001","rating":5,"content":"Synthetic review","title":"Test"}

class ExtensionBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.temp.name) / "reviews.db")
        self.bridge = ExtensionBridge(self.db, port=0)
        self.bridge.start()

    def tearDown(self):
        self.bridge.stop()
        self.temp.cleanup()

    def request(self, path, payload, token=None, origin="chrome-extension://" + "a"*32):
        headers = {"Content-Type":"application/json", "Origin":origin,
                   "Authorization":"Bearer " + (self.bridge.token if token is None else token)}
        request = Request(f"http://127.0.0.1:{self.bridge.port}" + path,
                          json.dumps({"client":CLIENT, **payload}).encode(), headers)
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.load(response)
        except HTTPError as exc:
            return exc.code, json.load(exc)

    def job(self):
        job = self.bridge.submit("https://www.amazon.com/dp/B0DDG2KQQ9", "amazon.com")
        self.assertEqual(self.request("/poll", {})[0], 200)
        return job

    def ready(self, job, **overrides):
        return {"id":job["id"], "status":"ready", "url":job["url"],
                "reviews":[ROW], "title":"Fixture", **overrides}

    def test_requires_token_and_extension_origin(self):
        self.assertEqual(self.request("/poll", {}, token="wrong")[0], 401)
        self.assertEqual(self.request("/poll", {}, origin="https://example.com")[0], 403)
        self.assertEqual(self.request("/poll", {}, origin="")[0], 403)
        self.assertFalse(self.bridge.snapshot()["connected"])

    def test_queue_capture_and_retry_are_idempotent(self):
        job = self.job()
        status, saved = self.request("/result", self.ready(job))
        self.assertEqual(status, 200)
        self.assertEqual(saved["job"]["new"], 1)
        self.assertEqual(self.request("/result", self.ready(job))[1], saved)
        job2 = self.job()
        result = self.request("/result", self.ready(job2))[1]["job"]
        self.assertEqual((result["new"], result["duplicates"]), (0, 1))
        store = ReviewStore(self.db)
        try:
            self.assertEqual(store.total_reviews(), 1)
        finally:
            store.close()

    def test_wrong_product_and_empty_payload_do_not_commit(self):
        job = self.job()
        for fields in ({"url":"https://www.amazon.com/product-reviews/B012345678/"},
                       {"reviews":[]}, {"reviews":[{**ROW, "rating":True}]},
                       {"reviews":[{**ROW, "rating":float("nan")}]},
                       {"url":"https://www.amazon.com.evil.test/product-reviews/B0DDG2KQQ9/"}):
            self.assertEqual(self.request("/result", self.ready(job, **fields))[0],400)
        store = ReviewStore(self.db)
        try:
            self.assertEqual(store.total_reviews(), 0)
        finally:
            store.close()

    def test_waiting_can_resume_but_cancelled_cannot_commit(self):
        job = self.job()
        self.assertEqual(self.request("/result", {"id":job["id"],"status":"waiting","message":"Login"})[0],200)
        self.assertEqual(self.bridge.snapshot()["job"]["status"], "waiting")
        self.bridge.cancel()
        self.assertEqual(self.request("/result", self.ready(job))[1]["job"]["status"], "cancelled")
        store = ReviewStore(self.db)
        try: self.assertEqual(store.total_reviews(), 0)
        finally: store.close()

    def test_second_profile_cannot_take_task(self):
        self.job()
        self.assertEqual(self.request("/poll", {"client":"different-client-0000002"})[0],400)

    def test_pairing_survives_restart_and_site_mismatch_is_rejected(self):
        other = ExtensionBridge(self.db, port=0)
        self.assertEqual(other.token, self.bridge.token)
        with self.assertRaises(ValueError):
            self.bridge.submit("https://www.amazon.de/dp/B0DDG2KQQ9", "amazon.com")
        with self.assertRaises(ValueError):
            self.bridge.submit("https://evil.test/dp/B0DDG2KQQ9", "amazon.com")
