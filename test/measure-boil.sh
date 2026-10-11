#!/usr/bin/env bash
# Run the drag harness in chromium for both boil variants and collect results.
set -u
CH=/nix/store/4vv4mnj1qp9m4k0lgxcnxsyvdlf4i1r7-ungoogled-chromium-152.0.7977.82/bin/chromium
OUT=/tmp/boil-verdict.txt
: > "$OUT"

run() {
  local label="$1" query="$2"
  rm -f /tmp/harness-result.json
  "$CH" --headless=new --disable-gpu --no-first-run \
        --user-data-dir="/tmp/chrome-tiers-$label" --window-size=950,900 \
        "http://127.0.0.1:8731/test/drag-harness.html$query" >/dev/null 2>&1 &
  local pid=$!
  # Wait for a FINAL verdict, not the heartbeat: the heartbeat posts fails=-1
  # and an existence test treats it as done.
  for _ in $(seq 1 60); do
    if python3 -c "import json,sys; d=json.load(open('/tmp/harness-result.json')); sys.exit(0 if d.get('fails',-1) >= 0 else 1)" 2>/dev/null; then break; fi
    sleep 1
  done
  sleep 1
  kill $pid 2>/dev/null
  {
    echo "######## $label  (chromium 152, --disable-gpu so raster is on the CPU, 390x844 iframe)"
    python3 - <<'PY'
import json
try:
    d = json.load(open('/tmp/harness-result.json'))
except Exception as e:
    print('NO RESULT:', e); raise SystemExit
keep = ('variant under test', 'filtered area', 'dropped frames', 'SCROLLING', 'FAIL')
for line in d.get('text', '').split('\n'):
    if any(k in line for k in keep):
        print(' ', line.strip())
print('  fails:', d.get('fails'))
PY
  } >> "$OUT" 2>&1
}

run plain-cards ""
run boiled-cards "?boil=cards"
echo "DONE" >> "$OUT"
