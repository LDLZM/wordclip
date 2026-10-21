#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wordclip.py —— 把 Markdown 转成「可直接粘进 Word/WPS 的剪贴板 HTML」

为什么不能直接把网页 HTML 丢进剪贴板：
  Word 粘贴时只认 (a) 内联 style，或 (b) 它自己的 mso-* 私有属性。
  网页靠 <style> 里的 class 规则，Word 一律忽略 → 字体/字号/间距全丢。

因此这里做三件事：
  1) 每个元素的样式全部内联化，不依赖任何 class；
  2) 用 mso-style-name:"标题 N" 让 Word 识别为真正的内置标题样式
     → 导航窗格、自动目录、多级编号都能正常工作；
  3) 用 Word 认识的 HTML 外壳（@page / WordSection1 / StartFragment 标记）
     封装，保证打开时不弹兼容模式、页边距正确。
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# ---------- 与 ref.docx 保持一致的排版常量 ----------
BODY_PT = 12          # 小四
BODY_LH = 150         # 1.5 倍行距（百分比）
CODE_PT = 10.5        # 五号
H_PT = {1: 16, 2: 14, 3: 12, 4: 12, 5: 10.5, 6: 10.5}
H_SPACE = {1: (12, 6), 2: (12, 6), 3: (6, 6), 4: (6, 3), 5: (6, 3), 6: (6, 3)}
FONT_CN = "宋体"
FONT_CN_TITLE = "黑体"
FONT_CN_QUOTE = "楷体"
FONT_EN = "Times New Roman"
FONT_MONO = "Consolas"
TEXT_INDENT = "2em"


def apply_cfg(cfg: dict):
    """把排版配置写进本模块常量，供 to_clip_html 使用。

    与 build_reference.build_variant 同理：这里也是临时改全局再恢复，
    调用方必须加锁串行化，否则多线程会互相踩踏。
    """
    global BODY_PT, BODY_LH, CODE_PT, H_PT, FONT_CN, FONT_CN_TITLE, FONT_EN, TEXT_INDENT
    saved = dict(BODY_PT=BODY_PT, BODY_LH=BODY_LH, CODE_PT=CODE_PT, H_PT=H_PT,
                 FONT_CN=FONT_CN, FONT_CN_TITLE=FONT_CN_TITLE, FONT_EN=FONT_EN,
                 TEXT_INDENT=TEXT_INDENT)

    build_sizes = {
        "小二": 18, "三号": 16, "小三": 15, "四号": 14,
        "小四": 12, "五号": 10.5, "小五": 9,
    }
    body = build_sizes.get(cfg.get("body_size", "小四"), 12)
    BODY_PT = body
    CODE_PT = build_sizes.get(cfg.get("code_size", "五号"), 10.5)
    # 标题字号直接取配置值；标题3 以下沿用正文大小，避免出现"标题比正文还小"
    h1 = build_sizes.get(cfg.get("h1_size", "三号"), 16)
    h2 = build_sizes.get(cfg.get("h2_size", "四号"), 14)
    h3 = body
    H_PT = {1: h1, 2: h2, 3: h3, 4: h3,
            5: round(CODE_PT), 6: round(CODE_PT)}

    rule = str(cfg.get("line_rule", "1.5"))
    if rule.startswith("固定"):
        # 固定磅值 -> 百分比（相对当前正文字号）
        fixed = float(rule.replace("固定", "").replace("磅", ""))
        BODY_LH = max(100, round(fixed / body * 100))
    else:
        BODY_LH = round(float(rule) * 100)

    FONT_CN = cfg.get("body_font", "宋体")
    FONT_CN_TITLE = cfg.get("head_font", "黑体")
    FONT_EN = cfg.get("body_latin", "Times New Roman")

    ic = int(cfg.get("indent_chars", 2))
    TEXT_INDENT = "0" if ic == 0 else f"{ic}em"
    return saved


def restore_cfg(saved: dict):
    global BODY_PT, BODY_LH, CODE_PT, H_PT, FONT_CN, FONT_CN_TITLE, FONT_EN, TEXT_INDENT
    for k, v in saved.items():
        globals()[k] = v


def font(cn, en=FONT_EN):
    return f"{cn},{en}"


