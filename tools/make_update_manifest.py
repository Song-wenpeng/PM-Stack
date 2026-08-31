# -*- coding: utf-8 -*-
"""为共享盘或 GitHub Release 生成 PM Stack update.json。"""

import argparse
import hashlib
import json
from pathlib import Path


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest().lower()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--url", default="PM Stack.exe")
    parser.add_argument("--notes", default="")
    parser.add_argument("--mandatory", action="store_true")
    parser.add_argument("--output", default="update.json")
    args = parser.parse_args()

    exe = Path(args.exe).resolve(strict=True)
    payload = {
        "version": args.version,
        "url": args.url,
        "sha256": sha256_file(exe),
        "size": exe.stat().st_size,
        "mandatory": args.mandatory,
        "notes": args.notes,
    }
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(output)


if __name__ == "__main__":
    main()
