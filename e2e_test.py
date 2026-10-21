#!/usr/bin/env python3
"""端到端测试 md2word 服务的两个接口。"""
import json
import urllib.request
import zipfile
import re

BASE = "http://127.0.0.1:8020"
MD = open("/tmp/sample_clean.md", encoding="utf-8").read()


def post(path, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        BASE + path, data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST")
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.read(), r.headers.get("Content-Type", "")


print("=" * 60)
print("1) /api/docx")
raw, ctype = post("/api/docx", {"md": MD, "title": "测试文档"})
print("   content-type:", ctype)
print("   bytes:", len(raw))
open("/tmp/e2e_out.docx", "wb").write(raw)
z = zipfile.ZipFile("/tmp/e2e_out.docx")
doc = z.read("word/document.xml").decode("utf-8")
print("   zip ok, entries:", len(z.namelist()))
print("   Heading1 count:", doc.count('w:val="Heading1"'))
print("   Heading2 count:", doc.count('w:val="Heading2"'))
print("   FirstParagraph:", doc.count('w:val="FirstParagraph"'))
print("   Table style:", doc.count('w:val="Table"'))
print("   SourceCode:", doc.count('w:val="SourceCode"'))
print("   OMML equations:", doc.count("<m:oMath"))
print("   tbl elements:", doc.count("<w:tbl>"))

print()
print("2) /api/clip")
raw2, ctype2 = post("/api/clip", {"md": MD})
payload = json.loads(raw2.decode("utf-8"))
html = payload["html"]
print("   content-type:", ctype2)
print("   bytes:", len(html))
open("/tmp/e2e_clip.html", "w", encoding="utf-8").write(html)

checks = {
    "中文首行缩进 2em": "text-indent:2em",
    "行高 1.5": "line-height:150%",
    "宋体": "宋体",
    "小四 12pt": "font-size:12pt",
    "mso 标题样式": "mso-style-name:'标题 1'",
    "表格边框": "border-top",
    # 以下三项是"粘贴到 Word 会乱"的三个直接原因，缺一不可
    "列表符号为真实字符": "\u2022",
    "无 ul/ol/li 残留": "list-style",
    "表格固定列宽": "width:1",
    "页边距独立规则": "@page {margin",
}
for name, needle in checks.items():
    ok = (needle in html) if name != "无 ul/ol/li 残留" else (needle not in html)
    print("   %-18s %s" % (name, "OK" if ok else "MISSING"))

# 关键：属性值里不能出现裸双引号（会截断 HTML）
bad = re.findall(r'style="[^"]*"[^ >]', html)
print("   裸双引号破坏属性:", "无" if not bad else bad[:3])
print("   <table> 数量:", html.count("<table"))
print("   <h1>/<h2> 数量:", html.count("<h1"), "/", html.count("<h2"))