def pandoc_html(md: str) -> str:
    p = subprocess.run(
        ["pandoc",
         "-f", "markdown+tex_math_dollars+pipe_tables+footnotes+strikeout+task_lists",
         "-t", "html5", "--wrap=none", "--no-highlight"],
        input=md, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("pandoc 转换失败: " + p.stderr[:500])
    return p.stdout


# ---------------------------------------------------------------- 样式变换
def _p(m):
    inner = m.group(1)
    st = (f"margin:0;text-align:justify;text-justify:inter-ideograph;"
          f"text-indent:{TEXT_INDENT};line-height:{BODY_LH}%;"
          f"font-family:{font(FONT_CN)};font-size:{BODY_PT}pt;")
    # 行内代码 / 公式 / 链接的样式都写在子 span 上，必须在 p 里显式声明
    # "子元素字体优先"，否则 Word 会以父段落的宋体 12pt 统一覆盖，
    # 导致代码和公式失去等宽特征。
    inner = re.sub(r"<(code|span)(?=[\s>])", r"<\1 data-inl=\"1\"", inner)
    return f"<p style=\"{st}\">{inner}</p>"


def _h(lvl):
    before, after = H_SPACE[lvl]
    align = "center" if lvl == 1 else "left"
    # 注意：mso-style-name 的值要写在**单引号**里，
    # 因为整个 style 属性用双引号包裹，写双引号会把属性截断。
    st = (f"margin:{before}pt 0 {after}pt 0;text-align:{align};text-indent:0;"
          f"line-height:130%;font-family:{font(FONT_CN_TITLE)};font-weight:bold;"
          f"font-size:{H_PT[lvl]}pt;color:#000000;"
          f"mso-style-name:'标题 {lvl}';mso-outline-level:{lvl};")
    return st


def _th(m):
    full = m.group(0)
    align = "center"
    am = re.search(r'data-al="(\w+)"', full)
    if am:
        align = am.group(1)
    wm = re.search(r'data-w="([\d.]+(?:pt|%))"', full)
    wcss = f"width:{wm.group(1)};" if wm else ""
    st = (f"{wcss}border:none;border-bottom:0.75pt solid #000000;"
          f"padding:4pt 8pt;mso-padding-alt:4pt 8pt;"
          f"text-align:{align};vertical-align:middle;"
          f"font-family:{font(FONT_CN)};font-size:{BODY_PT}pt;font-weight:bold;")
    return f"<th style=\"{st}\">{m.group(1)}</th>"


def _td(m):
    # pandoc 会带 align 属性，转成 text-align 内联
    inner, attrs = m.group(1), m.group(0)
    align = "left"
    am = re.search(r'align="(\w+)"', attrs)
    if am:
        align = am.group(1)
    wm = re.search(r'data-w="([\d.]+(?:pt|%))"', attrs)
    wcss = f"width:{wm.group(1)};" if wm else ""
    st = (f"{wcss}border:none;padding:4pt 8pt;mso-padding-alt:4pt 8pt;"
          f"text-align:{align};vertical-align:middle;"
          f"font-family:{font(FONT_CN)};font-size:{BODY_PT}pt;")
    return f"<td style=\"{st}\">{inner}</td>"


def _inline_code(m):
    st = (f"font-family:{FONT_MONO},{FONT_CN};font-size:{CODE_PT}pt;"
          f"background:#F2F2F2;")
    return f"<span style=\"{st}\">{m.group(1)}</span>"


def _math(m):
    # pandoc 的 math 只是纯文本，Word 里无法直接渲染 LaTeX。
    # 注意：不能加 background / 颜色块 —— 那在 Word 里会变成难看的色块，
    # 用户明确要求"不出多余符号、字体不出现过小过大的跳变"。
    st = (f"font-family:{FONT_MONO},{FONT_CN};font-size:{BODY_PT}pt;"
          f"color:#000000;white-space:nowrap;")
    return f"<span style=\"{st}\">{m.group(1)}</span>"


def _display_math(m):
    """行间公式：独立成段、居中、无首行缩进。
    之前被当成普通段落处理，带上了 2em 缩进，看起来像正文而不是公式。"""
    st = (f"margin:6pt 0;text-align:center;text-indent:0;line-height:{BODY_LH}%;"
          f"font-family:{FONT_MONO},{FONT_CN};font-size:{BODY_PT}pt;"
          f"color:#000000;white-space:nowrap;")
    return f"<p data-dm=\"1\" style=\"{st}\">{m.group(1)}</p>"


BULLET = "\u2022"          # •
BULLET_SUB = "\u25e6"      # ◦ 二级列表


def _convert_lists(body: str) -> str:
    """把 <ul>/<ol>/<li> 拆成普通段落，标记符号写成真实字符。

    为什么不用浏览器式的 list-style：
      Word / WPS / LibreOffice 各自用私有符号字体实现自动列表，
      写进剪贴板的 HTML 一旦被"翻译"到 Word，符号往往丢失或错位。
      直接写字符则三者一致，且用户能像普通文字一样编辑。

    嵌套处理：用栈记录当前层级，缩进按层递增。
    """
    out = []
    stack = []          # 每项: {"tag":"ul"/"ol", "n":计数}
    # 逐个 token 扫描，保留非列表内容
    pos = 0
    for m in re.finditer(r"<(/?)(ul|ol|li)\b[^>]*>", body):
        out.append(body[pos:m.start()])
        pos = m.end()
        closing, tag = m.group(1), m.group(2)

        if tag in ("ul", "ol") and not closing:
            stack.append({"tag": tag, "n": 0})
            continue
        if tag in ("ul", "ol") and closing:
            if stack:
                stack.pop()
            continue
        if tag == "li" and not closing:
            depth = max(len(stack) - 1, 0)
            if stack:
                stack[-1]["n"] += 1
                idx = stack[-1]["n"]
                top_is_ol = stack[-1]["tag"] == "ol"
            else:
                idx, top_is_ol = 1, False
            if top_is_ol:
                mark = f"{idx}. "
            else:
                mark = (BULLET if depth == 0 else BULLET_SUB) + "\u2002"
            # 缩进：每层 21pt（约 2 字符），符号与文字间用固定宽度的空格隔开
            ml = 21 * (depth + 1)
            st = (f"margin:2pt 0 2pt {ml}pt;text-indent:-10.5pt;"
                  f"text-align:justify;line-height:{BODY_LH}%;"
                  f"font-family:{font(FONT_CN)};font-size:{BODY_PT}pt;")
            out.append(f"<p style=\"{st}\">"
                       f"<span style=\"font-family:{FONT_CN};font-size:{BODY_PT}pt;\">"
                       f"{mark}</span>")
            continue
        if tag == "li" and closing:
            out.append("</p>")
            continue

    out.append(body[pos:])
    return "".join(out)


def inline_styles(body: str) -> str:
    # 0) 先把代码块的【内容】抽出来保护起来。原因：
    #    pandoc 输出的是 <pre><code>...</code></pre>，<code> 在里面。
    #    如果先跑行内代码规则，会把 <code> 换成带浅底的 span，
    #    再回头剥 span 时容易连整块 <pre> 一起吃掉（曾导致代码块整段消失）。
    #    做法：把 <pre> 内部内容换成占位符，全部处理完最后再放回去。
    pres = []

    def _stash(m):
        inner = m.group(1)
        inner = re.sub(r"</?code[^>]*>", "", inner)   # 去掉内层 code 包裹
        inner = re.sub(r"</?span[^>]*>", "", inner)   # 去掉任何高亮 span
        pres.append(inner)
        return f"@@PRE{len(pres) - 1}@@"

    body = re.sub(r"<pre[^>]*>(.*?)</pre>", _stash, body, flags=re.S)

    # 1) 先把行内代码 / 公式 / 链接处理掉（它们可能嵌在 p/h 里）
    body = re.sub(r'<code[^>]*>(.*?)</code>', _inline_code, body, flags=re.S)
    #    行间公式必须排在行内公式之前，否则 $$...$$ 会被 inline 规则先吃掉
    body = re.sub(r'<span class="math display">(.*?)</span>',
                  _display_math, body, flags=re.S)
    body = re.sub(r'<span class="math inline">(.*?)</span>',
                  _math, body, flags=re.S)
    body = re.sub(r'<a href="([^"]*)"[^>]*>',
                  r'<a href="\1" style="color:#0563C1;text-decoration:underline;">',
                  body)

    # 2) 标题（先于 <p>，避免 <h> 内部的 <p> 干扰；pandoc 不会这么嵌套）
    for lvl in range(1, 7):
        st = _h(lvl)
        body = re.sub(rf"<h{lvl}[^>]*>(.*?)</h{lvl}>",
                      lambda m, s=st, l=lvl: f"<h{l} style=\"{s}\">{m.group(1)}</h{l}>",
                      body, flags=re.S)

    # 3) 正文段落
    #    公式段落（data-dm）跳过：它的样式是居中+等宽，
    #    如果套上正文的 2em 缩进和宋体，会变成"一个带缩进的公式行"。
    body = re.sub(
        r"<p(?![^>]*data-dm)(?:\s[^>]*)?>(.*?)</p>", _p, body, flags=re.S)

    # 4) 列表：把标记符号当普通字符写进段落。
    #    实测结论（隔离实验，三个软件对比）：
    #      - list-style-type 在 LibreOffice 里会生成私有区字符（\\ue008），
    #        依赖软件自己造的符号字体，Word 拿不到这个字体 → 符号不显示；
    #      - 这就是"网页里好好的列表，粘到 Word 里符号全没了"的原因。
    #    因此这里把 ul/ol 拆成普通 <p>，符号直接写字符，
    #    靠 margin-left 控制缩进。三个软件渲染完全一致。
    body = _convert_lists(body)

    # 5) 引用
    body = body.replace(
        "<blockquote>",
        f"<blockquote style=\"margin:6pt 24pt;padding:0;border:none;"
        f"font-family:{font(FONT_CN_QUOTE)};font-size:{BODY_PT}pt;text-indent:0;\">")

    # 6) 代码块（内容已在第 0 步抽走，这里只处理外壳和占位符还原）
    body = re.sub(
        r"@@PRE(\d+)@@",
        lambda m: (
            f"<pre style=\"margin:6pt 0;padding:6pt 8pt;background:#F7F7F7;border:none;"
            f"font-family:{FONT_MONO},{FONT_CN};font-size:{CODE_PT}pt;line-height:130%;"
            f"text-indent:0;white-space:pre-wrap;mso-page-break-inside:avoid;\">"
            f"{pres[int(m.group(1))]}</pre>"),
        body)

    # 7) 表格：三线表
    #    要点：
    #    a) <thead>/<tbody> 在 Word 的 HTML 解析里不稳定，常导致
    #       "表头整行跑到表格外面"。这里展开成普通行，表头靠 th 的
    #       粗体 + 下框线标识，跨页重复由 Word 自身处理。
    #    b) 表格标签间的换行会被 Word 当成空行渲染在表格上方，要压掉。
    #    c) 列宽给显式宽度，否则 Word 按内容自适应，容易宽窄失衡。
    def _table(m):
        inner = m.group(1)
        inner = re.sub(r"</?(thead|tbody|colgroup)[^>]*>", "", inner)
        inner = re.sub(r">\s+<", "><", inner)          # 压掉标签间空白
        inner = re.sub(r"<th style=\"text-align: (\w+);\">",
                       lambda x: f"<th data-al=\"{x.group(1)}\">", inner)
        # 列宽：按内容长度分配权重，而不是平均分。
        #   平均分会让"数值列"过宽、"文字列"被挤成一字；
        #   按字数加权（并给每列保底 12%）更接近人手的排版直觉。
        first_row = re.search(r"<tr[^>]*>(.*?)</tr>", inner, re.S)
        heads = re.findall(r"<th[^>]*>(.*?)</th>", first_row.group(1), re.S) if first_row else []
        if not heads:
            heads = ["列"]
        # 每个单元格内容长度（去标签）
        rows_all = re.findall(r"<tr[^>]*>(.*?)</tr>", inner, re.S)
        weights = []
        for ci in range(len(heads)):
            lens = []
            for r in rows_all:
                cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)
                if ci < len(cells):
                    txt = re.sub(r"<[^>]+>", "", cells[ci])
                    lens.append(len(txt.strip()))
            weights.append(max([len(re.sub(r"<[^>]+>", "", h)) for h in [heads[ci]]] + lens))
        # 保底 12%，避免某列被压成一个字
        minw = 0.12
        total = sum(weights) or 1
        raw = [max(minw, w / total) for w in weights]
        s = sum(raw)
        # 百分比宽度实测在 LibreOffice / Word 的 HTML 粘贴里常被忽略，
        # 于是所有列平均分，短列被撑得很宽。改用固定 pt 宽度：
        # 版心 415pt（A4 585pt 减左右各 90pt 的页边距）。
        TEXT_W = 415.0
        widths = [round(x / s * TEXT_W, 1) for x in raw]
        # 最后一列不给宽度，让它吃掉剩余的像素，避免舍入误差撑破版心
        wpts = [f"{w}pt" for w in widths[:-1]]

        def _cell(m):
            tag = m.group(1)
            i = _cell.i % len(heads)
            _cell.i += 1
            w = wpts[i] if i < len(wpts) else ""
            return f'<{tag} data-w="{w}"'

        _cell.i = 0
        inner = re.sub(r"<(td|th)(?=[\s>])", _cell, inner)
        return (f"<table cellspacing=\"0\" cellpadding=\"0\" border=\"0\" "
                f"style=\"border-collapse:collapse;margin:6pt auto;width:100%;"
                f"border-top:1.5pt solid #000000;"
                f"border-bottom:1.5pt solid #000000;\">{inner}</table>")

    body = re.sub(r"<table[^>]*>(.*?)</table>", _table, body, flags=re.S)
    body = re.sub(r"<th[^>]*>(.*?)</th>", _th, body, flags=re.S)
    body = re.sub(r"<td[^>]*>(.*?)</td>", _td, body, flags=re.S)

    # 8) 图注
    body = re.sub(
        r"<figcaption>(.*?)</figcaption>",
        f"<p style=\"margin:3pt 0 6pt 0;text-align:center;text-indent:0;"
        f"font-family:{font(FONT_CN)};font-size:{CODE_PT}pt;font-weight:bold;\">\\1</p>",
        body, flags=re.S)

    return body


