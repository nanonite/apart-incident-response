#!/usr/bin/env bash
# Scoped adapter for the installed OpenCode Chainlink loop: legal offline tasks.
set -euo pipefail

usage() {
  printf '%s\n' \
    'Usage: bash scripts/jev_legal_chainlink_loop.sh [--dry-run|--run]' \
    'Dispatches #219 #220 #221 #227 #222 #223 #224, one task at a time.' \
    'Stops before #225, the separate user authorization gate.' \
    'Env: JEV_LEGAL_WORKER_MODEL and JEV_LEGAL_REVIEWER_MODEL' \
    '     default to opencode-go/mimo-v2.6-flash.'
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
worker_model=${JEV_LEGAL_WORKER_MODEL:-opencode-go/mimo-v2.6-flash}
reviewer_model=${JEV_LEGAL_REVIEWER_MODEL:-opencode-go/mimo-v2.6-flash}
worker_timeout=${JEV_LEGAL_WORKER_TIMEOUT:-3600}
reviewer_timeout=${JEV_LEGAL_REVIEWER_TIMEOUT:-1800}
for value in "$worker_timeout" "$reviewer_timeout"; do
  [[ "$value" =~ ^[0-9]+$ && "$value" -gt 0 ]] || {
    printf 'Timeouts must be positive integers\n' >&2; exit 2;
  }
done
for dependency in chainlink jq bun; do
  command -v "$dependency" >/dev/null || {
    printf 'Missing dependency: %s\n' "$dependency" >&2; exit 1;
  }
done
[[ -f "$loop_cli" && -f "$CHAINLINK_DB" ]] || {
  printf 'Missing loop CLI or issue database\n' >&2; exit 1;
}

task_ids=(219 220 221 227 222 223 224 225 226)
predecessors=(215 219 220 221 227 222 223 224 225)
for index in "${!task_ids[@]}"; do
  task_id=${task_ids[$index]}
  issue=$(chainlink --json issue show "$task_id")
  expected_parent=218
  if [[ "$task_id" == 227 ]]; then expected_parent=159; fi
  jq -e --argjson id "$task_id" \
    --argjson parent "$expected_parent" \
    '.id == $id and .parent_id == $parent and (.status == "open" or .status == "closed")' \
    <<<"$issue" >/dev/null || {
      printf 'Unexpected task identity/status: #%s\n' "$task_id" >&2; exit 1;
    }
  expected_blocker=${predecessors[$index]}
  jq -e --argjson blocker "$expected_blocker" \
    '.blocked_by == [$blocker]' <<<"$issue" >/dev/null || {
      printf 'Unexpected dependency on #%s\n' "$task_id" >&2; exit 1;
    }
done

for index in 0 1 2 3 4 5 6; do
  task_id=${task_ids[$index]}
  issue=$(chainlink --json issue show "$task_id")
  [[ $(jq -r '.status' <<<"$issue") == closed ]] && continue
  predecessor=${predecessors[$index]}
  before=$(chainlink --json issue show "$predecessor")
  if [[ $(jq -r '.status' <<<"$before") != closed ]]; then
    printf 'PAUSED: #%s is blocked by open #%s.\n' "$task_id" "$predecessor"
    exit 0
  fi
  if [[ "$task_id" == 223 || "$task_id" == 224 ]] && \
     [[ ! -f runs/next-phase/legal/jev-legal-p04-discovery-registration-v1.json ]]; then
    printf 'PAUSED: #222 has no runnable legal discovery registration.\n'
    exit 0
  fi
  if [[ "$mode" == --dry-run ]]; then
    printf 'Next offline legal task: #%s\n' "$task_id"
    exec bun "$loop_cli" --task "$task_id" --max-tasks 1 --attempts 3 \
      --review-first never --worker-model "$worker_model" \
      --reviewer-model "$reviewer_model" --worker-timeout "$worker_timeout" \
      --reviewer-timeout "$reviewer_timeout" --dry-run
  fi
  cli_status=0
  bun "$loop_cli" --task "$task_id" --max-tasks 1 --attempts 3 \
    --review-first never --worker-model "$worker_model" \
    --reviewer-model "$reviewer_model" --worker-timeout "$worker_timeout" \
    --reviewer-timeout "$reviewer_timeout" \
    --prompt 'Offline Jev research design only. For #227 audit complete task families and prospective full tasks, not microbenchmarks. No provider calls, probes, live journals, authorization inference, or modification of frozen hypothesis artifacts. Verify evidence and acceptance checks before closing.' || cli_status=$?
  after=$(chainlink --json issue show "$task_id")
  if (( cli_status != 0 )) || [[ $(jq -r '.status' <<<"$after") != closed ]]; then
    printf 'PAUSED: #%s unfinished after loop (CLI exit %s); no successor dispatched.\n' "$task_id" "$cli_status"
    exit 1
  fi
  printf 'Task #%s completed after review.\n' "$task_id"
done
printf 'PAUSED at #225: separate explicit legal discovery authorization required.\n'
