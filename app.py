#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
md2word 服务 —— Markdown/AI 回答 → 排版好的 Word

两种出口：
  POST /api/docx    返回 .docx 文件（最稳，公式是 Word 原生可编辑公式）
  POST /api/clip    返回 Word 剪贴板 HTML（配合前端一键写入剪贴板）

设计约束：
  - 单文件、无 ORM、只有标准库 + pandoc 命令行
  - 输入长度上限防滥用；pandoc 子进程带超时
  - 不落盘用户内容（临时目录用完即删），不写日志正文
"""
from __future__ import annotations

import hmac
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, send_file

import wordclip
import build_reference

BASE = Path(__file__).resolve().parent
REF_DOCX = BASE / "ref.docx"
MAX_CHARS = 300_000          # 约 15 万汉字，足够长报告
PANDOC = shutil.which("pandoc") or "pandoc"

# 排版缓存目录：每个不同配置生成一份 ref.docx，按内容哈希命名复用。
# 必须可写（容器里是 /tmp）。
CACHE_DIR = Path(os.environ.get("MD2W_CACHE", "/tmp/md2w-cache"))
_REF_LOCK = threading.Lock()


def _style_cfg() -> dict:
    """从请求里取排版配置（JSON 的 style 字段，或表单的 style JSON 串）。"""
    data = request.get_json(silent=True) or {}
    raw = data.get("style")
    if raw is None:
        s = request.form.get("style")
        if s:
            try:
                raw = json.loads(s)
            except (ValueError, TypeError):
                raw = None
    return build_reference.normalize_cfg(raw)


def _ref_docx(cfg: dict) -> Path:
    """按配置返回 reference.docx 路径；没缓存就生成一份。

    为什么要缓存：生成一次要走 pandoc + 改 XML，同一套配置每次重建纯属浪费，
    而且这台机器只有 1.7G 内存、多线程并发时更该省。
    """
    key = build_reference.cfg_key(cfg)
    dst = CACHE_DIR / f"ref-{key}.docx"
    if dst.exists() and dst.stat().st_size > 1000:
        return dst

    with _REF_LOCK:
        # 双检：等锁期间别人可能已经生成好了
        if dst.exists() and dst.stat().st_size > 1000:
            return dst
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        # 先写临时文件再原子改名，避免并发下别人读到半截文件。
        # ⚠ 必须在锁内：build_variant 靠临时改模块全局常量实现，
        # 多线程同时进入会互相踩踏（A 的字体跑进 B 的文档）。
        tmp = dst.with_name(f"{dst.stem}.{os.getpid()}.tmp")
        build_reference.build_variant(cfg, tmp)
        os.replace(tmp, dst)
    return dst

app = Flask(__name__, template_folder=str(BASE / "templates"))
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024

MD_FMT = ("markdown+tex_math_dollars+pipe_tables+footnotes+strikeout"
          "+task_lists+definition_lists+subscript+superscript")


def _get_md() -> tuple[str, str]:
    """从 JSON 或表单取输入，返回 (markdown, 标题)。"""
    data = request.get_json(silent=True) or {}
    md = data.get("md") or request.form.get("md") or ""
    title = data.get("title") or request.form.get("title") or ""
    return md, title


def _validate(md: str):
    if not md or not md.strip():
        return "内容为空"
    if len(md) > MAX_CHARS:
        return f"内容过长（{len(md)} 字符，上限 {MAX_CHARS}）"
    return None


def _prepend_title(md: str, title: str) -> str:
    """用户填了标题且正文没以一级标题开头时，自动补一行标题。"""
    t = (title or "").strip()
    if not t:
        return md
    first = md.lstrip().splitlines()[0] if md.strip() else ""
    if first.startswith("# "):
        return md
    return f"# {t}\n\n{md}"


def _token_ok():
    """调用令牌校验。

    为什么需要：nginx 为了给 Windows 脚本开门，把 /md2word/ 免掉了网页密码，
    等于把转换服务挂到了公网。没有令牌，任何人拿到地址就能白蹭 CPU，
    还能当"任意 Markdown 转 HTML"的免费接口用。

    规则：
      - 环境变量 MD2W_TOKEN 未设置  → 只允许本机(回环)调用；
      - 已设置 → 必须在 X-Md2W-Token 头里带上，且用恒定时间比较。
    """
    expect = os.environ.get("MD2W_TOKEN", "").strip()
    if not expect:
        # 没设令牌时，只信任本机直连（curl 127.0.0.1 / 容器内调用）
        return request.remote_addr in ("127.0.0.1", "::1")
    got = request.headers.get("X-Md2W-Token", "")
    return hmac.compare_digest(got.encode(), expect.encode())


@app.post("/api/docx")
def api_docx():
    if not _token_ok():
        return jsonify({"ok": False, "error": "未授权"}), 401
    md, title = _get_md()
    err = _validate(md)
    if err:
        return jsonify({"ok": False, "error": err}), 400

    md = _prepend_title(md, title)
    try:
        ref = _ref_docx(_style_cfg())
    except Exception as e:                      # 配置生成失败不能拖垮整个服务
        return jsonify({"ok": False, "error": "排版配置生成失败：" + str(e)[:200]}), 500
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "out.docx"
        try:
            p = subprocess.run(
                [PANDOC, "-f", MD_FMT, "-t", "docx",
                 f"--reference-doc={ref}", "-o", str(out)],
                input=md.encode("utf-8"),
                capture_output=True, timeout=45)
        except subprocess.TimeoutExpired:
            return jsonify({"ok": False, "error": "转换超时，请缩短内容"}), 504

        if p.returncode != 0 or not out.exists():
            return jsonify({
                "ok": False,
                "error": "转换失败：" + p.stderr.decode("utf-8", "replace")[:300]
            }), 500

        data = out.read_bytes()

    fname = (re.sub(r'[\\/:*?"<>|\s]+', "_", (title or "AI文档").strip())[:40]
             or "AI文档") + time.strftime("_%Y%m%d") + ".docx"

    # HTTP 头只能是 latin-1，中文名不能直接塞进去（否则变成 AIæ–‡æ¡£）。
    # 规范做法：filename= 给纯 ASCII 兜底名，filename*=UTF-8''<百分号编码> 给真名，
    # 现代浏览器（Edge/Chrome/Firefox）优先用后者，中文名就正常了。
    ascii_name = "AI-document" + time.strftime("_%Y%m%d") + ".docx"
    from urllib.parse import quote
    cd = (f"attachment; filename=\"{ascii_name}\"; "
          f"filename*=UTF-8''{quote(fname, safe='')}")

    return Response(
        data,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": cd})




@app.post("/api/clip")
def api_clip():
    if not _token_ok():
        return jsonify({"ok": False, "error": "未授权"}), 401
    md, title = _get_md()
    err = _validate(md)
    if err:
        return jsonify({"ok": False, "error": err}), 400
    md = _prepend_title(md, title)
    # wordclip 的排版参数是模块级常量，改完必须恢复；
    # 加锁保证同一时刻只有一个请求在改这些全局量。
    with _REF_LOCK:
        saved = wordclip.apply_cfg(_style_cfg())
        try:
            html = wordclip.to_clip_html(md)
            html = wordclip.tidy(html)
        except Exception as e:                       # noqa: BLE001
            return jsonify({"ok": False, "error": f"转换失败：{e}"}), 500
        finally:
            wordclip.restore_cfg(saved)
    return jsonify({"ok": True, "html": html, "chars": len(md)})


@app.get("/api/presets")
def presets():
    """把预设和可选项给前端，前端不写死任何值。"""
    return jsonify({
        "ok": True,
        "presets": [{"key": k, **v} for k, v in build_reference.PRESETS.items()],
        "default": build_reference.DEFAULT_STYLE,
        "cn_fonts": build_reference.CN_FONTS,
        "en_fonts": build_reference.EN_FONTS,
        "sizes": list(build_reference.FONT_SIZES_PT.keys()),
        "line_rules": build_reference.LINE_RULES,
    })


@app.get("/api/health")
def health():
    try:
        v = subprocess.run([PANDOC, "--version"], capture_output=True,
                           text=True, timeout=10).stdout.splitlines()[0]
    except Exception:                            # noqa: BLE001
        return jsonify({"ok": False, "pandoc": None}), 500
    return jsonify({"ok": True, "pandoc": v,
                    "ref_docx": REF_DOCX.exists(),
                    "max_chars": MAX_CHARS})


@app.get("/")
def index():
    return render_template("index.html")


@app.errorhandler(413)
def too_large(_e):
    return jsonify({"ok": False, "error": "请求体过大（上限 4MB）"}), 413


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 8020)), debug=False)
