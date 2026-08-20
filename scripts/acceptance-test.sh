#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLUGIN_ID="io.github.josephbriones.clearread"
REAL=false

usage() {
  printf '%s\n' \
    'Usage: bash scripts/acceptance-test.sh [--real]' \
    '' \
    'The default opens deterministic sample text without screen or clipboard access.' \
    '--real interactively verifies both active-window and selected-region OCR.'
}

while (( $# > 0 )); do
  case "$1" in
    --real)
      REAL=true
      ;;
    --help | -h)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown option: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

bash "$ROOT/scripts/validate.sh"

for command_name in omarchy omarchy-shell; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    printf 'FAIL: %s is required for desktop acceptance\n' "$command_name" >&2
    exit 1
  fi
done

if [[ ${XDG_SESSION_TYPE:-} != "wayland" || -z ${HYPRLAND_INSTANCE_SIGNATURE:-} ]]; then
  printf '%s\n' 'FAIL: run desktop acceptance inside an active Omarchy Hyprland session' >&2
  exit 1
fi

cleanup() {
  omarchy-shell shell hide "$PLUGIN_ID" >/dev/null 2>&1 || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

plugin_call() {
  omarchy-shell "$PLUGIN_ID" "$@"
}

wait_for_ping() {
  local attempt
  for (( attempt = 0; attempt < 100; attempt++ )); do
    [[ $(plugin_call ping 2>/dev/null || true) == "ok" ]] && return 0
    sleep 0.1
  done
  return 1
}

wait_for_state() {
  local wanted=$1 expected_mode=${2:-} attempt state
  for (( attempt = 0; attempt < 100; attempt++ )); do
    state=$(plugin_call state 2>/dev/null || true)
    if python3 - "$wanted" "$expected_mode" "$state" <<'PY'
import json
import sys

wanted, expected_mode, raw = sys.argv[1:]
try:
    state = json.loads(raw)
except (TypeError, ValueError):
    raise SystemExit(1)

if wanted == "demo-reading":
    ok = (
        state.get("open") is True
        and state.get("demo") is True
        and state.get("state") == "reading"
        and state.get("running") is False
        and state.get("characters", 0) > 0
    )
elif wanted == "closed":
    ok = (
        state.get("open") is False
        and state.get("running") is False
        and state.get("characters", 0) == 0
    )
elif wanted == "ready":
    ok = (
        state.get("open") is True
        and state.get("state") == "ready"
        and state.get("ready") is True
        and state.get("running") is False
    )
elif wanted == "real-reading":
    ok = (
        state.get("open") is True
        and state.get("demo") is False
        and state.get("state") == "reading"
        and state.get("running") is False
        and state.get("mode") == expected_mode
        and state.get("characters", 0) > 0
    )
else:
    ok = False
raise SystemExit(0 if ok else 1)
PY
    then
      return 0
    fi
    sleep 0.1
  done
  return 1
}

summon() {
  local payload=$1 result
  result=$(omarchy-shell shell summon "$PLUGIN_ID" "$payload")
  if [[ $result != "ok" ]]; then
    printf 'FAIL: shell summon returned %s\n' "$result" >&2
    exit 1
  fi
  wait_for_ping || { printf 'FAIL: plugin IPC did not register\n' >&2; exit 1; }
}

close_and_verify() {
  omarchy-shell shell hide "$PLUGIN_ID" >/dev/null
  wait_for_state closed || {
    printf 'FAIL: ClearRead did not close and dispose its document\n' >&2
    exit 1
  }
}

printf '%s\n' '==> Summoning deterministic no-capture demo'
summon '{"demo":true}'
wait_for_state demo-reading || {
  printf 'FAIL: demo did not reach a non-empty, process-free reading state\n' >&2
  exit 1
}

printf '%s\n' '==> Closing demo and checking content disposal'
close_and_verify

if [[ $REAL == "false" ]]; then
  printf '%s\n' 'PASS: deterministic demo opened and closed without capture'
  exit 0
fi

if [[ ! -t 0 ]]; then
  printf '%s\n' 'NOT PERFORMED: real capture acceptance requires an interactive terminal.' >&2
  exit 3
fi

run_real_capture() {
  local expected_mode=$1 instruction=$2

  printf '\n==> Opening ClearRead for %s capture\n' "$expected_mode"
  summon '{}'
  wait_for_state ready || {
    printf 'FAIL: readiness surface did not settle for %s capture\n' "$expected_mode" >&2
    exit 1
  }

  printf '%s\n' "$instruction"
  printf '%s\n' 'Use generated, non-sensitive fixture text. Return here and press Enter only after the reader appears.'
  read -r

  wait_for_state real-reading "$expected_mode" || {
    printf 'FAIL: ClearRead did not return a non-empty %s OCR result\n' "$expected_mode" >&2
    exit 1
  }
  close_and_verify
  printf 'Verified: %s OCR returned text and closed cleanly.\n' "$expected_mode"
}

run_real_capture window \
  'Choose “Read active window” using only the keyboard; the target window must contain the fixture text.'
run_real_capture region \
  'Choose “Select screen area”, select the fixture text, and confirm the ClearRead surface is absent from the captured pixels.'

printf '%s\n' 'PASS: active-window and selected-region OCR both reached reading state and closed cleanly'
