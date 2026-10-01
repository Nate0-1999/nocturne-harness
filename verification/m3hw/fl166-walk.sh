#!/bin/zsh
# FL-166 walk, one fresh run: a home with no write access is refused at start, and doctor shows
# the running daemon's memory against its threshold. usage: fl166-walk.sh <run> <receipt-file>
# Needs the test palace's SPINE_URL, SPINE_TOKEN and OPENROUTER_API_KEY in the environment (never
# printed): a home on main with an app newer than main would offer to update main at `up`.
run=$1; receipt=$2
root=/private/tmp/m3hw-fl166/run$run
rm -rf $root; mkdir -p $root/work; cd $root/work
export NOCTURNE_HOME=$root/home
nocturne=/private/tmp/m3hw-final/harness/.venv/bin/nocturne
watch_gcloud() {  # only this doctor's children: the owner's own gcloud commands are never touched
  while kill -0 $1 2>/dev/null; do
    for child in $(pgrep -P $1); do
      age=$(ps -o etime= -p $child | awk -F'[:-]' '{n=NF; s=$n+60*$(n-1); if (n>2) s+=3600*$(n-2); print s}')
      if [ "${age:-0}" -gt 30 ]; then
        echo "(watcher: ended $(ps -o command= -p $child | cut -c1-80) after ${age} s)"; pkill -TERM -P $child; kill -TERM $child
      fi
    done
    sleep 2
  done
}
{
  echo "# FL-166 run $run — $(date '+%Y-%m-%d %H:%M:%S %Z'), scratch home run$run, harness $(git -C /private/tmp/m3hw-final/harness rev-parse --short HEAD)"
  echo '$ echo n | nocturne init --verification --remote <test palace URL>'
  echo n | $nocturne init --verification --remote "$SPINE_URL" 2>&1 | tail -1
  grep -q '^NOCTURNE_PALACE_NAME="main"' $NOCTURNE_HOME/env && { echo 'home is named main; stopping before up'; exit 1; }
  mkdir -p $NOCTURNE_HOME/transcripts && chmod 0500 $NOCTURNE_HOME/transcripts
  echo '$ chmod 0500 <home>/transcripts; echo n | nocturne up --no-open'
  echo n | $nocturne up --no-open 2>&1 | tail -3; echo "(exit ${pipestatus[2]})"
  chmod 0700 $NOCTURNE_HOME/transcripts
  echo '$ chmod 0700 <home>/transcripts; nocturne up --no-open &   (then wait for the app)'
} > $receipt
(echo n | $nocturne up --no-open > $root/up.log 2>&1) &
for i in $(seq 1 90); do curl -s -o /dev/null http://127.0.0.1:8765/ && break; sleep 1; done
sleep 5
{
  grep -m1 "Nocturne is running" $root/up.log
  echo '$ nocturne doctor   (a watcher ends a gcloud call of this doctor stalled over 30 s; F167)'
  PYTHONUNBUFFERED=1 perl -e 'alarm 600; exec @ARGV' $nocturne doctor > $root/doctor.txt 2>&1 &
  doctor=$!; watch_gcloud $doctor > $root/watcher.txt; wait $doctor
  grep -v -i "token\|key" $root/doctor.txt; cat $root/watcher.txt
  echo "(daemon rss by ps: $(ps -o rss= -p $(lsof -nP -iTCP:8765 -sTCP:LISTEN -t) | awk '{printf "%.1f MiB", $1/1024}'))"
} >> $receipt
pkill -TERM -f "^/private/tmp/m3hw-final/harness/.venv/bin/python3? /private/tmp/m3hw-final/harness/.venv/bin/nocturne up" 2>/dev/null  # only this runner's
for i in $(seq 1 30); do lsof -nP -iTCP:8765 -sTCP:LISTEN -t >/dev/null || break; sleep 1; done
echo "(stopped; 8765 $(lsof -nP -iTCP:8765 -sTCP:LISTEN -t >/dev/null && echo still held || echo free))" >> $receipt
