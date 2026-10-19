"""Supabase 主数据库适配器。

所有业务写入通过事务型 RPC 完成；行权限由 Supabase Auth + RLS 控制。
模块使用延迟导入，因此离线采集时不要求 Supabase 可达。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from core.secure_storage import protect_secret, unprotect_secret
from .metadata import merge_payload


class SupabaseNotConfigured(RuntimeError):
    pass


class SupabaseAuthError(RuntimeError):
    pass


def _response_data(response: Any) -> Any:
    return getattr(response, "data", response)


class SupabaseStore:
    def __init__(self, project_url: str, publishable_key: str):
        project_url = (project_url or "").strip().rstrip("/")
        if "/rest/" in project_url:
            project_url = project_url.split("/rest/", 1)[0].rstrip("/")
        publishable_key = (publishable_key or "").strip()
        if not project_url or not publishable_key:
            raise SupabaseNotConfigured("尚未配置 Supabase 项目 URL 和可发布密钥")
        try:
            import httpx
            from supabase import ClientOptions, create_client
        except ImportError as exc:
            raise SupabaseNotConfigured(
                "当前程序缺少 supabase 依赖，请重新安装完整版或执行 pip install -r requirements.txt"
            ) from exc

        self.project_url = project_url
        self.publishable_key = publishable_key
        # Environment-injected proxies can break TLS negotiation on some Windows
        # machines.  The desktop app connects directly to the configured Supabase
        # project, so do not inherit process proxy variables here.
        self._http_client = httpx.Client(trust_env=False, timeout=120.0)
        self.client = create_client(
            project_url,
            publishable_key,
            options=ClientOptions(httpx_client=self._http_client,auto_refresh_token=False),
        )
        self.workspace_id: Optional[str] = None

    def close(self) -> None:
        self._http_client.close()

    @classmethod
    def from_local_settings(cls, local_store, *, restore_session: bool = True):
        url = local_store.get_setting("supabase_url", "") or ""
        key = local_store.get_setting("supabase_key", "") or ""
        cloud = cls(url, key)
        if restore_session:
            try:cloud.restore_session(local_store)
            except Exception:
                cloud.close()
                raise
        return cloud

    @staticmethod
    def is_configured(local_store) -> bool:
        return bool(
            local_store.get_setting("supabase_url", "")
            and local_store.get_setting("supabase_key", "")
        )

    def _save_session(self, local_store, session: Any) -> None:
        if not session or not getattr(session,"access_token","") or not getattr(session,"refresh_token",""):
            raise SupabaseAuthError("Supabase 未返回完整登录会话，请重新登录")
        payload = json.dumps(
            {
                "access_token": getattr(session, "access_token", ""),
                "refresh_token": getattr(session, "refresh_token", ""),
            },
            ensure_ascii=False,
        )
        encrypted=protect_secret(payload)
        if not encrypted or unprotect_secret(encrypted)!=payload:
            raise SupabaseAuthError("登录成功，但安全会话保存校验失败，请重试")
        local_store.set_setting("supabase_session",encrypted)
        if local_store.get_setting("supabase_session","")!=encrypted:
            raise SupabaseAuthError("登录成功，但登录会话未写入本地数据库")

    def sign_in(self, email: str, password: str, local_store) -> str:
        if not email or not password:
            raise SupabaseAuthError("请输入 Supabase 登录邮箱和密码")
        try:
            response = self.client.auth.sign_in_with_password(
                {"email": email.strip(), "password": password}
            )
        except Exception as exc:
            raise SupabaseAuthError(f"Supabase 登录失败：{exc}") from exc

        self.workspace_id = self.ensure_workspace()
        self.assert_scope(local_store,email=email)
        # Commit the authenticated session and its destination together.
        session=getattr(response,"session",None)
        if not session or not getattr(session,"access_token","") or not getattr(session,"refresh_token",""):
            raise SupabaseAuthError("登录未返回完整会话，请重试")
        payload=json.dumps({"access_token":session.access_token,"refresh_token":session.refresh_token})
        encrypted=protect_secret(payload)
        if unprotect_secret(encrypted)!=payload:raise SupabaseAuthError("会话加密验证失败")
        values={"supabase_session":encrypted,"supabase_url":self.project_url,
                "supabase_key":self.publishable_key,"supabase_email":email.strip(),
                "supabase_workspace_id":self.workspace_id,
                "review_data_scope":json.dumps({"url":self.project_url,"workspace":self.workspace_id})}
        with local_store.conn:
            for key,value in values.items():
                local_store.conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(key,value))
        if local_store.get_setting("supabase_session","")!=encrypted:raise SupabaseAuthError("会话未保存，请重新登录")
        return self.workspace_id

    def assert_scope(self,local_store,email=None):
        scope=local_store.get_setting("review_data_scope","")
        if scope:
            bound=json.loads(scope)
            if bound.get("url")!=self.project_url or bound.get("workspace")!=self.workspace_id:
                raise SupabaseAuthError("当前评论库属于另一云端空间，已阻止同步。请使用原项目和账号；切换空间需要单独迁移。")
        elif local_store.total_reviews() or local_store.conn.execute("SELECT 1 FROM outbox LIMIT 1").fetchone():
            prior_url=(local_store.get_setting("supabase_url","") or "").rstrip("/")
            prior_workspace=local_store.get_setting("supabase_workspace_id","") or ""
            prior_email=local_store.get_setting("supabase_email","") or ""
            if (prior_url and prior_url!=self.project_url) or (prior_workspace and prior_workspace!=self.workspace_id) or (email and prior_email and prior_email.casefold()!=email.strip().casefold()):
                raise SupabaseAuthError("本地已有评论及同步历史，请使用之前的项目和账号；不能直接将旧队列发往新空间。")

    def persist_session(self,local_store):
        self._save_session(local_store,self.client.auth.get_session())


    def restore_session(self, local_store) -> str:
        encrypted = local_store.get_setting("supabase_session", "") or ""
        if not encrypted:
            raise SupabaseAuthError("尚未登录 Supabase")
        try:
            tokens = json.loads(unprotect_secret(encrypted))
            response = self.client.auth.set_session(
                tokens["access_token"], tokens["refresh_token"]
            )
        except Exception as exc:
            # 不删除令牌：短暂网络故障时仍可稍后重试。
            raise SupabaseAuthError(f"无法恢复 Supabase 登录会话：{exc}") from exc
        self.workspace_id = self.ensure_workspace()
        self.assert_scope(local_store)
        self._save_session(local_store, getattr(response, "session", None))
        local_store.set_setting("supabase_workspace_id", self.workspace_id)
        local_store.set_setting("review_data_scope",json.dumps({"url":self.project_url,"workspace":self.workspace_id}))
        return self.workspace_id

    def sign_out(self, local_store) -> None:
        try:
            self.client.auth.sign_out()
        finally:
            local_store.delete_setting("supabase_session")
            local_store.delete_setting("supabase_workspace_id")
            self.workspace_id = None

    def ensure_workspace(self) -> str:
        try:
            data = _response_data(self.client.rpc("ensure_personal_workspace").execute())
        except Exception as exc:
            raise SupabaseAuthError(
                "无法初始化云端工作区；请确认已执行 supabase/migrations 下的 SQL"
            ) from exc
        if isinstance(data, list):
            data = data[0] if data else None
            if isinstance(data, dict):
                data = next(iter(data.values()), None)
        if isinstance(data, dict):
            data = data.get("ensure_personal_workspace") or data.get("workspace_id")
        if not data:
            raise SupabaseAuthError("Supabase 没有返回工作区 ID")
        return str(data)

    def _workspace(self) -> str:
        if not self.workspace_id:
            self.workspace_id = self.ensure_workspace()
        return self.workspace_id

    def review_metadata(self, review_ids):
        result = []
        ids = list(dict.fromkeys(review_ids))
        for start in range(0,len(ids),100):
            data = _response_data(self.client.table("reviews")
                .select("marketplace,review_id,content,raw_payload")
                .eq("workspace_id",self._workspace()).in_("review_id",ids[start:start+100]).execute())
            result.extend(data or [])
        return result

    def ingest_batch(self, payload: Dict[str, Any], idempotency_key: str) -> Dict[str, Any]:
        incoming = [dict(item) for item in (payload.get("reviews") or [])]
        remote = {(r["marketplace"],r["review_id"]):r for r in
                  self.review_metadata([r["review_id"] for r in incoming])}
        for item in incoming:
            old = remote.get((item.get("marketplace"),item["review_id"]), {})
            item["raw_payload"] = merge_payload(old.get("raw_payload"),item.get("raw_payload"))
        params = {
            "p_workspace_id": self._workspace(),
            "p_product": payload.get("product") or {},
            "p_reviews": incoming,
            "p_run": payload.get("run") or {},
            "p_idempotency_key": idempotency_key,
        }
        data = _response_data(self.client.rpc("ingest_review_batch", params).execute())
        return data or {}

    def product_stats(self) -> List[Dict[str, Any]]:
        data = _response_data(
            self.client.rpc(
                "list_product_stats", {"p_workspace_id": self._workspace()}
            ).execute()
        )
        return list(data or [])

    def query_reviews(
        self,
        *,
        asin: Optional[str] = None,
        rating: Optional[int] = None,
        keyword: str = "",
        limit: int = 500,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        data = _response_data(
            self.client.rpc(
                "search_reviews",
                {
                    "p_workspace_id": self._workspace(),
                    "p_asin": asin,
                    "p_rating": rating,
                    "p_keyword": keyword or None,
                    "p_limit": max(1, min(int(limit), 5000)),
                    "p_offset": max(0, int(offset)),
                },
            ).execute()
        )
        rows = list(data or [])
        metadata = self.review_metadata([r["review_id"] for r in rows])
        for row in rows:
            candidates = [m for m in metadata if m["review_id"]==row["review_id"]
                          and m.get("content")==row.get("content")]
            if len(candidates)==1:
                row["marketplace"] = candidates[0]["marketplace"]
                row["raw_payload"] = candidates[0]["raw_payload"]
        return rows

    def summary(self) -> Dict[str, Any]:
        data = _response_data(
            self.client.rpc(
                "get_workspace_summary", {"p_workspace_id": self._workspace()}
            ).execute()
        )
        if isinstance(data, list):
            data = data[0] if data else {}
        return dict(data or {})


__all__ = ["SupabaseStore", "SupabaseNotConfigured", "SupabaseAuthError"]
