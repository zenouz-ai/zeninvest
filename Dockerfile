# Stage 1: Build frontend
FROM node:20-slim AS frontend-builder

# Accept API key at build time so it can be baked into the Vite bundle as VITE_API_KEY.
# Pass via: docker build --build-arg DASHBOARD_API_KEY=<value>
# or via docker-compose args section (see docker-compose.yml).
ARG DASHBOARD_API_KEY=""
ENV VITE_API_KEY=${DASHBOARD_API_KEY}

WORKDIR /app

COPY dashboard/frontend/package.json dashboard/frontend/package-lock.json ./
RUN npm ci

COPY dashboard/frontend/ ./
RUN npm run build

# Stage 2: Python application
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN pip install --no-cache-dir poetry==1.8.5

# Copy dependency files first for caching
COPY pyproject.toml poetry.lock ./

# Install dependencies (no dev deps in production)
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi --without dev

# Copy application code
COPY src/ src/
COPY config/ config/
COPY docs/ docs/
COPY alembic.ini ./
COPY dashboard/ dashboard/

# Copy built frontend from stage 1
COPY --from=frontend-builder /app/dist dashboard/frontend/dist

# Create directories for volumes
RUN mkdir -p data journals/daily journals/weekly logs

# Run migrations on startup, then start scheduler
CMD ["sh", "-c", "alembic upgrade head && python -m src.scheduler.scheduler"]
