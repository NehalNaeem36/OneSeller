# Backend / agent API image (Hugging Face Spaces Docker SDK uses port 7860; Render sets $PORT).
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=7860
RUN pip install --no-cache-dir uv==0.13.7
RUN useradd -m -u 1000 app
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY --chown=app:app . .
USER app
EXPOSE 7860
# Apply migrations, then serve. LangGraph checkpoint tables are created on first agent use.
CMD ["sh", "-c", ".venv/bin/alembic upgrade head && .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
