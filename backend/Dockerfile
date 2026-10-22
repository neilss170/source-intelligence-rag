FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# CPU-only PyTorch: the CUDA build would add ~4 GB the API never uses.
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch

# Dependencies first, against a stub package, so code changes don't
# reinstall them.
COPY pyproject.toml ./
RUN mkdir app && touch app/__init__.py && pip install . && rm -rf app

COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic
RUN pip install --no-deps .

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data /models \
    && chown appuser /data /models
USER appuser

ENV DATA_DIR=/data HF_HOME=/models
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
