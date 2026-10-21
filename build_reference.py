#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_reference.py —— 生成 md2word 的 Word 排版基准模板 (reference.docx)

设计目标（中文文档通用规范，偏向学术/技术/正式报告）：
  - 正文：宋体 / Times New Roman，小四(12pt)，1.5 倍行距，首行缩进 2 字符，段前段后 0
  - 标题1：三号(16pt) 黑体 加粗 居中，段前 1 行 段后 0.5 行 —— 章标题
  - 标题2：四号(14pt) 黑体 加粗 左对齐，段前 0.5 行
  - 标题3：小四(12pt) 黑体 加粗 左对齐
  - 标题层级写入 outlineLvl → Word 导航窗格可见、可自动生成目录
  - 代码：Consolas / 等线，五号(10.5pt)，浅灰底纹，保留缩进
  - 表格：三线表风格（顶粗线、表头下细线、底部粗线），表头加粗居中
  - 页面：A4，上下 2.54cm，左右 3.17cm（Word 默认）
  - 中英文分别指定字体（rFonts ascii/hAnsi vs eastAsia），不让 Word 用主题色/主题字体
    → 这样 WPS 打开也不会变样

用法：python3 build_reference.py [输出路径]
"""
import shutil
import sys
import zipfile
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "ref.docx"

# ---- 字号（Word 半磅值：sz = pt*2）----
SZ_XIAOSI   = 24   # 小四 12pt   正文
SZ_WUHAO    = 21   # 五号 10.5pt 代码/表格
SZ_SIHAO    = 28   # 四号 14pt   标题2
SZ_XIAOSAN  = 30   # 小三 15pt   标题3 备选
SZ_SANHAO   = 32   # 三号 16pt   标题1
SZ_ERHAO    = 44   # 二号 22pt   文档标题
SZ_XIAOER   = 36   # 小二 18pt

SONG = "宋体"
HEI  = "黑体"
KAI  = "楷体"
MONO_CN = "等线"
MONO_EN = "Consolas"

# 这些由 build_variant() 按用户配置覆盖；单独跑本文件时用默认值
BODY_LINE = 360          # 1.5 倍：240*1.5
BODY_LINE_RULE = "auto"
BODY_INDENT_CHARS = 2
BODY_LATIN = "Times New Roman"

# ============================================================
#  可配置排版 —— 预设方案 + 单项覆盖
# ============================================================
# 说明：用户在网页上可以选择预设，也可以逐项改。
# 所有值最终都落到下面这些模块级常量上，build() 再用它们生成 ref.docx。
# 为什么要用"改常量"这种土办法：build() 内部几十处直接引用 SONG/SZ_XIAOSI 等，
# 改成传参要动上百行、极易引入 bug；这里在 build 前后做快照/恢复，干净且安全。

# 中文字号表（pt）。只给常见且 Windows/WPS 都自带的字号，避免"在别人电脑上变样"。
FONT_SIZES_PT = {
    "小二": 18.0, "三号": 16.0, "小三": 15.0, "四号": 14.0,
    "小四": 12.0, "五号": 10.5, "小五": 9.0,
}

# 中文字体白名单：只列 Windows 与 WPS 基本都有的
CN_FONTS = ["宋体", "黑体", "楷体", "仿宋", "微软雅黑", "等线", "思源宋体"]
# 西文字体白名单
EN_FONTS = ["Times New Roman", "Arial", "Calibri", "Cambria"]

# 行距：auto 用倍数，fixed 用固定磅值
LINE_RULES = ["1.0", "1.15", "1.5", "1.75", "2.0", "固定28磅", "固定20磅"]

DEFAULT_STYLE = {
    "body_font":   "宋体",
    "body_latin":  "Times New Roman",
    "body_size":   "小四",
    "line_rule":   "1.5",
    "indent_chars": 2,
    "head_font":   "黑体",
    "h1_size":     "三号",
    "h2_size":     "四号",
    "h3_size":     "小四",
    "title_size":  "小二",
    "code_size":   "五号",
}

# 预设方案。每套说明它适合什么场景，网页上直接显示。
PRESETS = {
    "thesis": {
        "name": "毕业论文 / 课程论文",
        "desc": "宋体小四、1.5 倍行距、首行缩进 2 字、标题黑体居中。多数高校论文格式要求。",
        "cfg": dict(DEFAULT_STYLE),
    },
    "report": {
        "name": "工作报告 / 内部汇报",
        "desc": "微软雅黑、行距 1.5 倍、首行不缩进、标题加粗。看起来现代、适合投屏。",
        "cfg": {**DEFAULT_STYLE, "body_font": "微软雅黑", "body_latin": "Calibri",
                "indent_chars": 0, "line_rule": "1.5", "head_font": "微软雅黑",
                "h1_size": "四号", "h2_size": "小四", "title_size": "小二"},
    },
    "official": {
        "name": "公文 / 红头文件风格",
        "desc": "仿宋三号、固定行距 28 磅、首行缩进 2 字。近似党政机关公文格式。",
        "cfg": {**DEFAULT_STYLE, "body_font": "仿宋", "body_latin": "Times New Roman",
                "body_size": "三号", "line_rule": "固定28磅", "indent_chars": 2,
                "head_font": "黑体", "h1_size": "三号", "h2_size": "三号",
                "h3_size": "三号", "title_size": "小二"},
    },
    "tech": {
        "name": "技术文档 / 说明手册",
        "desc": "等线、行距 1.15、不缩进，标题字号差异小。适合贴代码和表格。",
        "cfg": {**DEFAULT_STYLE, "body_font": "等线", "body_latin": "Calibri",
                "body_size": "五号", "line_rule": "1.15", "indent_chars": 0,
                "head_font": "微软雅黑", "h1_size": "四号", "h2_size": "小四",
                "h3_size": "五号", "title_size": "三号", "code_size": "小五"},
    },
    "note": {
        "name": "读书笔记 / 随手记录",
        "desc": "楷体、1.75 倍行距、首行缩进 2 字。读起来松弛，适合长篇。",
        "cfg": {**DEFAULT_STYLE, "body_font": "楷体", "body_latin": "Times New Roman",
                "body_size": "小四", "line_rule": "1.75", "indent_chars": 2,
                "head_font": "黑体"},
    },
}


def normalize_cfg(raw) -> dict:
    """把前端传来的配置洗成安全值。任何不认识的值一律回退默认，绝不抛异常。"""
    cfg = dict(DEFAULT_STYLE)
    if not isinstance(raw, dict):
        return cfg
    if raw.get("preset") in PRESETS:
        cfg.update(PRESETS[raw["preset"]]["cfg"])

    # 逐项合法值校验（不允许前端塞任意字体名：字体不存在时 Word 会乱替换）
    if raw.get("body_font") in CN_FONTS:      cfg["body_font"] = raw["body_font"]
    if raw.get("body_latin") in EN_FONTS:     cfg["body_latin"] = raw["body_latin"]
    if raw.get("head_font") in CN_FONTS:      cfg["head_font"] = raw["head_font"]
    for k in ("body_size", "h1_size", "h2_size", "h3_size", "title_size", "code_size"):
        if raw.get(k) in FONT_SIZES_PT:       cfg[k] = raw[k]
    if str(raw.get("line_rule")) in LINE_RULES:
        cfg["line_rule"] = str(raw["line_rule"])
    try:
        ic = int(raw.get("indent_chars", cfg["indent_chars"]))
        if 0 <= ic <= 4:
            cfg["indent_chars"] = ic
    except (TypeError, ValueError):
        pass
    return cfg


def cfg_key(cfg: dict) -> str:
    """配置 -> 稳定文件名，用于缓存 ref.docx。"""
    import hashlib
    import json as _json
    blob = _json.dumps(cfg, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha1(blob).hexdigest()[:12]


def _line_attrs(rule: str) -> tuple[int, str]:
    """把行距选项变成 (w:line 值, w:lineRule)。

    Word 的规矩：lineRule=auto 时 line 是"倍数×240"；
    lineRule=exact 时 line 是 twips（1pt = 20 twips）。
    """
    if rule.startswith("固定"):
        pt = float(rule.replace("固定", "").replace("磅", ""))
        return int(round(pt * 20)), "exact"
    return int(round(float(rule) * 240)), "auto"


def build_variant(cfg: dict, out_path: Path):
    """按配置生成 ref.docx。做法：临时改模块常量 → build() → 恢复。

    这样 build() 里几十处硬编码引用不用动，且并发下互不影响
    （Gunicorn 是多线程，所以用局部快照 + 有锁时的替换由调用方保证）。
    """
    global SONG, HEI, KAI, MONO_CN, MONO_EN
    global SZ_XIAOSI, SZ_WUHAO, SZ_SIHAO, SZ_XIAOSAN, SZ_SANHAO, SZ_ERHAO, SZ_XIAOER
    global BODY_LINE, BODY_LINE_RULE, BODY_INDENT_CHARS, BODY_LATIN

    saved = {k: globals().get(k) for k in (
        "SONG", "HEI", "KAI", "MONO_CN", "MONO_EN", "SZ_XIAOSI", "SZ_WUHAO",
        "SZ_SIHAO", "SZ_XIAOSAN", "SZ_SANHAO", "SZ_ERHAO", "SZ_XIAOER",
        "BODY_LINE", "BODY_LINE_RULE", "BODY_INDENT_CHARS", "BODY_LATIN")}

    def sz(name):        # 选项名 -> 半磅值
        return int(round(FONT_SIZES_PT[name] * 2))

    try:
        SONG = cfg["body_font"]
        HEI  = cfg["head_font"]
        KAI  = "楷体"
        # 代码块里的中文跟随正文字体，否则正文换字体后代码块会显得突兀
        MONO_CN = cfg["body_font"]
        BODY_LATIN = cfg["body_latin"]
        SZ_XIAOSI  = sz(cfg["body_size"])
        SZ_WUHAO   = sz(cfg["code_size"])
        SZ_SIHAO   = sz(cfg["h2_size"])
        SZ_XIAOSAN = sz(cfg["body_size"])
        SZ_SANHAO  = sz(cfg["h1_size"])
        SZ_ERHAO   = sz(cfg["title_size"])
        SZ_XIAOER  = sz(cfg["title_size"])
        BODY_LINE, BODY_LINE_RULE = _line_attrs(cfg["line_rule"])
        BODY_INDENT_CHARS = cfg["indent_chars"]
        return build(out_path)
    finally:
        for k, v in saved.items():
            globals()[k] = v



def fonts(east_asia: str, latin: str) -> str:
    """生成 rFonts，同时锁定中西文字体并清除主题字体引用。"""
    return (f'<w:rFonts w:ascii="{latin}" w:hAnsi="{latin}" '
            f'w:eastAsia="{east_asia}" w:cs="{latin}" w:hint="eastAsia" />')


def style(sid, name, ppr="", rpr="", based="Normal", extra="", next_s="BodyText"):
    head = f'<w:style w:type="paragraph" w:styleId="{sid}">'
    parts = [head,
             f'<w:name w:val="{name}" />',
             f'<w:basedOn w:val="{based}" />' if based else "",
             f'<w:next w:val="{next_s}" />' if next_s else "",
             '<w:qFormat />', extra,
             f'<w:pPr>{ppr}</w:pPr>' if ppr else "",
             f'<w:rPr>{rpr}</w:rPr>' if rpr else "",
             '</w:style>']
    return "".join(p for p in parts if p)


def build(out_path: Path):
    # 1) 用 pandoc 自带模板做底（含 numbering.xml / settings.xml 等必需部件）
    src = HERE / ".base_ref.docx"
    if not src.exists():
        import subprocess
        with open(src, "wb") as f:
            subprocess.run(["pandoc", "--print-default-data-file", "reference.docx"],
                           stdout=f, check=True)

    zin = zipfile.ZipFile(src)
    styles_xml = zin.read("word/styles.xml").decode("utf-8")

    # 2) 定位 </w:styles> 之前，整体替换我们已经定义过的样式
    #    做法：先删掉旧定义，再追加新定义（Word 以最后出现为准不够稳，
    #    所以对同名 styleId 必须先删除旧块）
    def drop(sid):
        nonlocal styles_xml
        pat = re.compile(r'<w:style\b[^>]*w:styleId="%s"[^>]*>.*?</w:style>' % re.escape(sid), re.S)
        styles_xml = pat.sub("", styles_xml)

    targets = ["Normal", "BodyText", "FirstParagraph", "Compact",
               "Title", "Subtitle", "Heading1", "Heading2", "Heading3",
               "Heading4", "Heading5", "Heading6",
               "BlockText", "VerbatimChar", "Caption", "TableCaption",
               "ImageCaption", "FootnoteText", "TOCHeading", "Hyperlink",
               # 关键：pandoc 模板里 Table 样式 basedOn 了 TableNormal，
               # 但并没有定义 TableNormal —— Word 会退回到"无边框表格族"，
               # 这就是"表格粘进 Word 后边框/宽度全乱"的根因之一。这里补齐。
               "Table", "TableNormal", "TableGrid"]
    for t in targets:
        drop(t)

    # ---- 正文 Normal：中英文分设，1.5 倍行距(360 twips 的 line=360 auto) ----
    new_styles = []
    new_styles.append(
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
        '<w:name w:val="Normal" /><w:qFormat />'
        '<w:pPr><w:spacing w:before="0" w:after="0" '
        f'w:line="{BODY_LINE}" w:lineRule="{BODY_LINE_RULE}" />'
        '<w:jc w:val="both" /></w:pPr>'
        f'<w:rPr>{fonts(SONG, BODY_LATIN)}'
        f'<w:sz w:val="{SZ_XIAOSI}" /><w:szCs w:val="{SZ_XIAOSI}" />'
        '<w:color w:val="000000" /></w:rPr>'
        '</w:style>')

    # ---- Body Text：首行缩进 N 字符（firstLineChars 是百分之一字符，Word 优先用它）----
    _ic = int(BODY_INDENT_CHARS)
    _flc = _ic * 100
    _fl  = int(round(_ic * SZ_XIAOSI / 2 * 20))   # 兜底值：pt->twips
    new_styles.append(style(
        "BodyText", "Body Text",
        ppr=(f'<w:ind w:firstLineChars="{_flc}" w:firstLine="{_fl}" />'
             '<w:spacing w:before="0" w:after="0" '
             f'w:line="{BODY_LINE}" w:lineRule="{BODY_LINE_RULE}" />'
             '<w:jc w:val="both" />'),
        based="Normal", next_s=None))

    new_styles.append(style(
        "FirstParagraph", "First Paragraph",
        ppr=f'<w:ind w:firstLineChars="{_flc}" w:firstLine="{_fl}" />',
        based="BodyText", next_s="BodyText",
        extra='<w:customStyle />'))

    # ---- Compact：列表项，不缩进首行，行距略紧 ----
    new_styles.append(style(
        "Compact", "Compact",
        ppr=('<w:spacing w:before="40" w:after="40" w:line="340" w:lineRule="auto" />'
             '<w:jc w:val="both" />'),
        based="Normal", next_s=None, extra='<w:customStyle />'))

    # ---- 标题 ----
    def heading(n, name, size, align, before, after, center=False):
        ppr = (f'<w:keepNext /><w:keepLines />'
               f'<w:spacing w:before="{before}" w:after="{after}" w:line="240" w:lineRule="auto" />'
               f'<w:jc w:val="{"center" if center else "left"}" />'
               f'<w:outlineLvl w:val="{n-1}" />'
               f'<w:ind w:firstLineChars="0" w:firstLine="0" />')
        rpr = (f'{fonts(HEI, BODY_LATIN)}<w:b /><w:bCs />'
               f'<w:color w:val="000000" />'
               f'<w:sz w:val="{size}" /><w:szCs w:val="{size}" />')
        return style(f"Heading{n}", name, ppr=ppr, rpr=rpr, next_s="BodyText")

    new_styles.append(heading(1, "heading 1", SZ_SANHAO,  "center", 480, 240, center=True))
    new_styles.append(heading(2, "heading 2", SZ_SIHAO,   "left",   360, 120))
    new_styles.append(heading(3, "heading 3", SZ_XIAOSI,  "left",   240, 120))
    new_styles.append(heading(4, "heading 4", SZ_XIAOSI,  "left",   240, 120))
    new_styles.append(heading(5, "heading 5", SZ_WUHAO,   "left",   180, 60))
    new_styles.append(heading(6, "heading 6", SZ_WUHAO,   "left",   180, 60))

    # ---- 文档大标题 ----
    new_styles.append(style(
        "Title", "Title",
        ppr=('<w:spacing w:before="240" w:after="360" w:line="240" w:lineRule="auto" />'
             '<w:jc w:val="center" /><w:outlineLvl w:val="0" />'),
        rpr=(f'{fonts(HEI, BODY_LATIN)}<w:b /><w:bCs />'
             f'<w:color w:val="000000" /><w:sz w:val="{SZ_ERHAO}" /><w:szCs w:val="{SZ_ERHAO}" />'),
        next_s="BodyText"))

    # ---- 引用 Block Text：楷体，左右缩进 ----
    new_styles.append(style(
        "BlockText", "Block Text",
        ppr=('<w:ind w:left="480" w:right="480" w:firstLineChars="0" w:firstLine="0" />'
             '<w:spacing w:before="120" w:after="120" w:line="360" w:lineRule="auto" />'),
        rpr=f'{fonts(KAI, BODY_LATIN)}<w:sz w:val="{SZ_XIAOSI}" /><w:szCs w:val="{SZ_XIAOSI}" />',
        next_s=None, extra='<w:customStyle />'))

    # ---- 图/表题注：居中、五号、加粗 ----
    for sid, nm in [("Caption", "caption"), ("TableCaption", "Table Caption"),
                    ("ImageCaption", "Image Caption")]:
        new_styles.append(style(
            sid, nm,
            ppr=('<w:spacing w:before="60" w:after="120" w:line="280" w:lineRule="auto" />'
                 '<w:jc w:val="center" /><w:keepNext />'
                 '<w:ind w:firstLineChars="0" w:firstLine="0" />'),
            rpr=(f'{fonts(SONG, BODY_LATIN)}<w:b /><w:bCs />'
                 f'<w:sz w:val="{SZ_WUHAO}" /><w:szCs w:val="{SZ_WUHAO}" />'),
            next_s=None, extra='<w:customStyle />' if sid != "Caption" else ""))

    # ---- 脚注 ----
    new_styles.append(style(
        "FootnoteText", "footnote text",
        ppr=('<w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto" />'),
        rpr=f'<w:sz w:val="{SZ_WUHAO}" /><w:szCs w:val="{SZ_WUHAO}" />',
        next_s=None))

    # ---- 行内代码 / 等宽字符 ----
    new_styles.append(
        '<w:style w:type="character" w:customStyle="1" w:styleId="VerbatimChar">'
        '<w:name w:val="Verbatim Char" /><w:qFormat />'
        f'<w:rPr>{fonts(MONO_CN, MONO_EN)}<w:shd w:val="clear" w:color="auto" w:fill="F2F2F2" />'
        f'<w:sz w:val="{SZ_WUHAO}" /><w:szCs w:val="{SZ_WUHAO}" /></w:rPr></w:style>')

    # 给 Normal 之外的 default 字符样式补一个 BodyTextChar，防止 pandoc 引用不到
    new_styles.append(
        '<w:style w:type="character" w:styleId="BodyTextChar">'
        '<w:name w:val="Body Text Char" />'
        f'<w:rPr>{fonts(SONG, BODY_LATIN)}</w:rPr></w:style>')

    # 注意：new_styles 的拼接必须放在**所有** append 之后（见文件末尾），
    # 否则后追加的样式（如表格）会被静默丢弃。

    # 3) 补一个代码块段落样式 SourceCode
    #    要点：keepLines(段内不分页) 防止代码被拦腰截断；
    #    keepNext 让「核心函数如下：」这类引导句不和代码分家。
    drop2 = re.compile(r'<w:style\b[^>]*w:styleId="SourceCode"[^>]*>.*?</w:style>', re.S)
    styles_xml = drop2.sub("", styles_xml)
    source_code = (
        '<w:style w:type="paragraph" w:customStyle="1" w:styleId="SourceCode">'
        '<w:name w:val="Source Code" /><w:qFormat />'
        '<w:pPr>'
        '<w:keepLines />'                     # 代码块整段不分页
        '<w:shd w:val="clear" w:color="auto" w:fill="F7F7F7" />'
        '<w:spacing w:before="120" w:after="120" w:line="260" w:lineRule="auto" />'
        '<w:ind w:left="240" w:right="120" w:firstLineChars="0" w:firstLine="0" />'
        '<w:jc w:val="left" />'
        '<w:snapToGrid w:val="0" />'          # 不受文档网格约束，避免行高异常
        '</w:pPr>'
        f'<w:rPr>{fonts(MONO_CN, MONO_EN)}<w:sz w:val="{SZ_WUHAO}" />'
        f'<w:szCs w:val="{SZ_WUHAO}" /></w:rPr></w:style>')
    insert_at = styles_xml.rindex("</w:styles>")
    styles_xml = styles_xml[:insert_at] + source_code + styles_xml[insert_at:]

    # ---- 表格：三线表（顶线粗、表头下细线、底粗线），无竖线 ----
    # TableNormal 是 Word 表格样式的根基样式，必须先定义，否则 Table 继承断裂。
    new_styles.append(
        '<w:style w:type="table" w:default="1" w:styleId="TableNormal">'
        '<w:name w:val="Normal Table" /><w:semiHidden /><w:unhideWhenUsed />'
        '<w:tblPr><w:tblInd w:w="0" w:type="dxa" />'
        '<w:tblCellMar>'
        '<w:top w:w="40" w:type="dxa" /><w:left w:w="108" w:type="dxa" />'
        '<w:bottom w:w="40" w:type="dxa" /><w:right w:w="108" w:type="dxa" />'
        '</w:tblCellMar></w:tblPr></w:style>')

    new_styles.append(
        '<w:style w:type="table" w:styleId="Table">'
        '<w:name w:val="Table" /><w:basedOn w:val="TableNormal" /><w:qFormat />'
        '<w:tblPr>'
        '<w:tblBorders>'
        '<w:top w:val="single" w:sz="12" w:space="0" w:color="000000" />'
        '<w:left w:val="none" w:sz="0" w:space="0" w:color="auto" />'
        '<w:bottom w:val="single" w:sz="12" w:space="0" w:color="000000" />'
        '<w:right w:val="none" w:sz="0" w:space="0" w:color="auto" />'
        '<w:insideH w:val="none" w:sz="0" w:space="0" w:color="auto" />'
        '<w:insideV w:val="none" w:sz="0" w:space="0" w:color="auto" />'
        '</w:tblBorders>'
        '<w:tblLayout w:type="autofit" />'
        '<w:jc w:val="center" />'
        '</w:tblPr>'
        '<w:tblStylePr w:type="firstRow">'
        '<w:rPr><w:b /><w:bCs /></w:rPr>'
        '<w:tcPr><w:tcBorders>'
        '<w:bottom w:val="single" w:sz="6" w:space="0" w:color="000000" />'
        '</w:tcBorders><w:vAlign w:val="center" /></w:tcPr>'
        '</w:tblStylePr>'
        '</w:style>')

    # TableGrid：Word UI 里"网格表"对应的样式，给需要全框线的场景留一手
    new_styles.append(
        '<w:style w:type="table" w:styleId="TableGrid">'
        '<w:name w:val="Table Grid" /><w:basedOn w:val="TableNormal" /><w:qFormat />'
        '<w:tblPr><w:tblBorders>'
        '<w:top w:val="single" w:sz="4" w:space="0" w:color="auto" />'
        '<w:left w:val="single" w:sz="4" w:space="0" w:color="auto" />'
        '<w:bottom w:val="single" w:sz="4" w:space="0" w:color="auto" />'
        '<w:right w:val="single" w:sz="4" w:space="0" w:color="auto" />'
        '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="auto" />'
        '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="auto" />'
        '</w:tblBorders></w:tblPr></w:style>')

    # 单元格内文字用五号，避免表格被小四撑得过宽
    new_styles.append(
        '<w:style w:type="paragraph" w:customStyle="1" w:styleId="TableText">'
        '<w:name w:val="Table Text" /><w:qFormat />'
        '<w:pPr><w:spacing w:before="20" w:after="20" w:line="260" w:lineRule="auto" />'
        '<w:jc w:val="left" /><w:ind w:firstLineChars="0" w:firstLine="0" /></w:pPr>'
        f'<w:rPr>{fonts(SONG, BODY_LATIN)}'
        f'<w:sz w:val="{SZ_WUHAO}" /><w:szCs w:val="{SZ_WUHAO}" /></w:rPr></w:style>')

    # ---- 统一写入 styles.xml（必须在此处、所有 append 之后执行一次）----
    insert_at = styles_xml.rindex("</w:styles>")
    styles_xml = styles_xml[:insert_at] + "".join(new_styles) + styles_xml[insert_at:]

    # 自检：必须存在的样式一个都不能少（此前出过「表格样式被静默丢弃」的 bug）
    REQUIRED = ["Normal", "BodyText", "Compact", "Title",
                "Heading1", "Heading2", "Heading3",
                "SourceCode", "VerbatimChar", "BlockText",
                "TableNormal", "Table", "TableGrid", "TableText"]
    for sid in REQUIRED:
        n = len(re.findall(r'w:styleId="%s"' % re.escape(sid), styles_xml))
        if n != 1:
            raise SystemExit(f"模板自检失败: 样式 {sid} 出现 {n} 次（应为 1）")
    dangling = set(re.findall(r'<w:basedOn w:val="([^"]+)"', styles_xml)) - \
               set(re.findall(r'w:styleId="([^"]+)"', styles_xml))
    if dangling:
        raise SystemExit(f"模板自检失败: basedOn 指向未定义样式 {dangling}")

    # 4) 页面设置：A4 + 页边距，写进 document.xml 的 sectPr
    doc_xml = zin.read("word/document.xml").decode("utf-8")
    sect = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838" />'
            '<w:pgMar w:top="1440" w:right="1800" w:bottom="1440" w:left="1800" '
            'w:header="851" w:footer="992" w:gutter="0" />'
            '<w:docGrid w:type="lines" w:linePitch="312" /></w:sectPr>')
    doc_xml = re.sub(r'<w:sectPr\b.*?</w:sectPr>', sect, doc_xml, flags=re.S)
    if "<w:sectPr" not in doc_xml:
        doc_xml = doc_xml.replace("</w:body>", sect + "</w:body>")

    # 5) 写出
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/styles.xml":
                data = styles_xml.encode("utf-8")
            elif item.filename == "word/document.xml":
                data = doc_xml.encode("utf-8")
            zout.writestr(item, data)
    zin.close()
    return out_path


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    p = build(out)
    print("wrote", p, p.stat().st_size, "bytes")
