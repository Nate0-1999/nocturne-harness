"""M3EX-16 diagnosis: run the real /remember path against OpenRouter with a fake Palace (no
writes) and print the splitter's draft and whether the (base or fixed) validator accepts it."""
import asyncio, json, os, sys
sys.path.insert(0, "tests")
from test_agent import FakeSpine, context, settings, memory_unit, split_response
from harness import agent as agent_module
from harness.agent import HarnessAgent
from harness.spine_client import CreatedMemoryResponse

SOURCE = ("Web UI tests live in harness/web/tests and run with npm test; "
          "Python tests run with .venv/bin/python -m pytest -q.")
drafts = []
original = agent_module._validated_remember_split
def spy(draft, **kwargs):
    result = original(draft, **kwargs)
    drafts.append({"draft": draft.model_dump(mode="json"), "accepted": result is not None})
    return result
agent_module._validated_remember_split = spy

async def main():
    spine = FakeSpine(CreatedMemoryResponse(created=memory_unit()), split_outcome=split_response(SOURCE))
    agent = HarnessAgent(settings(openrouter_api_key=os.environ["OPENROUTER_API_KEY"]))
    for attempt in range(int(sys.argv[1])):
        drafts.clear()
        import time
        started = time.monotonic()
        result = await agent.remember(SOURCE, context=context(spine))
        elapsed = round(time.monotonic() - started, 1)
        print(json.dumps({"attempt": attempt + 1, "ok": result.ok, "message": result.message[:120], "seconds": elapsed,
                          "drafts": drafts}, indent=1))

asyncio.run(main())
