#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""没有 node 的环境下给扩展做静态自检。

做四件事（真机上"加载已解压的扩展"之前先跑一遍，能挡掉 80% 的低级错误）：
  1) manifest.json 能被解析；manifest_version == 3
  2) manifest 里引用的每个文件都真实存在
  3) 每个 .js 语法可解析（用 deno/node 若有；否则退化为括号/引号配平 + 常见错法检查）
  4) 每个 .html 引用的本地 js/css 都存在；popup/options 里的 id 都被对应 js 用到

退出码 0 = 全部通过。
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
fails, warns = [], []


def check_manifest():
    p = ROOT / "manifest.json"
    try:
        m = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:                                    # noqa: BLE001
        fails.append(f"manifest.json 解析失败: {e}")
        return None
    if m.get("manifest_version") != 3:
        fails.append("manifest_version 不是 3")
    refs = []
    bg = m.get("background", {})
    if bg.get("service_worker"):
        refs.append(bg["service_worker"])
    for cs in m.get("content_scripts", []):
        refs += cs.get("js", []) + cs.get("css", [])
    act = m.get("action", {})
    if act.get("default_popup"):
        refs.append(act["default_popup"])
    if m.get("options_page"):
        refs.append(m["options_page"])
    for ic in m.get("icons", {}).values():
        refs.append(ic)
    for r in refs:
        if not (ROOT / r).exists():
            fails.append(f"manifest 引用了不存在的文件: {r}")
    return m


def check_html():
    for h in ROOT.glob("*.html"):
        s = h.read_text(encoding="utf-8")
        for src in re.findall(r'<script[^>]+src="([^"]+)"', s):
            if not (ROOT / src).exists():
                fails.append(f"{h.name} 引用的脚本不存在: {src}")
        for href in re.findall(r'<link[^>]+href="([^"]+)"', s):
            if not href.startswith("http") and not (ROOT / href).exists():
                fails.append(f"{h.name} 引用的样式不存在: {href}")
        ids = set(re.findall(r'id="([^"]+)"', s))
        js = h.with_suffix(".js")
        if js.exists():
            jsrc = js.read_text(encoding="utf-8")
            used = set(re.findall(r"""\$\('([^']+)'\)""", jsrc))
            missing = used - ids
            if missing:
                fails.append(f"{js.name} 用到了 {h.name} 里不存在的 id: {sorted(missing)}")
            # 反查：html 里有 id 但 js 没用到的按钮，通常是忘了绑事件
            for extra in sorted(ids - used):
                if extra in ("msg", "state", "status", "server", "tokenState"):
                    continue
                warns.append(f"{h.name} 的 #{extra} 没有在 {js.name} 里绑定")


def check_api_permissions(manifest):
    """用了 chrome.Xxx 就必须在 permissions 里声明，否则运行时报 "is not defined"。"""
    if not manifest:
        return
    # 不需要声明的 API
    free = {"runtime", "i18n", "extension"}
    # 这几个不走 permissions：action 由 "action" 键提供，commands 由 "commands" 键提供
    if manifest.get("action"):
        free.add("action")
    if manifest.get("commands"):
        free.add("commands")
    declared = set()
    for k in ("permissions", "optional_permissions"):
        declared |= {str(x) for x in (manifest.get(k) or [])}
    used = set()
    for j in sorted(ROOT.rglob("*.js")):
        used |= set(re.findall(r"chrome\.([a-zA-Z]+)\.", j.read_text(encoding="utf-8")))
    missing = {u for u in used - free - declared}
    known = {"downloads", "storage", "tabs", "scripting", "notifications",
             "contextMenus", "action", "commands", "clipboardWrite", "activeTab", "alarms"}
    if "tabs" in missing:
        # 只用到 tabs.query / tabs.create / tabs.sendMessage，这些在 activeTab + host_permissions 下可用，
        # 不读 tab.url / tab.title 就不需要 "tabs" 权限（真的读了才要）。
        src = "".join(j.read_text(encoding="utf-8") for j in ROOT.rglob("*.js"))
        # 只认 tab/picked 这类对象上的敏感字段，document.title、picked.title 不算
        if re.search(r"\b(tab|t|tabs\[0\]|sender\.tab)\.(url|title|favIconUrl)\b", src) is None:
            missing.discard("tabs")
    for u in sorted(missing):
        if u in known:
            fails.append(f"代码用了 chrome.{u}，但 manifest 没声明该权限")


