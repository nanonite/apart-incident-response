default: test

setup:
    UV_CACHE_DIR=.uv-cache uv sync

test: setup
    if command -v bwrap >/dev/null 2>&1; then ./scripts/test; else nix develop --command ./scripts/test; fi
