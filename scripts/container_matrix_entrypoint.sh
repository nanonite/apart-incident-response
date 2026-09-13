#!/bin/sh

set -eu

# Docker control belongs to the trusted outer session/controller. Refuse to
# start if a host Docker socket was accidentally added to this runtime.
for socket_path in /run/docker.sock /var/run/docker.sock; do
    if [ -S "$socket_path" ]; then
        echo "refusing matrix runtime: Docker socket must not be mounted" >&2
        exit 64
    fi
done

if [ ! -f /.dockerenv ]; then
    echo "refusing matrix runtime: container marker is unavailable" >&2
    exit 65
fi

# Docker may initialize a named volume with a wider mode. The controller's
# existing validation requires its OAuth parent to be private before use.
mkdir -p /controller-state
chmod 0700 /controller-state

# A bind-mounted OpenCode key is owned by the host user. Copy it to a
# controller-only 0600 path so the runtime's ownership check remains useful;
# the path is never included in the Pi Bubblewrap mounts or child environment.
staged_key=""
key_path="${APART_OPENCODE_API_KEY_FILE:-}"
if [ "$key_path" = "/run/secrets/opencode-key" ] && [ -f "$key_path" ]; then
    umask 077
    mkdir -p /run/controller-secrets
    chmod 0700 /run/controller-secrets
    cp "$key_path" /run/controller-secrets/opencode-key
    chmod 0600 /run/controller-secrets/opencode-key
    export APART_OPENCODE_API_KEY_FILE=/run/controller-secrets/opencode-key
    staged_key=/run/controller-secrets/opencode-key
fi

cleanup() {
    if [ -n "$staged_key" ]; then
        rm -f -- "$staged_key"
        rmdir /run/controller-secrets 2>/dev/null || true
    fi
}
trap cleanup EXIT HUP INT TERM

python scripts/run_experiment.py "$@"
