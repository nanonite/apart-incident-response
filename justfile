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

# Verify Docker from the trusted outer session before starting any controller.
# This host-specific target is opt-in and does not affect other machines.
docker-check:
    docker info >/dev/null
    @echo "Docker server reachable from the outer controller session"

pi-smoke: setup
    docker build --target pi-smoke --output type=cacheonly .

report: setup
    docker build --target report --output type=cacheonly .

# Run the deterministic fake-provider lifecycle check in the container. This
# host-specific target is opt-in, and produces harness evidence only; it is
# never experimental model data.
container-harness: setup
    docker compose run --rm --build matrix --harness-check --output /app/runs/container-harness

# Check the Docker and nested Bubblewrap boundaries without launching Pi or a
# model. The JSON result is stored under the mounted workspace runs directory.
container-isolation: setup
    docker compose run --rm --build --entrypoint python matrix scripts/container_isolation_check.py --output /app/runs/container-isolation.json

# Run the real C0/C1/C2 controller in the container. This host-specific target
# is opt-in. The host credential is mounted read-only for the controller only;
# it is never placed in argv.
container-anchor output="t1-container" seeds="1" model="" run_id="": setup
    #!/usr/bin/env bash
    set -euo pipefail
    output="{{ output }}"; output="${output#output=}"
    seeds="{{ seeds }}"; seeds="${seeds#seeds=}"
    model="{{ model }}"; model="${model#model=}"
    run_id="{{ run_id }}"; run_id="${run_id#run_id=}"
    read -r -a seed_values <<< "$seeds"
    args=(--real-anchor --seeds "${seed_values[@]}" --output "/app/runs/$output")
    mount_args=()
    selected_model="$model"
    if [[ -n "$selected_model" ]]; then
        args+=(--model "$selected_model")
    fi
    if [[ -n "$run_id" ]]; then
        args+=(--run-id "$run_id")
    fi
    if [[ "$selected_model" == opencode-go/* ]]; then
        : "${APART_OPENCODE_API_KEY_FILE:?set APART_OPENCODE_API_KEY_FILE to a private OpenCode key file}"
        mount_args+=(--volume "$APART_OPENCODE_API_KEY_FILE:/run/secrets/opencode-key:ro")
    elif [[ "$selected_model" == openrouter/* ]]; then
        : "${APART_OPENROUTER_API_KEY_FILE:?set APART_OPENROUTER_API_KEY_FILE to a private OpenRouter key file}"
        mount_args+=(--volume "$APART_OPENROUTER_API_KEY_FILE:/run/secrets/openrouter-key:ro")
    else
        : "${APART_PI_AUTH_FILE:?set APART_PI_AUTH_FILE to a private Pi/Codex auth file}"
        mount_args+=(--volume "$APART_PI_AUTH_FILE:/run/secrets/pi-auth.json:ro")
    fi
    docker compose run --rm --build "${mount_args[@]}" matrix "${args[@]}"

# Local Qwen3-8B (4-bit) model server for the one-shot /goal logprobs path.
ollama-up:
    docker compose up -d ollama

ollama-pull:
    docker compose exec ollama ollama pull qwen3:8b

# Run one-shot /goal inference with token logprobs and dump the entropy artifact.

goal-model := "qwen3:8b"
goal-host := "http://localhost:11434"
goal-output := "runs/qwen3-8b/logprobs"

goal: ollama-pull
    just qwen logprobs \
        "The capital of France is" \
        1 \
        {{ goal-output }} \
        {{ goal-model }} \
        {{ goal-host }}

# Run either the existing Ollama token-logprob mode or the full-vocabulary
# Transformers/Unsloth mode. Empty output/model values use mode-specific

# defaults; explicit values make paired prompts, seeds, and run IDs reproducible.
qwen mode="logprobs" prompt="The capital of France is" seed="1" output="" model="" host="http://localhost:11434" run_id="":
    @mode="{{ mode }}"; mode="${mode#mode=}"; \
    prompt="{{ prompt }}"; prompt="${prompt#prompt=}"; \
    seed="{{ seed }}"; seed="${seed#seed=}"; \
    output="{{ output }}"; output="${output#output=}"; \
    model="{{ model }}"; model="${model#model=}"; \
    host="{{ host }}"; host="${host#host=}"; \
    run_id="{{ run_id }}"; run_id="${run_id#run_id=}"; \
    set -- python3 scripts/qwen3_goal.py --mode "$mode" --prompt "$prompt" --seed "$seed" --host "$host"; \
    if [ -n "$output" ]; then set -- "$@" --output "$output"; fi; \
    if [ -n "$model" ]; then set -- "$@" --model "$model"; fi; \
    if [ -n "$run_id" ]; then set -- "$@" --run-id "$run_id"; fi; \
    "$@"

# Build the isolated CUDA runtime; weights remain in the compose-mounted cache.
qwen-runtime:
    docker compose -f compose.qwen3.yaml build qwen3

# Run the real C0/C1/C2 anchor matrix against local Ollama Qwen3-8B inside the
# same containerized runtime image used elsewhere in the repository. Pass
# agent_count=2 for the genuine two-role Task 1 fixture.
qwen3-experiment output="runs/qwen3-8b/manual" seeds="1" agent_count="" ollama_host="http://localhost:11434": build
    #!/usr/bin/env bash
    set -euo pipefail
    output="{{ output }}"; output="${output#output=}"
    seeds="{{ seeds }}"; seeds="${seeds#seeds=}"
    ollama_host="{{ ollama_host }}"; ollama_host="${ollama_host#ollama_host=}"
    agent_count="{{ agent_count }}"; agent_count="${agent_count#agent_count=}"
    read -r -a seed_values <<< "$seeds"
    args=(--real-anchor --model ollama/qwen3:8b --seeds "${seed_values[@]}" --output "$output")
    if [[ -n "$agent_count" ]]; then
        args+=(--agent-count "$agent_count")
    fi
    docker run --rm --network host \
        --cap-add SYS_ADMIN --cap-add NET_ADMIN \
        --security-opt seccomp=unconfined --security-opt apparmor=unconfined \
        -e APART_PI_ROOT=/opt/pi \
        -e OLLAMA_HOST="$ollama_host" \
        -v "$(pwd)/scripts:/app/scripts" \
        -v "$(pwd)/pi-extension:/app/pi-extension" \
        -v "$(pwd)/config:/app/config" \
        -v "$(pwd)/runs:/app/runs" \
        --entrypoint python \
        apart-incident-response:local scripts/run_experiment.py "${args[@]}"
    docker run --rm -v "$(pwd)/runs:/runs" alpine chown -R "$(id -u):$(id -g)" /runs
    find "$output" -type d -name home -exec rm -rf {} +
