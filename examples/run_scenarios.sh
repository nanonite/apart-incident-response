#!/usr/bin/env bash
set -euo pipefail

# Offline plumbing: five tasks, all three communication conditions, five minutes.
UV_CACHE_DIR=.uv-cache uv run env PYTHONPATH=src python -m apart_incident_response.experiment \
  --db artifacts/fixture-scenarios.sqlite --adapter fixture --tasks inventory schedule cache-incident pipeline campus-security \
  --conditions C0 C1 C2 --steps 5 --unlock-step 3

# Optional local model pass after Ollama has gemma2:2b installed.
UV_CACHE_DIR=.uv-cache uv run env PYTHONPATH=src python -m apart_incident_response.experiment \
  --db artifacts/ollama-scenarios.sqlite --adapter ollama --model gemma2:2b \
  --tasks inventory schedule --conditions C0 C1 C2 --steps 5 --unlock-step 3
