"""M3EX-37: a journal shaped like the walk's — one Symphony thread with 210 ~480 KB
snapshot rows (~100 MB) and 20 small threads — written through the journal API."""
import sys, uuid
from pathlib import Path
from harness.transcript import TranscriptJournal

root = Path(sys.argv[1])
journal = TranscriptJournal(root / "transcripts")
project = str(Path(sys.argv[2]).resolve())

def thread(n_snapshots, snapshot_bytes):
    thread_id = str(uuid.uuid4())
    journal.append_thread_context(thread_id, project, workspace_root=project, current_location=project)
    prompt_id = "01" + uuid.uuid4().hex[:24].upper()
    journal.append_message(thread_id, {"message_id": prompt_id, "run_id": prompt_id, "role": "user",
                                       "content": "Take this to a Symphony.", "state": "complete"}, parent_id=None)
    filler = "x" * snapshot_bytes
    for index in range(n_snapshots):
        journal._append(thread_id, {"version": 1, "record_type": "event", "event": {
            "type": "thread.snapshot", "thread_id": thread_id,
            "payload": {"messages": [{"role": "assistant", "content": filler, "index": index}]}}})
    return thread_id

thread(210, 480_000)
for _ in range(20):
    thread(5, 2_000)
print(sum(p.stat().st_size for p in (root / "transcripts").iterdir()) // 1_000_000, "MB")
