FROM node:22-alpine AS frontend
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 STILL_DATABASE=/app/data/journal.sqlite3
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home --uid 10001 still
COPY backend/ ./backend/
COPY --from=frontend /web/dist ./frontend/dist/
RUN mkdir -p /app/data && chown -R still:still /app/data
USER still
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/status', timeout=3)"
CMD ["python", "-m", "uvicorn", "backend.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
