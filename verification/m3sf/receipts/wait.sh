#!/bin/sh
# Wait until a Symphony leaves "running" (or 30 minutes pass), then print its state.
for i in $(seq 1 360); do
  s=$(curl -s "http://127.0.0.1:8766/v1/symphonies/$1" | python3 -c "import json,sys; print(json.load(sys.stdin).get('state'))" 2>/dev/null)
  [ "$s" != "running" ] && break
  sleep 5
done
date; /private/tmp/m3sf-verification/receipts/state.sh "$1"
