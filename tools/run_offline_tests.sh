#!/usr/bin/env bash
# Render Studio's tests that need no Blender. Run from the repository: bash tools/run_offline_tests.sh <IngeTrazo source>
[ -d "$1" ] || { echo "usage: $0 <IngeTrazo source folder>"; exit 2; }
SRC="$(cd "$1" && (pwd -W 2>/dev/null || pwd))"; PY="${PYTHON:-python}"
export QT_QPA_PLATFORM=offscreen PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1 RENDER_STUDIO_HOME="$(mktemp -d)"
pass=0; fail=""
for t in tests/test_*offline*.py; do
  case "$t" in *blender*|*_job_*|tests/test_offline.py|*outlines_proxies*|*pbr_offline*) continue;; esac
  if timeout 240 "$PY" "$t" "$SRC" . >"$RENDER_STUDIO_HOME/log.txt" 2>&1; then pass=$((pass+1))
  else fail="$fail $t"; echo "== $t"; grep -E "^FAIL|Error" "$RENDER_STUDIO_HOME/log.txt" | head -5; fi
done
echo "passed $pass; failed:$fail"
[ -z "$fail" ]
