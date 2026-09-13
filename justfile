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

# Local Qwen3-8B (4-bit) model server for the one-shot /goal logprobs path.
ollama-up:
    docker compose up -d ollama

ollama-pull:
    docker compose exec ollama ollama pull qwen3:8b

# Run one-shot /goal inference with token logprobs and dump the entropy artifact.
goal-model := "qwen3:8b"
goal-host := "http://localhost:11434"
goal-output := "artifacts/goal/qwen3-8b"

goal: ollama-pull
    python3 scripts/ollama_goal_inference.py \
        --host {{goal-host}} \
        --model {{goal-model}} \
        --prompt "The capital of France is" \
        --num-predict 12 \
        --output {{goal-output}}
