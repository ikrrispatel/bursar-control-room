FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY app ./app
COPY scripts ./scripts
COPY samples ./samples

RUN pip install --no-cache-dir . \
    && useradd --create-home --shell /usr/sbin/nologin bursar \
    && mkdir -p /data \
    && chown -R bursar:bursar /app /data

USER bursar

EXPOSE 8000 8501

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
