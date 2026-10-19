"""Conservative correction of local, never-synced import associations."""
import json
import re
import uuid
from pathlib import Path
from .metadata import as_dict, KEY
from .normalizer import utc_now, json_dumps, normalize_reviews
from .cloud import SupabaseStore

def batches(store):
    groups = {}
    for row in store.conn.execute("SELECT r.marketplace,pr.asin,r.review_id,r.raw_json FROM reviews r JOIN product_reviews pr ON r.marketplace=pr.marketplace AND r.review_id=pr.review_id"):
        for source in as_dict(as_dict(row["raw_json"]).get(KEY)).get("imports",{}).values():
            if not isinstance(source,dict) or source.get("target_asin") != row["asin"]: continue
            digest = source.get("file_sha256")
            if not digest: continue
            key = (row["marketplace"],row["asin"],digest)
            group = groups.setdefault(key,{"marketplace":key[0],"asin":key[1],"sha256":digest,"file":source.get("file",""),"ids":set()})
            group["ids"].add(row["review_id"])
    return sorted(groups.values(),key=lambda r:(r["asin"],r["file"]))

def _guard(store, batch):
    if SupabaseStore.is_configured(store):
        raise ValueError("此入口仅处理本地未同步导入。已配置云端时需同时核对云端归属，当前不执行修改。")
    for row in store.conn.execute("SELECT status,payload_json FROM outbox"):
        if row["status"] == "syncing":
            raise ValueError("同步正在进行，请等待结束")
        if row["status"] != "synced": continue
        p = as_dict(row["payload_json"]).get("product",{})
        if p.get("asin")==batch["asin"] and p.get("marketplace")==batch["marketplace"]:
            raise ValueError("该商品存在已同步记录，不能只修改本地，请先处理云端归属")

def change_batch(store, batch, destination=""):
    """Remove one file's contribution, optionally associate it with a new ASIN.
    Other import contributions and known browser collections keep their links.
    Raw reviews and AI labels are retained, including unlinked rows for recovery.
    """
    destination = destination.strip().upper()
    if destination and (not re.fullmatch(r"B[A-Z0-9]{9}",destination) or destination==batch["asin"]):
        raise ValueError("请输入不同的有效目标 ASIN")
    live = next((b for b in batches(store) if all(b[k]==batch[k] for k in ("marketplace","asin","sha256"))),None)
    if not live: raise ValueError("导入记录已变化，请刷新后重试")
    _guard(store,live)
    backup_dir = Path(store.db_path).parent / "backups"
    backup_dir.mkdir(parents=True,exist_ok=True)
    backup = backup_dir / ("before-import-correction-"+uuid.uuid4().hex+".db")
    store.backup_to(str(backup))
    site, old, ids = live["marketplace"],live["asin"],live["ids"]
    now = utc_now()
    moved, removed, kept = 0,0,0
    store.conn.execute("BEGIN IMMEDIATE")
    try:
        _guard(store,live)
        # The history is durable even after a batch no longer has active links.
        store.conn.execute("CREATE TABLE IF NOT EXISTS import_corrections (id TEXT PRIMARY KEY, created_at TEXT, details_json TEXT)")
        known_browser = set()
        queue = list(store.conn.execute("SELECT * FROM outbox"))
        for row in queue:
            payload = as_dict(row["payload_json"])
            product = payload.get("product",{})
            if product.get("marketplace") != site or product.get("asin") != old: continue
            for review in payload.get("reviews",[]):
                imports = as_dict(as_dict(as_dict(review.get("raw_payload")).get(KEY)).get("imports"))
                if not imports: known_browser.add(review.get("review_id"))
        if destination:
            store.conn.execute("""INSERT INTO products(asin,marketplace,added_at,last_scraped_at)
                VALUES (?,?,?,?) ON CONFLICT(asin,marketplace) DO NOTHING""",(destination,site,now,now))
        snapshots = []
        removed_ids = set()
        for rid in sorted(ids):
            row = dict(store.conn.execute("SELECT * FROM reviews WHERE marketplace=? AND review_id=?",(site,rid)).fetchone())
            raw = as_dict(row["raw_json"])
            meta = as_dict(raw.get(KEY))
            imports = as_dict(meta.get("imports"))
            updated = {}
            preexisting = False
            for source_id,source in imports.items():
                matches = source.get("target_asin")==old and source.get("file_sha256")==live["sha256"]
                if not matches: updated[source_id]=source; continue
                preexisting = preexisting or source.get("preexisting_link",False)
                if destination:
                    updated[source_id+":corrected:"+destination] = {**source,"target_asin":destination,"corrected_from":old,"corrected_at":now}
            raw[KEY] = {**meta,"imports":updated}
            store.conn.execute("UPDATE reviews SET raw_json=? WHERE marketplace=? AND review_id=?",(json_dumps(raw),site,rid))
            keep = preexisting or rid in known_browser or any(v.get("target_asin")==old for v in updated.values())
            if keep:
                kept += 1
            else:
                store.conn.execute("DELETE FROM product_reviews WHERE marketplace=? AND asin=? AND review_id=?",(site,old,rid))
                removed += 1
                removed_ids.add(rid)
            if destination:
                store.conn.execute("""INSERT INTO product_reviews(marketplace,asin,review_id,first_seen_at,last_seen_at)
                    VALUES(?,?,?,?,?) ON CONFLICT(marketplace,asin,review_id) DO NOTHING""",(site,destination,rid,now,now))
                row["raw_payload"]=raw
                snapshots.append(row)
                moved += 1
        # Prune stale uploads so a later sync cannot recreate the removed links.
        for entry in queue:
            payload=as_dict(entry["payload_json"])
            p=payload.get("product",{})
            reviews=payload.get("reviews",[])
            if p.get("marketplace")==site and p.get("asin")==old:
                reviews=[r for r in reviews if r.get("review_id") not in removed_ids]
            for r in reviews:
                if r.get("marketplace")==site and r.get("review_id") in ids:
                    saved=store.conn.execute("SELECT raw_json FROM reviews WHERE marketplace=? AND review_id=?",(site,r["review_id"])).fetchone()
                    r["raw_payload"]=as_dict(saved["raw_json"])
            if not reviews and payload.get("reviews"):
                store.conn.execute("DELETE FROM outbox WHERE id=?",(entry["id"],))
            else:
                payload["reviews"]=reviews
                store.conn.execute("UPDATE outbox SET payload_json=? WHERE id=?",(json_dumps(payload),entry["id"]))
        if destination:
            payload={"product":{"asin":destination,"marketplace":site,"title":""},"reviews":normalize_reviews(destination,site,snapshots),"run":{}}
            store.conn.execute("""INSERT INTO outbox(idempotency_key,entity_type,payload_json,status,created_at,updated_at)
                VALUES(?,'review_batch',?,'pending',?,?)""",("correction:"+uuid.uuid4().hex,json_dumps(payload),now,now))
        result={"removed":removed,"associated":moved,"retained":kept,"backup":str(backup)}
        store.conn.execute("INSERT INTO import_corrections VALUES(?,?,?)",(uuid.uuid4().hex,now,json_dumps({**result,"asin":old,"marketplace":site,"destination":destination,"file":live["file"],"sha256":live["sha256"],"review_ids":sorted(ids)})))
        store.conn.commit()
        return result
    except Exception:
        store.conn.rollback()
        raise
