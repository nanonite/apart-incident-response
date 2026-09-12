# syntax=docker/dockerfile:1.7

ARG PYTHON_VERSION=3.12.14
ARG BUN_VERSION=1.4.2
ARG NODE_VERSION=24.19.0

FROM oven/bun:${BUN_VERSION}-slim AS bun

FROM node:${NODE_VERSION}-bookworm-slim AS pi-build

RUN apt-get update \
    && apt-get install --no-install-recommends --yes \
        bash \
        ca-certificates \
        git \
        ripgrep \
    && rm -rf /var/lib/apt/lists/*

COPY --from=bun /usr/local/bin/bun /usr/local/bin/bun

WORKDIR /opt/pi

COPY pi ./
RUN npm ci --ignore-scripts \
    && npm --prefix packages/ai run generate-models

FROM python:${PYTHON_VERSION}-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

RUN apt-get update \
    && apt-get install --no-install-recommends --yes \
        bubblewrap \
        ca-certificates \
        tini \
    && rm -rf /var/lib/apt/lists/*

COPY --from=bun /usr/local/bin/bun /usr/local/bin/bun

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY config ./config
COPY src ./src

FROM base AS test

COPY tests ./tests
RUN python -m unittest discover -s tests -v

FROM test AS runtime

LABEL org.opencontainers.image.title="Apart incident response runtime" \
      org.opencontainers.image.description="Capability-restricted runtime for the accidental-coordination experiment"

COPY --from=pi-build /opt/pi /opt/pi

RUN mkdir -p /app/artifacts

ENTRYPOINT ["/usr/bin/tini", "--", "python", "-m", "apart_incident_response.runtime"]
CMD ["validate-config", "config/runtime.json"]
