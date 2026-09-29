#!/bin/sh
# Print a Symphony's state, spend, reason and last timeline marks.
curl -s "http://127.0.0.1:8766/v1/symphonies/$1" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print(d.get('state'), d.get('spend_usd'), '|', (d.get('blocked_reason') or d.get('result') or '')[:400])
print('timeline:', d.get('timeline', [])[-6:])
print('attempts:', [(a['attempt_id'], a['state']) for a in d.get('attempts', [])])
"
