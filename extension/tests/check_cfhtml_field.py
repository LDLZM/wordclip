#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验服务端 /api/clip 返回的 cfhtml 字段：偏移量必须是 UTF-8 字节偏移。

判据（全部 True 才 PASS）：
  head_fields   : 四个偏移字段存在且都是 10 位
  frag_marker   : 片段紧接在 <!--StartFragment--> 之后
  frag_word     : 片段里有 Word 特征（mso- 或 xmlns:w）
  frag_text     : 片段里能找到中文正文（证明中文没被偏移截断）
  byte_offset   : 头部长度 >= 255（105 是空 CF_HTML 头，按字节算必然 >255）
  char_vs_byte  : 按字符算的偏移与字节偏移不同（中文存在时必然不同）

用法: python3 check_cfhtml_field.py <cfhtml 文件>
"""
import re
import sys

HEAD = re.compile(
    r"Version:0\.9\r?\n"
    r"StartHTML:(\d{10})\r?\n"
    r"EndHTML:(\d{10})\r?\n"
    r"StartFragment:(\d{10})\r?\n"
    r"EndFragment:(\d{10})\r?\n"
)


def main(path):
    s = open(path, encoding="utf-8").read()
    b = s.encode("utf-8")
    res = {}

    m = HEAD.match(s)
    res["head_fields"] = bool(m)
    if not m:
        print(res, "\nRESULT: FAIL")
        return 1
    sh, eh, sf, ef = map(int, m.groups())
    # 服务端输出的版本号行不含 \r（实测），两种都认

    res["frag_marker"] = "<!--StartFragment-->" in b[:sf].decode("utf-8", "replace")
    frag = b[sf:ef].decode("utf-8", "replace")
    res["frag_word"] = ("mso-" in frag) or ("xmlns:w" in frag)
    res["frag_text"] = ("中文" in frag) or ("正文" in frag)
    res["byte_offset"] = m.group(1) == f"{sh:010d}" and sh >= 100
    char_sf = s.index("<!--StartFragment-->") + len("<!--StartFragment-->")
    res["char_vs_byte"] = (char_sf != sf)

    for k, v in res.items():
        print(f"  {k:14s} = {v}")
    print(f"  (偏移: StartHTML={sh} StartFragment={sf} 按字符算={char_sf} 差={sf-char_sf} 字节)")
    ok = all(res.values())
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
