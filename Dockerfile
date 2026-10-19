FROM ghcr.io/astral-sh/uv:0.10.7 AS uv
FROM python:3.11.16-slim-bookworm

COPY --from=uv /uv /usr/local/bin/uv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy \
    GRADIO_ANALYTICS_ENABLED=False HOME=/tmp \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --group review-auth --no-install-project
COPY app.py review_app.py contracts.py ./
COPY core/ core/
COPY ui/ ui/
COPY fixtures/ fixtures/
COPY scripts/ scripts/
RUN mkdir -p runs/review-exports runs/reviewer-exports
USER 1000:1000
EXPOSE 7860 7863
CMD ["python", "app.py", "--host", "0.0.0.0", "--port", "7860"]
