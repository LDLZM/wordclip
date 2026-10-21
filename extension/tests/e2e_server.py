#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端验证扩展依赖的服务端契约（不需要浏览器）。

跑通这五件事，才能保证"扩展里点一下 → Word 里粘出来有格式"：

  1. GET  /                     页面返回 200 且引用了 extension-bridge.js
  2. GET  /extension-bridge.js  桥接脚本 200 且内容非空
  3. GET  /api/presets          能返回预设列表（设置页下拉要用）
  4. POST /api/clip 无令牌      必须 401（令牌是唯一的访问控制）
  5. POST /api/clip 带令牌      ok=true，且 cfhtml 字段的偏移量按字节正确、含 mso- 样式

用法:
  python3 e2e_server.py http://127.0.0.1:8020 <token>
  python3 e2e_server.py https://你的域名/md2word <token>
"""
import json
import re
import sys
import urllib.error
import urllib.request

HEAD_RE = re.compile(
    r"Version:0\.9\r?\n"
    r"StartHTML:(\d{10})\r?\n"
    r"EndHTML:(\d{10})\r?\n"
    r"StartFragment:(\d{10})\r?\n"
    r"EndFragment:(\d{10})\r?\n"
)

MD = ("# 端到端测试\n\n这是**中文正文**，含 `行内代码`。\n\n"
      "| 指标 | 数值 |\n|---|---|\n| 精度 | 0.95 |\n\n"
      "行内公式 $E=mc^2$，块级：\n\n$$\\int_0^1 x^2 dx = \\frac{1}{3}$$\n")

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name:26s} {detail}")


def get(url, timeout=20):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.read()


def post(url, token, payload, timeout=60):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "X-Md2W-Token": token or ""},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def main(base, token):
    base = base.rstrip("/")
    print(f"目标: {base}")

    for path, name in (("/", "首页"), ("/extension-bridge.js", "桥接脚本")):
        try:
            st, body = get(base + path)
            check(name, st == 200 and len(body) > 50, f"{st}, {len(body)}B")
            if path == "/":
                check("页面引用桥接脚本", b"extension-bridge.js" in body)
        except Exception as e:                                   # noqa: BLE001
            check(name, False, repr(e)[:80])

    try:
        st, body = get(base + "/api/presets")
        d = json.loads(body)
        n = len(d.get("presets") or [])
        check("预设列表", st == 200 and d.get("ok") and n >= 1, f"{n} 个预设")
    except Exception as e:                                       # noqa: BLE001
        check("预设列表", False, repr(e)[:80])

    st, _ = post(base + "/api/clip", "", {"md": MD})
    check("无令牌必须 401", st == 401, f"status={st}")
    st, _ = post(base + "/api/clip", "wrong-token-0123456789", {"md": MD})
    check("错令牌必须 401", st == 401, f"status={st}")

    st, body = post(base + "/api/clip", token, {"md": MD})
    if st != 200:
        check("带令牌转换", False, f"status={st} {body[:120]}")
    else:
        d = json.loads(body)
        cf = d.get("cfhtml") or ""
        check("带令牌转换", d.get("ok") and bool(cf), f"html={len(d.get('html',''))}B cf={len(cf)}B")
        m = HEAD_RE.match(cf)
        check("cfhtml 头部格式", bool(m))
        if m:
            sh, eh, sf, ef = map(int, m.groups())
            b = cf.encode("utf-8")
            check("cfhtml 偏移是字节", eh == len(b) and ef <= eh, f"EndHTML={eh} 实际={len(b)}")
            frag = b[sf:ef].decode("utf-8", "replace")
            check("片段含 Word 样式", ("mso-" in frag) or ("xmlns:w" in frag))
            check("片段含样式表", "<style" in cf[:sf + 3000])
            check("片段含中文正文", "中文正文" in frag)

    print()
    bad = [n for n, ok, _ in results if not ok]
    print(f"RESULT: {'PASS' if not bad else 'FAIL'}  ({len(results) - len(bad)}/{len(results)})")
    if bad:
        print("未通过:", ", ".join(bad))
    return 0 if not bad else 1


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
