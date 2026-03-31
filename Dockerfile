# Multi-stage build for production.
#
# Stage 1: Install dependencies in a clean environment
# Stage 2: Copy only what's needed into a slim runtime image
#
# Why multi-stage?
# - Build deps (compilers, dev tools) stay out of the final image
# - Smaller image = faster deploys, smaller attack surface
# - Reproducible builds

# --- Stage 1: Builder ---
FROM python:3.10-slim AS builder

WORKDIR /app

# Install build dependencies
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Copy project files
COPY pyproject.toml .
COPY src/ src/

# Install the package
RUN pip install --no-cache-dir .

# --- Stage 2: Runtime ---
FROM python:3.10-slim AS runtime

# Security: run as non-root user
RUN groupadd -r medscribe && useradd -r -g medscribe medscribe

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
COPY --from=builder /usr/local/bin/uvicorn /usr/local/bin/uvicorn
COPY --from=builder /app/src /app/src

# Switch to non-root user
USER medscribe

# Health check — Docker and orchestrators use this
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health')" || exit 1

EXPOSE 8000

# Production server command
# Workers = 2 * CPU cores + 1 (standard formula)
CMD ["uvicorn", "medscribe.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
