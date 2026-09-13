default: test

# Check out the `pi` submodule. Required before `build`/`test`/`pi-smoke`
# (the Docker pi-build stage fails fast with a clear message if `pi/` is
# empty). Run this after a fresh clone.
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
goal-output := "runs/qwen3-8b/logprobs/compat-goal"

goal: ollama-pull
    just qwen mode=logprobs \
        prompt="The capital of France is" \
        host={{ goal-host }} \
        model={{ goal-model }} \
        output={{ goal-output }}

# Run either the existing Ollama token-logprob mode or the full-vocabulary
# Transformers/Unsloth mode. Empty output/model values use mode-specific

# defaults; explicit values make paired prompts, seeds, and run IDs reproducible.
qwen mode="logprobs" prompt="The capital of France is" seed="1" output="" model="" host="http://localhost:11434":
    @mode="{{ mode }}"; mode="${mode#mode=}"; \
    prompt="{{ prompt }}"; prompt="${prompt#prompt=}"; \
    seed="{{ seed }}"; seed="${seed#seed=}"; \
    output="{{ output }}"; output="${output#output=}"; \
    model="{{ model }}"; model="${model#model=}"; \
    host="{{ host }}"; host="${host#host=}"; \
    set -- python3 scripts/qwen3_goal.py --mode "$mode" --prompt "$prompt" --seed "$seed" --host "$host"; \
    if [ -n "$output" ]; then set -- "$@" --output "$output"; fi; \
    if [ -n "$model" ]; then set -- "$@" --model "$model"; fi; \
    "$@"

# Build the isolated CUDA runtime; weights remain in the compose-mounted cache.
qwen-runtime:
    docker compose -f compose.qwen3.yaml build qwen3
