# syntax=docker/dockerfile:1

# python:3.12-slim, not the full python:3.12 image or alpine:
#   - full image: ~300MB extra of build tooling/docs we never use at runtime.
#   - alpine: musl libc instead of glibc breaks silently on some scientific
#     Python wheels (numpy/pydantic-core's compiled extensions) with cryptic
#     errors - not worth the ~40MB saved for a project this size.
# When to change: if a future dependency needs apt packages not on Debian's
# slim image (rare), or if image size becomes an actual problem (it won't,
# at this scale).
FROM python:3.12-slim

WORKDIR /app

# Copy requirements BEFORE app code so Docker's layer cache keeps the
# (slow) pip install step cached across rebuilds that only change app code -
# the single most common Docker build-speed mistake to avoid.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# Runs as a non-root user inside the container. Doesn't change anything
# about EKS's own pod security (that's enforced at the cluster/PodSpec
# level, not the image level), but it's a basic container-hardening habit
# worth having by default rather than retrofitting later.
RUN useradd --create-home --uid 1000 appuser
USER appuser

EXPOSE 8000

# --host 0.0.0.0, not 127.0.0.1: inside a container, 127.0.0.1 is only
# reachable from within the container's own network namespace - Kubernetes'
# Service/kubelet health checks and all external traffic arrive from
# outside that namespace and need 0.0.0.0 to be accepted at all.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
