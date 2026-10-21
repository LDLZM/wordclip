#!/bin/sh
# 打包 Windows 客户端（含令牌）到下载目录，并给一次性链接。
# 令牌来自 /opt/md2word/.env，不进聊天、不进源码仓库。
set -e

SRC=/opt/md2word
OUT=/var/www/downloads
STAMP=$(date +%Y%m%d)
ZIP=/tmp/md2word-win.zip

[ -f "$SRC/.env" ] || { echo "缺少 $SRC/.env"; exit 1; }
TOK=$(grep '^MD2W_TOKEN=' "$SRC/.env" | cut -d= -f2)
[ -n "$TOK" ] || { echo "令牌为空"; exit 1; }

rm -rf /tmp/md2word-pkg && mkdir -p /tmp/md2word-pkg
cp "$SRC/wordclip.ps1" "$SRC/wordclip.bat" /tmp/md2word-pkg/
printf '%s' "$TOK" > /tmp/md2word-pkg/wordclip.token

cat > /tmp/md2word-pkg/使用说明.txt <<'TXT'
AI 回答 -> Word 格式  使用说明
================================

一、第一次使用
  1. 把整个文件夹解压到任意位置（比如 D:\Downloads\md2word\）
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
  · 提示"连不上服务器"：检查网络；服务器地址写死在 wordclip.ps1 顶部。
  · 提示"服务器拒绝 401"：wordclip.token 丢了或过期，找服务提供者重新要。
  · 提示缺少脚本：解压时被 Windows Defender 拦了，把文件夹加白名单。
  · 想要 .docx 文件而不是粘贴：在浏览器打开
      https://your-server.example.com   （部署后改成你自己的地址）
    粘贴 Markdown，点"下载 Word 文档"。
TXT

cd /tmp/md2word-pkg
rm -f "$ZIP"
zip -q -r "$ZIP" . || { echo "zip 命令不可用"; exit 1; }

install -m 600 "$ZIP" "$OUT/md2word-win.zip"
# nginx 需要对 /dl/ 下的文件可读
chgrp www-data "$OUT/md2word-win.zip" 2>/dev/null || true

echo "已生成: $OUT/md2word-win.zip"
echo "包内文件:"
unzip -l "$ZIP" | sed 's/^/  /'
