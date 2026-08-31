#!/usr/bin/env python3
"""Fire one verification prompt over the released owner WebSocket contract.

This narrow fallback exists because the live Stage composer can currently
invalidate its own ready snapshot while dispatching an attuned prompt.  It
does not bypass the daemon, gate, journal, provider, or spend ledger.
"""

from __future__ import annotations

import argparse
import asyncio
import json

import websockets

from harness.envelope import EnvelopeFactory


async def fire(*, url: str, thread_id: str, prompt: str) -> None:
    factory = EnvelopeFactory(machine_id="m3b3-owner-wire", agent_id="m3b3-owner")
    envelope = factory.create("prompt.submit", {"prompt": prompt}, thread_id=thread_id)
    # A continued thread can have a snapshot larger than the library's 1 MiB
    # default after a tool-heavy first run. The daemon remains the authority;
    # this only allows the verification client to receive that snapshot.
    async with websockets.connect(url, max_size=None) as socket:
        await socket.send(envelope.model_dump_json())
        print(json.dumps({"sent": envelope.model_dump(mode="json")}, sort_keys=True))
        while True:
            received = json.loads(await socket.recv())
            print(json.dumps(received, sort_keys=True))
            if received.get("type") in {"gate.open", "run.done", "error"}:
                return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://127.0.0.1:8783/ws")
    parser.add_argument("--thread-id", required=True)
    parser.add_argument("--prompt", required=True)
    args = parser.parse_args()
    asyncio.run(fire(url=args.url, thread_id=args.thread_id, prompt=args.prompt))


if __name__ == "__main__":
    main()
