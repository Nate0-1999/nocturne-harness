"""Sample the visualization's work observation the way the daemon does (every 2 s -> here
back to back), and report time per sample and the process's peak RSS."""

import resource
import sys
import time
from pathlib import Path

from harness.transcript import TranscriptJournal
from harness.visualization import work_observation

root = Path(sys.argv[1])
journal = TranscriptJournal(root / "transcripts")
times = []
for _ in range(int(sys.argv[3])):
    started = time.monotonic()
    observation = work_observation(journal, root, Path(sys.argv[2]))
    times.append(time.monotonic() - started)
peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1_000_000  # bytes on macOS
print(
    f"samples={len(times)} first={times[0]:.2f}s later_avg={sum(times[1:]) / max(1, len(times) - 1):.2f}s peak_rss={peak:.0f} MB agents={len(observation['agents'])}"  # noqa: E501
)
