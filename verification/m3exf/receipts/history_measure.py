"""M3EX-37 (history half): 300 recorded observations of a 36k-entry project tree, then
the live read a mounted 3D module makes every 2.5 s, repeated 10 times."""
import resource, sys, time
from pathlib import Path
from harness.visualization import VisualizationHistory, directory_tree

path = Path(sys.argv[1])
if not path.exists():
    history = VisualizationHistory(path)
    tree = directory_tree(Path("/private/tmp/m3exf-work/base"))
    for index in range(300):
        history.append({"agents": [{"id": "a", "location": "/x", "cost_usd": index, "state": "running"}],
                        "projects": [tree], "palace": None, "curation": None, "errors": []},
                       f"2026-09-28T00:{index // 60:02d}:{index % 60:02d}+00:00")
history = VisualizationHistory(path)
times = []
for _ in range(10):
    started = time.monotonic()
    result = history.read()
    times.append(time.monotonic() - started)
print(f"rows={len(result['timeline'])} first={times[0]:.2f}s later_avg={sum(times[1:])/9:.3f}s peak_rss={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1e6:.0f} MB")