# ---------------------------------------------------------------- 外壳
CLIP_HEAD = (
    '<html xmlns:o="urn:schemas-microsoft-com:office:office" '
    'xmlns:w="urn:schemas-microsoft-com:office:word" '
    'xmlns="http://www.w3.org/TR/REC-html40">\n'
    '<head>\n'
    '<meta http-equiv="Content-Type" content="text/html; charset=utf-8">\n'
    '<!--[if gte mso 9]><xml><w:WordDocument><w:View>Print</w:View>'
    '<w:Zoom>100</w:Zoom><w:DoNotOptimizeForBrowser/></w:WordDocument></xml><![endif]-->\n'
    '<style>\n'
    # Word 只认它自己能解析的 @page 写法。经验：
    #   size 和 margin 分开写，且用一个不叫 WordSection1 的通用 @page 兜底，
    #   否则某些版本（含 LibreOffice 导入路径）会直接忽略整条规则，
    #   导致页边距变成默认值 —— 表现为正文顶到纸张最右边、右侧出血。
    '@page WordSection1 {size:595.3pt 841.9pt;}\n'
    '@page {size:595.3pt 841.9pt;}\n'
    '@page {margin:72.0pt 90.0pt 72.0pt 90.0pt;}\n'
    'div.WordSection1 {page:WordSection1;}\n'
    f'body {{font-family:{FONT_CN},{FONT_EN}; font-size:{BODY_PT}pt;}}\n'
    f'p.MsoNormal, li.MsoNormal {{margin:0; font-size:{BODY_PT}pt; '
    f'font-family:{FONT_CN},{FONT_EN};}}\n'
    '</style>\n</head>\n<body lang="ZH-CN">\n<div class="WordSection1">\n'
    '<!--StartFragment-->\n'
)

CLIP_TAIL = "\n<!--EndFragment-->\n</div>\n</body>\n</html>\n"


def to_clip_html(md: str) -> str:
    body = inline_styles(pandoc_html(md))
    return CLIP_HEAD + body + CLIP_TAIL


def tidy(s: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", s)


if __name__ == "__main__":
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    md = src.read_text(encoding="utf-8") if src else sys.stdin.read()
    sys.stdout.write(tidy(to_clip_html(md)))
