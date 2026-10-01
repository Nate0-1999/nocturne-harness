"""M3HW final soak: the daemon in-process; SIGUSR1 appends pymalloc arena stats and the largest
object-type counts to argv[2]. Nothing is traced until the signal, so soak numbers stay clean."""
import collections
import gc
import os
import signal
import sys
import time

from harness.onboarding import load_config

os.environ.update(load_config().process_environment())
import uvicorn  # noqa: E402


def dump(*_):
    with open(sys.argv[2], "a") as out:
        counts = collections.Counter(type(item).__name__ for item in gc.get_objects())
        out.write(f"\n=== {time.strftime('%H:%M:%S')} gc objects {sum(counts.values())}\n")
        out.write(" ".join(f"{name}={count}" for name, count in counts.most_common(25)) + "\n")
        out.flush()
        saved = os.dup(2)
        os.dup2(out.fileno(), 2)
        try:
            sys._debugmallocstats()
        finally:
            os.dup2(saved, 2)
            os.close(saved)


signal.signal(signal.SIGUSR1, dump)
uvicorn.run("harness.packaged:create_app", factory=True, host="127.0.0.1", port=int(sys.argv[1]))
