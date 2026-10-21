#!/bin/sh
# 生成/轮换 md2word 调用令牌。
# 令牌只写进 docker-compose 用的 .env（600），不打印到聊天里。
set -e
cd /opt/md2word

if [ -f .env ] && grep -q '^MD2W_TOKEN=' .env; then
    echo "已存在令牌，未改动。要轮换请先删掉 .env 里的 MD2W_TOKEN 那一行。"
    exit 0
fi

TOKEN=$(python3 -c "import secrets;print(secrets.token_urlsafe(24))")
umask 077
if [ -f .env ]; then
    printf 'MD2W_TOKEN=%s\n' "$TOKEN" >> .env
else
    printf 'MD2W_TOKEN=%s\n' "$TOKEN" > .env
fi
chmod 600 .env

echo "令牌已写入 /opt/md2word/.env (chmod 600)"
echo "查看方法：sudo cat /opt/md2word/.env   或   运行 /opt/md2word/wordclip-token.sh"
