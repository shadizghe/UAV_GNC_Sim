# Backend image — FastAPI service wrapping the simulator in src/.
#
# Built from the project root so we can COPY both `src/` (the sim core)
# and `backend/` (the API layer) in a single context.  The .dockerignore
# at the repo root keeps the heavy folders (.venv, .next, node_modules)
# out of the build context.

FROM python:3.12-slim AS runtime

# Faster, deterministic Python runtime defaults
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System deps for scientific stack (numpy/scipy wheels are precompiled,
# but `gcc` keeps the door open for any source-only fallback packages).
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first so this layer caches across code changes.
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install -r backend/requirements.txt

# App code — sim core + API surface.
COPY src     ./src
COPY backend ./backend

EXPOSE 8000

# Container-side health probe used by docker-compose.
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
