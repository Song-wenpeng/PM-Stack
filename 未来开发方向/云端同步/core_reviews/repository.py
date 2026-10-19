"""Application repository: Supabase first, SQLite fallback/outbox."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple

from .store import ReviewStore
from .metadata import merge_payload
from .cloud import SupabaseAuthError, SupabaseNotConfigured, SupabaseStore


class ReviewRepository:
    def __init__(self, local_store: Optional[ReviewStore] = None):
        self.local = local_store or ReviewStore()
        self._owns_local = local_store is None
        self.cloud: Optional[SupabaseStore] = None
        self.cloud_error = ""
        if SupabaseStore.is_configured(self.local):
            try:
                self.cloud = SupabaseStore.from_local_settings(self.local)
            except Exception as exc:
                self.cloud_error = str(exc)

    def close(self) -> None:
        if self.cloud:
            self.cloud.close()
        if self._owns_local:
            self.local.close()

    @property
    def cloud_available(self) -> bool:
        return self.cloud is not None

    def login(self, url: str, key: str, email: str, password: str) -> str:
        cloud = SupabaseStore(url, key)
        try:
            workspace_id = cloud.sign_in(email, password, self.local)
        except Exception:
            cloud.close()
            raise
        if self.cloud:self.cloud.close()
        self.cloud = cloud
        self.cloud_error = ""
        return workspace_id

    def logout(self) -> None:
        if self.cloud:
            self.cloud.sign_out(self.local)
        else:
            self.local.delete_setting("supabase_session")
            self.local.delete_setting("supabase_workspace_id")
        self.cloud = None

    def sync_pending(self, limit: int = 200, *, force: bool = False, stop=lambda:False, progress=lambda message:None):
        from .sync_lock import uploader_lock
        with uploader_lock(self.local.db_path):
            return self._sync_snapshot(limit,force,stop,progress)

    def _sync_snapshot(self,limit,force,stop,progress):
        synced=failed=0
        error=""
        cancelled=False
        if not self.cloud:
            error=self.cloud_error or "未保存可恢复的登录会话，请填写密码并重新登录；待同步数据保留"
        else:
            try:
                if isinstance(self.cloud,SupabaseStore):self.cloud.assert_scope(self.local)
                watermark=self.local.conn.execute("SELECT COALESCE(MAX(id),0) FROM outbox").fetchone()[0]
                total=self.local.conn.execute("SELECT COUNT(*) FROM outbox WHERE id<=? AND status IN ('pending','failed','syncing')",(watermark,)).fetchone()[0]
                progress(f"开始同步：本次待处理 {total} 个任务")
                while True:
                    if stop():cancelled=True;break
                    rows=self.local.pending_outbox(limit=max(1,min(int(limit),200)),include_deferred=force,max_id=watermark)
                    if not rows:break
                    if isinstance(self.cloud,SupabaseStore):self.cloud.persist_session(self.local)
                    for row in rows:
                        if stop():cancelled=True;break
                        self.local.mark_outbox_syncing(row["id"])
                        try:
                            payload=json.loads(row["payload_json"])
                            for item in payload.get("reviews",[]):
                                current=self.local.conn.execute("SELECT raw_json FROM reviews WHERE marketplace=? AND review_id=?",
                                    (item.get("marketplace"),item.get("review_id"))).fetchone()
                                if current:item["raw_payload"]=merge_payload(item.get("raw_payload"),current["raw_json"])
                            self.cloud.ingest_batch(payload,row["idempotency_key"])
                        except Exception as exc:
                            failed+=1;error=str(exc)
                            self.local.mark_outbox_failed(row["id"],error)
                            break
                        else:
                            synced+=1;self.local.mark_outbox_synced(row["id"])
                            if synced%20==0:progress(f"已同步 {synced}/{total} 个任务")
                    if isinstance(self.cloud,SupabaseStore):self.cloud.persist_session(self.local)
                    if error or cancelled:break
                progress(f"本次同步结束：成功 {synced}，失败 {failed}")
            except Exception as exc:
                error=str(exc)
        stats=self.local.outbox_stats()
        return {"synced":synced,"failed":failed,"remaining":stats["pending"]+stats["failed"]+stats["syncing"],"error":error,"cancelled":cancelled}

    def export_snapshot(self,**filters):
        """Pin a complete source, then overlay same-space local updates before rendering."""
        local_rows=self.local.query_reviews(limit=2147483647)
        if not self.cloud:
            rows=local_rows
            source="本地快照"
        else:
            try:
                if isinstance(self.cloud,SupabaseStore):self.cloud.assert_scope(self.local)
                rows=[];offset=0;seen=set()
                while True:
                    page=self.cloud.query_reviews(limit=1000,offset=offset)
                    for row in page:
                        if not row.get("marketplace"):raise ValueError("云端评论站点不明确，已回退本地快照")
                        key=(row.get("marketplace"),row.get("asin"),row.get("review_id"))
                        if key in seen:raise ValueError("云端分页数据发生变化，请重试导出")
                        seen.add(key)
                    rows.extend(page)
                    if len(page)<1000:break
                    offset+=len(page)
                mapping={(r.get("marketplace"),r.get("asin"),r.get("review_id")):r for r in rows}
                for local in local_rows:
                    key=(local.get("marketplace"),local.get("asin"),local.get("review_id"))
                    remote=mapping.get(key)
                    if remote and remote.get("content")==local.get("content"):
                        from .metadata import raw_of
                        remote={**remote,"raw_payload":merge_payload(raw_of(remote),raw_of(local))}
                        mapping[key]=remote
                    elif not remote or str(local.get("last_seen_at",""))>=str(remote.get("last_seen_at","")):
                        mapping[key]=local
                rows=list(mapping.values());source="云端与本地结果快照"
            except Exception as exc:
                self.cloud_error=str(exc);rows=local_rows;source="本地快照（云端不可用）"
        asin,rating,keyword=filters.get("asin"),filters.get("rating"),filters.get("keyword","").casefold()
        rows=[r for r in rows if (not asin or r.get("asin")==asin)
              and (rating is None or (r.get("rating") is not None and int(float(r["rating"])+0.5)==rating))
              and (not keyword or keyword in (str(r.get("title",""))+" "+str(r.get("content",""))).casefold())]
        rows.sort(key=lambda r:(str(r.get("review_date") or ""),str(r.get("marketplace") or ""),str(r.get("asin") or ""),str(r.get("review_id") or "")),reverse=True)
        return rows,source

    def product_stats(self) -> Tuple[list, str]:
        if self.cloud:
            try:
                return self.cloud.product_stats(), "Supabase"
            except Exception as exc:
                self.cloud_error = str(exc)
        return self.local.product_stats(), "本地缓存"

    def query_reviews(self, **filters) -> Tuple[list, str]:
        if self.cloud:
            try:
                rows=self.cloud.query_reviews(**filters)
                from .metadata import raw_of
                for row in rows:
                    local=self.local.conn.execute("SELECT content,raw_json FROM reviews WHERE marketplace=? AND review_id=?",
                        (row.get("marketplace"),row.get("review_id"))).fetchone()
                    if local and local["content"]==row.get("content"):
                        row["raw_payload"]=merge_payload(raw_of(row),local["raw_json"])
                return rows, "Supabase（含本地新标签）"
            except Exception as exc:
                self.cloud_error = str(exc)
        return self.local.query_reviews(**filters), "本地缓存"

    def total_reviews(self) -> Tuple[int, str]:
        if self.cloud:
            try:
                summary = self.cloud.summary()
                return int(summary.get("review_count", 0)), "Supabase"
            except Exception as exc:
                self.cloud_error = str(exc)
        return self.local.total_reviews(), "本地缓存"


__all__ = [
    "ReviewRepository", "SupabaseStore", "SupabaseNotConfigured", "SupabaseAuthError"
]
