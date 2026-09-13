# syntax=docker/dockerfile:1.7

ARG PYTHON_VERSION=3.12.14
ARG BUN_VERSION=1.4.2
ARG NODE_VERSION=24.19.0

FROM oven/bun:${BUN_VERSION}-slim AS bun

FROM node:${NODE_VERSION}-bookworm-slim AS pi-build

COPY --from=bun /usr/local/bin/bun /usr/local/bin/bun

WORKDIR /opt/pi

COPY pi ./
# Fail fast with an actionable message when the `pi` submodule has not been
# checked out. A fresh clone leaves `pi/` empty; `COPY pi ./` then yields a
# bare directory and `npm ci` fails with an unhelpful "no package.json" error.
# The `just` recipes chain `setup` (git submodule update --init --recursive),
# but a bare `docker compose build` must fail here, not silently upstream.
RUN test -f package.json && test -f package-lock.json || \
    (echo "pi submodule is not checked out" >&2; \
     echo "run: just setup   (or: git submodule update --init --recursive)" >&2; \
     exit 1)
RUN --mount=type=cache,target=/root/.npm \
    npm ci --omit=dev --ignore-scripts \
    && npm --prefix packages/ai run generate-models \
    && find packages -type d -name src -exec sh -c \
        'package="${1%/src}"; ln -s src "$package/dist"' _ {} \;

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

COPY pi-extension ./pi-extension
COPY scripts/task_one_calibration.py ./scripts/task_one_calibration.py
COPY scripts/run_experiment.py ./scripts/run_experiment.py
COPY scripts/ollama_goal_inference.py scripts/qwen3_full_logits.py ./scripts/
COPY tests ./tests
RUN python -m unittest discover -s tests -v

FROM base AS runtime

LABEL org.opencontainers.image.title="Apart incident response runtime" \
      org.opencontainers.image.description="Capability-restricted runtime for the accidental-coordination experiment"

COPY --from=pi-build /opt/pi/package.json /opt/pi/package-lock.json /opt/pi/
COPY --from=pi-build /opt/pi/node_modules /opt/pi/node_modules
COPY --from=pi-build /opt/pi/packages /opt/pi/packages

RUN mkdir -p /app/artifacts

ENTRYPOINT ["/usr/bin/tini", "--", "python", "-m", "apart_incident_response.runtime"]
CMD ["validate-config", "config/runtime.json"]

FROM runtime AS pi-smoke

ENV APART_PI_ROOT=/opt/pi

COPY pi-extension ./pi-extension
COPY tests/fixtures/pi-faux-provider.ts ./tests/fixtures/pi-faux-provider.ts
COPY scripts/pi_extension_smoke.py ./scripts/pi_extension_smoke.py
RUN python scripts/pi_extension_smoke.py --output /tmp/pi-extension-smoke-trace.json

FROM debian:bookworm-slim AS report

RUN apt-get update \
    && apt-get install --no-install-recommends --yes \
        biber \
        cm-super \
        latexmk \
        texlive-bibtex-extra \
        texlive-fonts-extra \
        texlive-fonts-recommended \
        texlive-lang-greek \
        texlive-latex-extra \
        texlive-latex-recommended \
        texlive-plain-generic \
        texlive-pictures \
        texlive-science \
        tipa \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/report

COPY report ./
RUN latexmk -C main.tex \
    && latexmk -pdf main.tex
