#!/usr/bin/env bash
# Project-scoped adapter for the installed OpenCode deterministic loop CLI.
set -euo pipefail

usage() {
  printf '%s\n' 'Usage: bash scripts/jev_chainlink_loop.sh [--dry-run|--run]' \
    'Default: read-only preflight and plugin dry-run.' \
    'Runs only #202-#215, one task at a time; stops at open authorization gates.' \
    'Set JEV_LOOP_CLI to override the installed plugin CLI entrypoint.' \
    'Env: JEV_WORKER_TIMEOUT (default 7200s), JEV_REVIEWER_TIMEOUT (default 1800s).' \
    'Env: JEV_WORKER_MODEL (default opencode-go/gpt-6-luna),' \
    '     JEV_REVIEWER_MODEL (default opencode-go/mimo-v2.6-flash).'
}

mode=${1:---dry-run}
if [[ $# -gt 1 ]]; then usage >&2; exit 2; fi
case "$mode" in
  --help|-h) usage; exit 0 ;;
  --dry-run|--run) ;;
  *) usage >&2; exit 2 ;;
esac

project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd -- "$project_root"
export CHAINLINK_DB="$project_root/.chainlink/issues.db"
loop_cli=${JEV_LOOP_CLI:-/home/framework/GitRepos/opencode-chainlink-loop-plugin/bin/chainlink-loop}
# Per-step ceilings the plugin CLI otherwise defaults to 3600s/1800s. P02
# exceeded 3600s, so the worker timeout is deliberately raised here.
worker_timeout=${JEV_WORKER_TIMEOUT:-7200}
reviewer_timeout=${JEV_REVIEWER_TIMEOUT:-1800}
worker_model=${JEV_WORKER_MODEL:-opencode-go/gpt-6-luna}
reviewer_model=${JEV_REVIEWER_MODEL:-opencode-go/mimo-v2.6-flash}
[[ "$worker_timeout" =~ ^[0-9]+$ && "$worker_timeout" -gt 0 ]] || { printf 'JEV_WORKER_TIMEOUT must be a positive integer\n' >&2; exit 2; }
[[ "$reviewer_timeout" =~ ^[0-9]+$ && "$reviewer_timeout" -gt 0 ]] || { printf 'JEV_REVIEWER_TIMEOUT must be a positive integer\n' >&2; exit 2; }
for dependency in chainlink jq bun; do
  command -v "$dependency" >/dev/null || { printf 'Missing dependency: %s\n' "$dependency" >&2; exit 1; }
done
[[ -f "$CHAINLINK_DB" ]] || { printf 'Missing project database: %s\n' "$CHAINLINK_DB" >&2; exit 1; }
[[ -f "$loop_cli" ]] || { printf 'Missing loop CLI: %s\n' "$loop_cli" >&2; exit 1; }

printf 'Project: %s\nDatabase: %s\nScope: #202-#215 under #201\n' "$project_root" "$CHAINLINK_DB"
# Validate the entire scope before dispatching even one worker.
for task_id in {202..215}; do
  issue=$(chainlink --json issue show "$task_id")
  jq -e --argjson id "$task_id" \
    '.id == $id and .parent_id == 201 and (.status == "open" or .status == "closed")' \
    <<<"$issue" >/dev/null || { printf 'Unexpected task identity/status: #%s\n' "$task_id" >&2; exit 1; }
done

for task_id in {202..215}; do
  issue=$(chainlink --json issue show "$task_id")
  if [[ $(jq -r '.status' <<<"$issue") == closed ]]; then continue; fi

  # Always leave explicit research authorization to the dedicated gate workflow.
  if [[ "$task_id" == 206 || "$task_id" == 211 ]]; then
    printf 'PAUSED at authorization gate #%s. Complete its reviewed lock and separate live authorization before continuing.\n' "$task_id"
    exit 0
  fi
  # Check the intended sequence even if a dependency edge was accidentally removed.
  if (( task_id > 202 )); then
    previous=$(chainlink --json issue show "$((task_id - 1))")
    [[ $(jq -r '.status' <<<"$previous") == closed ]] || {
      printf 'PAUSED: predecessor of #%s is still open.\n' "$task_id"; exit 0;
    }
  fi
  for blocker in $(jq -r '.blocked_by[]?' <<<"$issue"); do
    blocker_issue=$(chainlink --json issue show "$blocker")
    [[ $(jq -r '.status' <<<"$blocker_issue") == closed ]] || {
      printf 'PAUSED: #%s is blocked by #%s.\n' "$task_id" "$blocker"; exit 0;
    }
  done

  if [[ "$mode" == --dry-run ]]; then
    printf 'Next task: #%s; invoking plugin dry-run only.\n' "$task_id"
    exec bun "$loop_cli" --task "$task_id" --max-tasks 1 --attempts 20 \
      --review-first never --worker-model "$worker_model" --reviewer-model "$reviewer_model" \
      --worker-timeout "$worker_timeout" --reviewer-timeout "$reviewer_timeout" --dry-run
  fi

  # Never invoke unscoped queue selection; never pass the entire ID list to a
  # runner that might skip an exhausted task and continue to a dependent task.
  # Capture the CLI status instead of letting `set -e` abort here: the PAUSED
  # report and exit 1 below are where an unfinished task must be surfaced.
  cli_status=0
  bun "$loop_cli" --task "$task_id" --max-tasks 1 --attempts 20 \
    --review-first never --worker-model "$worker_model" --reviewer-model "$reviewer_model" \
    --worker-timeout "$worker_timeout" --reviewer-timeout "$reviewer_timeout" || cli_status=$?
  if (( cli_status != 0 )); then
    printf 'Plugin CLI exited %s for #%s; falling through to the status check.\n' "$cli_status" "$task_id" >&2
  fi
  after=$(chainlink --json issue show "$task_id")
  if [[ $(jq -r '.status' <<<"$after") != closed ]]; then
    printf 'PAUSED: #%s remains open after the loop; no successor dispatched.\n' "$task_id"
    exit 1
  fi
  printf 'Task #%s closed after review.\n' "$task_id"
done
printf '%s\n' 'All scoped tasks are closed. Inspect #215 for the scientific outcome; closure alone is not proof of success.'
