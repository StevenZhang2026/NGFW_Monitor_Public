FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    fonts-wqy-zenhei \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 非 root 运行（trivy DS-0002）。uid 写死 1000：reportdata 命名卷首次创建时
# 会从镜像里的 /app/data/reports 继承属主，uid 变了旧卷就写不进去了。
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /app/data/reports \
    && chown -R app:app /app/data

COPY --chown=app:app . .

# matplotlib / fontconfig 要往 $HOME 下写缓存，非 root 下 HOME 未设会退化并打警告
ENV HOME=/home/app \
    MPLCONFIGDIR=/tmp/matplotlib

USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
