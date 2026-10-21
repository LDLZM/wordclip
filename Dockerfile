FROM python:3.12-slim

# pandoc 是唯一的重依赖（约 30MB 二进制），其余全部走 apt 源安装
# 用阿里云镜像，国内构建更快
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' \
        /etc/apt/sources.list.d/debian.sources 2>/dev/null || true \
    && apt-get update \
    && apt-get install -y --no-install-recommends pandoc fonts-noto-cjk ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ \
        --trusted-host mirrors.aliyun.com -r requirements.txt

COPY . .

RUN useradd -m -u 10002 md2word \
    && mkdir -p /app && chown -R md2word:md2word /app
USER md2word

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')" || exit 1

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "4", \
     "--timeout", "90", "--access-logfile", "-", "--error-logfile", "-", "app:app"]
