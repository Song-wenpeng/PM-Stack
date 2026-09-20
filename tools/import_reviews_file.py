"""Import a review XLSX through the same application service."""
import argparse
import json
from pathlib import Path
import sys
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core.config_manager import ConfigManager
from core.reviews.excel_import import read_import, import_reviews, extract_labels
from core.reviews.store import ReviewStore
from core.reviews.repository import ReviewRepository

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("file")
    parser.add_argument("--asin",required=True)
    parser.add_argument("--marketplace",default="amazon.com")
    parser.add_argument("--category",default="power strip")
    parser.add_argument("--ai",action="store_true")
    parser.add_argument("--sync",action="store_true")
    parser.add_argument("--dry-run",action="store_true")
    parser.add_argument("--max-labels",type=int,default=0)
    args=parser.parse_args()
    data=read_import(args.file,args.asin,args.marketplace)
    print(json.dumps({k:v for k,v in data.items() if k!="rows"},ensure_ascii=False),flush=True)
    if args.dry_run: return
    store=ReviewStore()
    try:
        runtime_dir=Path(__file__).resolve().parents[1]/".runtime-local"
        runtime_dir.mkdir(parents=True,exist_ok=True)
        backup=runtime_dir/("before-import-"+datetime.now().strftime("%Y%m%d-%H%M%S")+".db")
        store.backup_to(str(backup))
        new,duplicates=import_reviews(store,data,lambda msg:print(msg,flush=True))
        result={"new":new,"duplicates":duplicates}
        if args.ai:
            manager=ConfigManager()
            configs=json.loads(Path(manager.resolve_config("product_configs.json")).read_text(encoding="utf-8"))
            if args.max_labels: data={**data,"rows":data["rows"][:args.max_labels]}
            result["labels"]=extract_labels(store,data,args.category,configs[args.category],
                manager.get_env_dict(),log=lambda msg:print(msg,flush=True))
        if args.sync:
            repo=ReviewRepository(store)
            try: result["sync"]=repo.sync_pending(limit=200,force=True)
            finally: repo.close()
        print(json.dumps(result,ensure_ascii=False),flush=True)
        (runtime_dir/"import-live-result.json").write_text(
            json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    finally: store.close()
if __name__=="__main__": main()
