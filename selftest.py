#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
selftest.py —— wordclip 输出的自动化校验

检查项：
  1) HTML 属性完整性：style="..." 内部不能再出现双引号（会截断属性）
  2) 关键样式全部内联命中：字号/行距/缩进/中文字体/mso 样式名
  3) 没有残留 class 依赖（Word 不认 class）
  4) 剪贴板外壳标记 StartFragment / EndFragment 成对出现
  5) 表格、代码块、列表、标题各元素都有内联样式
"""
import re
import subprocess
import sys
from html.parser import HTMLParser

SRC = "/opt/md2word/wordclip.py"
SAMPLE = "/opt/md2word/sample.md"

fails, warns = [], []


def check(cond, msg):
    if cond:
        print(f"  ✓ {msg}")
    else:
        print(f"  ✗ {msg}")
        fails.append(msg)


print("=" * 62)
print("wordclip 输出校验")
print("=" * 62)

html = subprocess.run([sys.executable, SRC, SAMPLE], capture_output=True, text=True)
if html.returncode != 0:
    print("生成失败:", html.stderr[:800]); sys.exit(1)
h = html.stdout

# ---- 1) 属性解析完整性：用 HTMLParser 逐标签检查 ----
print("\n[1] HTML 结构（属性是否被截断）")


class P(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.broken = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        # HTMLParser 会尽力解析；若 style 值里出现多余引号，
        # 会产生形如 ('1', None) 这种怪异属性名
        for k, v in attrs:
            if k is None or k.strip() == "":
                self.broken.append(tag)


p = P(); p.feed(h)
check(not p.broken, f"所有标签属性均可解析（异常标签 {p.broken[:5]}）")
tags = [t for t, _ in p.tags]
print(f"    标签统计: h1={tags.count('h1')} h2={tags.count('h2')} "
      f"h3={tags.count('h3')} p={tags.count('p')} li={tags.count('li')} "
      f"table={tags.count('table')} pre={tags.count('pre')}")

# ---- 2) style 属性内部无反引号/双引号 ----
print("\n[2] style 属性内部引号安全")
style_vals = [a.get("style", "") for t, a in p.tags if "style" in a]
bad = [s for s in style_vals if '"' in s]
check(not bad, f"{len(style_vals)} 个 style 属性内部无裸双引号（违规 {len(bad)} 个）")
for b in bad[:3]:
    print("     违例:", b[:100])

# ---- 3) 关键内联样式命中 ----
print("\n[3] 关键排版样式内联")
check("font-family:宋体" in h, "正文中文字体=宋体")
check("font-family:黑体" in h, "标题中文字体=黑体")
check("Times New Roman" in h, "英文/数字字体=Times New Roman")
check("font-size:12pt" in h, "正文字号=12pt(小四)")
check("text-indent:2em" in h, "首行缩进=2em")
check("line-height:150%" in h, "行距=150%")
check("text-align:justify" in h, "两端对齐")
check("mso-style-name:'标题 1'" in h, "标题1 映射到 Word 内置样式")
check("mso-outline-level:1" in h, "标题1 写入大纲级别（导航窗格可用）")
check("font-size:16pt" in h, "标题1 字号=16pt(三号)")
check("font-size:14pt" in h, "标题2 字号=14pt(四号)")
check("Consolas" in h, "代码等宽字体=Consolas")
check("border-top:1.5pt solid" in h, "表格顶线（三线表）")
check("border-bottom:0.75pt solid" in h, "表头下细线（三线表）")

# ---- 4) 不应残留依赖 class 的样式 ----
print("\n[4] 无 class 依赖")
body_only = h.split("<!--StartFragment-->")[1] if "StartFragment" in h else h
cls = re.findall(r'class="([^"]*)"', body_only)
check(all(c in ("", "WordSection1") for c in cls) or not cls,
      f"正文片段内无 style class 依赖（发现 {set(cls) or '无'}）")

# ---- 5) 剪贴板外壳 ----
print("\n[5] Word 剪贴板外壳")
check("<!--StartFragment-->" in h, "含 StartFragment 标记")
check("<!--EndFragment-->" in h, "含 EndFragment 标记")
check('xmlns:w="urn:schemas-microsoft-com:office:word"' in h, "含 Word 命名空间")
check("@page WordSection1" in h, "含 @page 页面设置")
check('lang="ZH-CN"' in h, "body 声明中文语言（避免 Word 用英文字体）")

# ---- 6) 每个内容标签都带 style ----
print("\n[6] 内容元素是否都带内联样式")
missing = [(t, a) for t, a in p.tags
           if t in ("p", "h1", "h2", "h3", "h4", "li", "table", "pre", "th", "td", "ul", "ol")
           and "style" not in a]
check(not missing, f"所有结构性元素均带 style（缺失 {len(missing)} 个）")
for m in missing[:5]:
    print("     缺失:", m[0])

# ---- 7) 列表符号写成真实字符（不依赖 list-style） ----
print("\n[7] 列表符号")
check(tags.count("ul") == 0 and tags.count("ol") == 0 and tags.count("li") == 0,
      "无 ul/ol/li 标签（避免私有区符号字体在 Word 中丢失）")
check("\u2022" in h, "项目符号为真实字符 U+2022")
check("list-style" not in h, "未使用 list-style（Word 不会丢符号）")
# 每个项目符号后面必须紧跟内容，不能是空段
items = re.findall(r'<span[^>]*>(\u2022|\u25e6)[\u2000-\u200a\u3000 ]*</span>(.{0,3})', h)
check(len(items) >= 2, f"项目符号条目数 {len(items)}")
check(all(t.strip() for _, t in items), "每个项目符号后都有正文（无空条目）")

# ---- 8) 表格列宽 / 字号一致性 ----
print("\n[8] 表格")
check("border-collapse:collapse" in h, "表格使用 border-collapse（Word 需此才画三线表）")
w = re.findall(r'<t[dh] style="width:([\d.]+)pt;', h)
check(len(w) >= 3, f"以固定 pt 给出列宽（{len(w)} 个单元格有宽度）")
# 表头与表体字号必须一致，否则出现"表头特别大"的观感
th_sizes = {s for s in re.findall(r'<th style="[^"]*font-size:([\d.]+)pt', h)}
td_sizes = {s for s in re.findall(r'<td style="[^"]*font-size:([\d.]+)pt', h)}
check(th_sizes == td_sizes == {"12" if "font-size:12pt" in h else list(td_sizes)[0] if td_sizes else ""},
      f"表头与表体字号一致（th={th_sizes} td={td_sizes}）")

# ---- 9) 页边距：不能让正文越过版心 ----
print("\n[9] 页面设置")
marg = re.findall(r"@page[^{]*\{([^}]*)\}", h)
check(any("margin" in m for m in marg), "@page 含独立 margin 规则")
check(any("size" in m for m in marg), "@page 含独立 size 规则")
check(len([m for m in marg if "margin" in m and "size" in m]) == 0,
      "size 与 margin 未合并成一条（合并会被 Word/LibreOffice 忽略导致右侧溢出）")


print("\n" + "=" * 62)
if fails:
    print(f"结果: 失败 {len(fails)} 项")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("结果: 全部通过")
