# -*- coding: utf-8 -*-
"""兼容原单文件入口，与批量入口共享拆分计算。"""
import argparse
import sys
from pathlib import Path

try:
    from scripts.batch_sales_split import write_result, output_path
except ModuleNotFoundError:
    from batch_sales_split import write_result, output_path

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source')
    parser.add_argument('output', nargs='?')
    args = parser.parse_args()
    try:
        write_result(args.source, args.output or output_path(args.source))
        return 0
    except Exception as exc:
        print(f'[错误] {exc}')
        return 1

if __name__ == '__main__':
    sys.exit(main())
