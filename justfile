default: test

setup:
    git submodule update --init --recursive

build: setup
    docker compose build runtime

test: setup
    docker build --target test --output type=cacheonly .

pi-smoke: setup
    docker build --target pi-smoke --output type=cacheonly .

report: setup
    docker build --target report --output type=cacheonly .