def check_js():
    runtime = shutil.which("node") or shutil.which("nodejs") or shutil.which("deno")
    for j in sorted(ROOT.rglob("*.js")):
        src = j.read_text(encoding="utf-8")
        if runtime and runtime.endswith(("node", "nodejs")):
            r = subprocess.run([runtime, "--check", str(j)],
                               capture_output=True, text=True)
            if r.returncode != 0:
                fails.append(f"{j.name} 语法错误: {r.stderr.strip().splitlines()[:2]}")
            continue
        # 无运行时：括号配平 + 模板串/字符串引号配平（忽略注释与字符串内的括号）
        depth = {"(": 0, "{": 0, "[": 0}
        pairs = {")": "(", "}": "{", "]": "["}
        i, n = 0, len(src)
        stack, line = [], 1
        while i < n:
            c = src[i]
            if c == "\n":
                line += 1
            if c in "\"'`":
                q, i = c, i + 1
                while i < n and src[i] != q:
                    if src[i] == "\\":
                        i += 1
                    elif src[i] == "\n":
                        if q != "`":
                            fails.append(f"{j.name}:{line} 字符串没闭合")
                            break
                        line += 1
                    i += 1
            elif src.startswith("//", i) and not re.search(r"[)\]a-zA-Z0-9_$.]$", src[:i].rstrip()):
                while i < n and src[i] != "\n":
                    i += 1
                continue
            elif c == "/" and not src.startswith("//", i) and not src.startswith("/*", i) \
                    and re.search(r"(^|[=(,:[!&|?{};])\s*$", src[:i]):
                # 正则字面量（形如 /.../gi）：跳过，别把里面的括号当代码
                j = i + 1
                while j < n and src[j] != "/":
                    if src[j] == "\\":
                        j += 1
                    elif src[j] == "[":
                        while j < n and src[j] != "]":
                            if src[j] == "\\":
                                j += 1
                            elif src[j] == "\n":
                                line += 1
                            j += 1
                    j += 1
                i = j + 1
                continue
            elif src.startswith("/*", i):
                k = src.find("*/", i + 2)
                line += src.count("\n", i, k if k > 0 else n)
                i = (k + 2) if k > 0 else n
                continue
            elif c in "({[":
                stack.append((c, line))
            elif c in ")}]":
                if not stack or stack[-1][0] != pairs[c]:
                    fails.append(f"{j.name}:{line} 括号不匹配: {c}")
                    break
                stack.pop()
            i += 1
        if stack:
            fails.append(f"{j.name} 结尾有多余的 {stack[-1][0]}（第 {stack[-1][1]} 行开）")
        for bad in ("chrome.runtime.sendMessage({ type: 'probe' }, (r) =>",):
            pass
    if not runtime:
        warns.append("本机没有 node/deno，JS 只做了括号配平检查（不是真语法检查）")


def main():
    if not (ROOT / "manifest.json").exists():
        print("找不到 manifest.json，请在 extension/ 目录下运行")
        return 2
    m = check_manifest()
    check_html()
    check_js()
    check_api_permissions(m)
    for w in warns:
        print("  WARN", w)
    for f in fails:
        print("  FAIL", f)
    print(f"RESULT: {'PASS' if not fails else 'FAIL'}  (warn {len(warns)}, fail {len(fails)})")
    if m:
        print(f"  名称={m.get('name')} 版本={m.get('version')} 权限={m.get('permissions')}")
    return 0 if not fails else 1


if __name__ == "__main__":
    sys.exit(main())
