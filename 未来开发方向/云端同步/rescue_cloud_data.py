"""One-time cloud export. Original user database is opened read-only."""
from pathlib import Path
import importlib.util
import json
import sqlite3
import sys
import os

root = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root))
from core.reviews.store import ReviewStore

def main():
    source = Path(os.environ['LOCALAPPDATA'])/'PM Stack/reviews/data/reviews.db'
    if not source.exists(): print('No local review database'); return
    output = Path(__file__).parent/'数据迁移留存'
    output.mkdir(exist_ok=True)
    snapshot = output/'reviews_local_and_cloud.db'
    source_conn = sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True)
    target_conn = sqlite3.connect(snapshot)
    try: source_conn.backup(target_conn)
    finally: source_conn.close(); target_conn.close()
    store = ReviewStore(str(snapshot))
    cloud = None
    try:
        if not store.get_setting('supabase_session',''):
            print('No saved cloud session; local snapshot retained'); return
        spec = importlib.util.spec_from_file_location('core.reviews.future_cloud',Path(__file__).parent/'core_reviews/cloud.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        cloud = module.SupabaseStore(store.get_setting('supabase_url',''),store.get_setting('supabase_key',''))
        cloud._http_client.timeout = 20
        cloud.restore_session(store)
        products = cloud.product_stats()
        rows=[];offset=0
        while True:
            page=cloud.query_reviews(limit=1000,offset=offset)
            rows.extend(page)
            if len(page)<1000: break
            offset+=len(page)
        if len(rows)<int(cloud.summary().get('review_count',0)): raise ValueError('Cloud export count mismatch')
        (output/'cloud_reviews.json').write_text(json.dumps({'products':products,'reviews':rows},ensure_ascii=False,indent=2),encoding='utf-8')
        groups={}
        for row in rows:
            if not row.get('marketplace') or not row.get('asin'): raise ValueError('Review identity missing')
            groups.setdefault((row['marketplace'],row['asin']),[]).append(row)
        for (site,asin),reviews in groups.items():
            store.upsert_product(asin,site)
            store.add_reviews(asin,site,reviews)
        print(f'Cloud export complete: {len(rows)} associations; combined local database: {store.total_reviews()} unique reviews')
    except Exception as exc:
        # Error details can contain project/account information; keep a generic status.
        print(f'Cloud export unavailable: {type(exc).__name__}; original database unchanged')
        raise SystemExit(2)
    finally:
        if cloud: cloud.close()
        store.conn.execute("DELETE FROM settings WHERE key LIKE 'supabase_%' OR key='review_data_scope'")
        store.conn.commit(); store.close()

if __name__ == '__main__': main()
