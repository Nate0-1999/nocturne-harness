"""M3MD single-key walk: the same packaged app in M3G's OFF mode, on port 8786 — one
OpenAI-compatible endpoint (OpenRouter's), one key, one model, and no OpenRouter key, after
M3G's proof shape. The key is the home's own; nothing secret is passed on the command line."""

import os
import sys

from harness.onboarding import load_config

environment = dict(load_config().process_environment())
environment.pop("MODEL_POLICY_CHAT", None)
environment.update(
    OPENAI_BASE_URL="https://openrouter.ai/api/v1",
    OPENAI_API_KEY=environment.pop("OPENROUTER_API_KEY"),
    CHAT_MODEL="openai:openai/gpt-4.1-mini",
)
os.execvpe(
    sys.executable,
    [sys.executable, "-m", "uvicorn", "harness.packaged:create_app", "--factory",
     "--host", "127.0.0.1", "--port", "8786"],
    environment,
)
