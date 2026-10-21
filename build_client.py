#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把客户端源文件里的统一占位符替换成真正想要的默认值。

源文件（仓库里）写的是占位符，避免把任何真实地址带进公开仓库：
  @@SERVER_PLACEHOLDER@@   -> 默认服务器地址
发布者打包/自用前按自己的部署改掉即可。

用法：
  python3 build_client.py --set-server https://your-server.example.com
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLACEHOLDER = "@@SERVER_PLACEHOLDER@@"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set-server", required=True,
                    help="默认服务器根地址，例如 https://your-server.example.com")
    ap.add_argument("--files", nargs="*", default=None,
                    help="要处理的文件（默认 wordclip.ps1 wordclip.bat clipboard/wordclip.ps1）")
    args = ap.parse_args()

    files = args.files or ["wordclip.ps1", "wordclip.bat", "clipboard/wordclip.ps1"]
    server = args.set_server.rstrip("/")
    n = 0
    for rel in files:
        p = HERE / rel
        if not p.exists():
            print("跳过（不存在）:", rel)
            continue
        s = p.read_text(encoding="utf-8")
        if PLACEHOLDER not in s:
            print("跳过（无占位符）:", rel)
            continue
        p.write_text(s.replace(PLACEHOLDER, server), encoding="utf-8")
        n += 1
        print("已写入默认地址:", rel)
    print(f"共处理 {n} 个文件")
    return 0 if n else 1


if __name__ == "__main__":
    sys.exit(main())
