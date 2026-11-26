# syntax=docker/dockerfile:1

# ---------- 阶段 1：构建 React + TypeScript 前端 ----------
FROM node:22-bookworm-slim AS web
ARG NPM_REGISTRY=https://registry.npmmirror.com
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm config set registry "${NPM_REGISTRY}" \
    && if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY frontend/ ./
RUN npm run build

# ---------- 阶段 2：FastAPI 运行时（同时托管前端 dist） ----------
FROM python:3.12-slim AS api
ARG PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_INDEX_URL=${PIP_INDEX} \
    STATIC_DIR=/app/static \
    PORT=8000
WORKDIR /app

# psycopg[binary] 自带所需原生库，slim 镜像无需额外 libpq
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY --from=web /web/dist ./static

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=4s --retries=12 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).status==200 else 1)"

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
