"""Local authoritative repository; never opens a cloud connection."""
from .store import ReviewStore

class ReviewRepository:
    def __init__(self, local_store=None):
        self.local = local_store or ReviewStore()
        self._owns_local = local_store is None
        self.cloud_error = ""  # Compatibility for existing export dialogs.
    def close(self):
        if self._owns_local: self.local.close()
    def product_stats(self):
        return self.local.product_stats(), "本地数据库"
    def query_reviews(self, **filters):
        return self.local.query_reviews(**filters), "本地数据库"
    def total_reviews(self):
        return self.local.total_reviews(), "本地数据库"
    def export_snapshot(self, **filters):
        filters.pop("limit", None)
        return self.local.query_reviews(limit=2147483647, **filters), "本地快照"
