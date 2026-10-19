"""Correction of local import associations."""
import json
import re
import uuid
from pathlib import Path
from .metadata import as_dict, KEY
from .normalizer import utc_now, json_dumps, normalize_reviews

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
    backup_dir = Path(store.db_path).parent / "backups"
    backup_dir.mkdir(parents=True,exist_ok=True)
    backup = backup_dir / ("before-import-correction-"+uuid.uuid4().hex+".db")
    store.backup_to(str(backup))
    site, old, ids = live["marketplace"],live["asin"],live["ids"]
    now = utc_now()
    moved, removed, kept = 0,0,0
    store.conn.execute("BEGIN IMMEDIATE")
    try:
        # The history is durable even after a batch no longer has active links.
        store.conn.execute("CREATE TABLE IF NOT EXISTS import_corrections (id TEXT PRIMARY KEY, created_at TEXT, details_json TEXT)")
        known_browser = set()
        queue = list(store.conn.execute("SELECT payload_json FROM outbox UNION ALL SELECT payload_json FROM collection_events"))
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
        result={"removed":removed,"associated":moved,"retained":kept,"backup":str(backup)}
        store.conn.execute("INSERT INTO import_corrections VALUES(?,?,?)",(uuid.uuid4().hex,now,json_dumps({**result,"asin":old,"marketplace":site,"destination":destination,"file":live["file"],"sha256":live["sha256"],"review_ids":sorted(ids)})))
        store.conn.commit()
        return result
    except Exception:
        store.conn.rollback()
        raise
