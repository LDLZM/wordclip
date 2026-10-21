#!/usr/bin/env python3
"""打包 Windows 客户端（含令牌）到下载目录。

为什么不放进 /dl/ 直接给人下载：那个目录开了 autoindex，包里带令牌，
等于把令牌挂在公网上。这里做成随机文件名 + 一次性提示，
并且写进 /var/www/downloads/_private/（nginx 只对精确路径放行）。
"""
import os
import secrets
import shutil
import zipfile
from pathlib import Path

SRC = Path("/opt/md2word")
OUT = Path("/var/www/downloads/_private")

env = SRC / ".env"
if not env.exists():
    raise SystemExit("缺少 /opt/md2word/.env")
token = ""
for line in env.read_text(encoding="utf-8").splitlines():
    if line.startswith("MD2W_TOKEN="):
        token = line.split("=", 1)[1].strip()
if not token:
    raise SystemExit("令牌为空")

OUT.mkdir(parents=True, exist_ok=True)

README = """AI 回答 -> Word 格式  使用说明
================================

一、第一次使用
  1. 把压缩包整个解压到任意位置（比如 D:\\Downloads\\md2word\\）
     注意：wordclip.ps1 和 wordclip.token 必须放在同一个文件夹里。
  2. 在 AI 聊天页面里全选回答并复制（Ctrl+A、Ctrl+C）。

二、每次转换
  3. 双击 wordclip.bat
     看到 "完成。现在到 Word 里 Ctrl+V 即可。" 就成功了。
  4. 打开 Word，Ctrl+V 粘贴。

三、会得到什么格式
  · 标题是真正的 Word 标题样式 —— 导航窗格能用，自动目录能生成
  · 正文 宋体 小四(12pt)，行距 1.5 倍，首行缩进两字
  · 英文和数字用 Times New Roman，不会和中文挤在一起
  · 表格是三线表，列宽按内容分配
  · 公式是真公式（能点开编辑），不是图片也不是乱码
  · 代码块等宽字体，不会被分页拆开
  · 列表符号是普通字符，不会消失

四、常见问题
  · "连不上服务器"：检查网络。服务器地址在 wordclip.ps1 顶部。
  · "服务器拒绝 401"：wordclip.token 丢了或过期，找服务提供者重新要。
  · 解压后看不到 wordclip.ps1：被 Windows Defender 拦了，把文件夹加白名单。
  · 想要 .docx 文件而不是粘贴：浏览器打开
      https://your-server.example.com   （部署后改成你自己的地址）
    粘贴 Markdown，点"下载 Word 文档"。
  · 粘贴后如果发现某处不对，把那一段连同 Word 里的样子截图给服务提供者。
"""

files = [
    (SRC / "wordclip.ps1", "md2word/wordclip.ps1"),
    (SRC / "wordclip.bat", "md2word/wordclip.bat"),
]

fname = f"md2word-win-{secrets.token_hex(6)}.zip"
dest = OUT / fname

with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
    for src, arc in files:
        if not src.exists():
            raise SystemExit(f"缺少 {src}")
        z.write(src, arc)
    z.writestr("md2word/wordclip.token", token)
    z.writestr("md2word/使用说明.txt", README)

os.chmod(dest, 0o640)
try:
    shutil.chown(dest, group="www-data")
except LookupError:
    pass

with zipfile.ZipFile(dest) as z:
    print(f"已生成 {dest}  ({dest.stat().st_size} 字节)")
    for n in z.namelist():
        print("  ", n)

old = sorted(OUT.glob("md2word-win-*.zip"))
for p in old:
    if p != dest:
        p.unlink()
        print(f"已清理旧包 {p.name}")
