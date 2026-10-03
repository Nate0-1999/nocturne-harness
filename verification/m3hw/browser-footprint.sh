#!/bin/zsh
# M3HW soak side log: the soak browser's physical footprint by process every ten minutes, five
# minutes off the soak's own samples (vmmap pauses a process while it reads it).
# usage: browser-footprint.sh <profile-dir> <out.tsv> <until-file-contains> <file>
profile=$1; out=$2; marker=$3; watch=$4
while ! grep -q "$marker" $watch; do
  main=$(pgrep -f -- "--user-data-dir=$profile" | head -1)
  total=0; parts=""
  for pid in $(ps -axo pid=,ppid= | awk -v m=$main '$1==m || $2==m {print $1}'); do
    fp=$(vmmap --summary $pid 2>/dev/null | awk '/^Physical footprint:/{v=$3; u=substr(v,length(v)); n=substr(v,1,length(v)-1); if(u=="G")n*=1024; if(u=="K")n/=1024; print n}')
    kind=$(ps -o command= -p $pid | grep -o -- "--type=[a-z-]*" | cut -d= -f2); parts="$parts ${kind:-browser}=${fp}M"
    total=$(echo "$total + ${fp:-0}" | bc)
  done
  echo "$(date -u +%H:%M:%S)\t${total}M\t$parts" >> $out
  sleep 600
done
