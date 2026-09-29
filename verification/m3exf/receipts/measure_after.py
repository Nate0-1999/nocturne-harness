"""Same sampling as measure.py, but the way the fixed daemon calls it: one folds cache."""

import resource
import sys
import time
from pathlib import Path

from harness.transcript import TranscriptJournal
from harness.visualization import work_observation

root = Path(sys.argv[1])
journal = TranscriptJournal(root / "transcripts")
folds, times = {}, []
for _ in range(int(sys.argv[3])):
    started = time.monotonic()
    observation = work_observation(journal, root, Path(sys.argv[2]), folds)
    times.append(time.monotonic() - started)
peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1_000_000
print(
    f"samples={len(times)} first={times[0]:.2f}s later_avg={sum(times[1:]) / max(1, len(times) - 1):.3f}s peak_rss={peak:.0f} MB agents={len(observation['agents'])}"  # noqa: E501
)
