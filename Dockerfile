# Multi-stage build for production.
FROM python:3.10-slim AS builder
WORKDIR /app
RUN pip install --no-cache-dir --upgrade pip setuptools wheel
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir .

FROM python:3.10-slim AS runtime
RUN groupadd -r medscribe && useradd -r -g medscribe medscribe
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
COPY --from=builder /usr/local/bin/uvicorn /usr/local/bin/uvicorn
COPY --from=builder /app/src /app/src
USER medscribe
EXPOSE 8000
CMD ["uvicorn", "medscribe.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
