#!/usr/bin/env bash
# Stop running GhostRoll CLI processes (watch / run / setup / doctor).
# Usage: ./scripts/kill-ghostroll.sh
# Optional: FORCE=1 to SIGKILL after ~1s if TERM did not exit.

set -euo pipefail

pids() {
  pgrep -f 'ghostroll\.cli:main|/ghostroll( |$)| -m ghostroll ' 2>/dev/null || true
}

collect_pids() {
  pids | tr '\n' ' ' | sed 's/[[:space:]]*$//'
}

PIDS=$(collect_pids)
if [[ -z "${PIDS// }" ]]; then
  echo "No GhostRoll processes found."
  exit 0
fi

echo "Sending SIGTERM to: ${PIDS}"
# shellcheck disable=SC2086
kill -TERM ${PIDS} 2>/dev/null || true

if [[ "${FORCE:-0}" == "1" ]]; then
  sleep 1
  LEFT=$(collect_pids)
  if [[ -n "${LEFT// }" ]]; then
    echo "Sending SIGKILL to: ${LEFT}"
    # shellcheck disable=SC2086
    kill -KILL ${LEFT} 2>/dev/null || true
  fi
else
  for _ in $(seq 1 15); do
    LEFT=$(collect_pids)
    [[ -z "${LEFT// }" ]] && break
    sleep 0.2
  done
  LEFT=$(collect_pids)
  if [[ -n "${LEFT// }" ]]; then
    echo "Still running after TERM; sending SIGKILL to: ${LEFT}"
    # shellcheck disable=SC2086
    kill -KILL ${LEFT} 2>/dev/null || true
  fi
fi

sleep 0.1
LEFT=$(collect_pids)
if [[ -z "${LEFT// }" ]]; then
  echo "Done."
  exit 0
fi
echo "Warning: processes may still exist: ${LEFT}"
exit 1
