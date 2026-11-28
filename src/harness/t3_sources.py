"""Project T3's private provider inventory into the conversation source contract (A-095)."""

import asyncio
import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime

from harness.t3_client import T3Error

TOOLS = {
    "codex": ("Codex", {"chatgpt"}),
    "claudeAgent": (
        "Claude Code",
        {
            "pro",
            "team",
            "enterprise",
            "max",
            "maxplan",
            "max5",
            "max20",
            "claudeultra",
            "claudemaxsubscription",
            "claudemax5xsubscription",
            "claudemax20xsubscription",
            "claudeprosubscription",
            "claudeteamsubscription",
            "claudeenterprisesubscription",
        },
    ),
}
SLUG = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._/-]*")
VERSION = re.compile(r"[0-9][a-zA-Z0-9.+-]{0,64}")


def _instant(value):
    try:
        instant = datetime.fromisoformat(value)
        if instant.tzinfo:
            return instant.astimezone(UTC).isoformat()
    except (TypeError, ValueError):
        pass
    return None


def _thinking(model):
    for option in (model.get("capabilities") or {}).get("optionDescriptors", []):
        key = option.get("id")
        if key == "thinking" and option.get("type") == "boolean":
            return {"id": key, "levels": ["on", "off"]}
        if key in ("reasoningEffort", "effort") and option.get("type") == "select":
            levels = [
                choice["id"]
                for choice in option["options"]
                if re.fullmatch(r"[a-z0-9_-]+", choice["id"]) and choice["id"] != "default"
            ]
            if levels:
                return {"id": key, "levels": levels}
    return None


def project_sources(providers: list[dict]) -> list[dict]:
    observed = {p.get("instanceId"): p for p in providers}
    rows = []
    for instance, (label, plans) in TOOLS.items():
        provider = observed.get(instance, {})
        auth = provider.get("auth") or {}
        limits = provider.get("usageLimits") or {}
        native_id = auth.get("workspaceId") or auth.get("profileId")
        account = None
        if native_id and "@" not in native_id and auth.get("status") == "authenticated":
            account = hashlib.sha256(f"{instance}\0{native_id}".encode()).hexdigest()
        windows = [w for w in limits.get("windows", []) if w.get("usedPercent", 0) >= 100]
        global_limits = [w for w in windows if not w.get("modelIds")]
        if provider.get("installed") is False:
            status = "missing"
        elif auth.get("status") == "unauthenticated":
            status = "signed_out"
        elif (
            not account
            or provider.get("status") != "ready"
            or provider.get("modelsRetained")
            or provider.get("availability") == "unavailable"
            or re.sub(r"[\s_-]+", "", (auth.get("type") or "").lower()) not in plans
            or auth.get("endpoint")
            or auth.get("action")
            or auth.get("subscriptionSharing")
        ):
            status = "unknown"
        elif global_limits or limits.get("zeroSpendCap"):
            status = "limited"
        else:
            status = "available"
        models = []
        for model in provider.get("models", []):
            slug = model.get("slug", "")
            if not SLUG.fullmatch(slug) or model.get("isCustom"):
                continue
            limited = [w for w in windows if slug in w.get("modelIds", [])]
            model_state = "limited" if limited and status == "available" else status
            models.append(
                {
                    "id": slug,
                    "name": slug,
                    "thinking": _thinking(model),
                    "default": model.get("isDefault") is True,
                    "availability": model_state,
                    "limited_until": max(
                        filter(
                            None, (_instant(w.get("resetsAt")) for w in limited + global_limits)
                        ),
                        default=None,
                    ),
                    "context_tokens": None,
                }
            )
        version = provider.get("version") or ""
        rows.append(
            {
                "tool": instance,
                "name": label,
                "version": version if VERSION.fullmatch(version) else None,
                "account": account,
                "availability": status,
                "usage_known": bool(limits) and not limits.get("unavailable"),
                "models": models,
                "limited_until": max(
                    filter(None, (_instant(w.get("resetsAt")) for w in global_limits)), default=None
                ),
                "observed_at": _instant(provider.get("checkedAt")),
                "observed_via": "T3",
            }
        )
    return rows


async def sources(server):
    try:
        client = await server.client()
        config = await client.call("server.getConfig", {})
    except (TimeoutError, OSError):
        raise T3Error("The local T3 server is unavailable.") from None
    return project_sources(config["providers"])


def offers(rows):
    for source in rows:
        if source["availability"] == "available":
            for model in source["models"]:
                if model["availability"] == "available":
                    key = f"subscription:{source['tool']}/{source['account']}/{model['id']}"
                    yield key, source, model


async def resolve_offer(server, requested):
    for key, source, model in offers(await sources(server)):
        if requested in (key, f"subscription:{source['tool']}/{model['id']}"):
            return key, source, model
    raise T3Error("This tool, account and model are unavailable on the signed-in subscription.")


async def subscription_window(server, tool, slug) -> int:
    """Ask only for metadata, after the private server confirms the signed-in offer."""
    client = await server.client()
    binary = server._settings()["providerInstances"][tool]["config"]["binaryPath"]
    args = [binary]
    request = ""
    if tool == "codex":
        args += ["debug", "models"]
    else:
        args += [
            "-p",
            "--no-session-persistence",
            "--model",
            slug,
            "--tools",
            "",
            "--strict-mcp-config",
            "--mcp-config",
            '{"mcpServers":{}}',
            "--setting-sources",
            "",
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--verbose",
        ]
        request = (
            json.dumps(
                {
                    "type": "control_request",
                    "request_id": "window",
                    "request": {"subtype": "get_context_usage"},
                }
            )
            + "\n"
        )
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            args,
            input=request,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=20,
            cwd=client.native_env["TMPDIR"],
            env={
                **client.native_env,
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                "DISABLE_AUTOUPDATER": "1",
                "DISABLE_TELEMETRY": "1",
            },
        )
        if tool == "codex":
            window = next(
                (
                    m.get("context_window")
                    for m in json.loads(result.stdout)["models"]
                    if m.get("slug") == slug
                ),
                None,
            )
        else:
            window = None
            for line in result.stdout.splitlines():
                frame = json.loads(line)
                response = frame.get("response") or {}
                if (
                    frame.get("type") == "control_response"
                    and response.get("request_id") == "window"
                    and response.get("subtype") == "success"
                ):
                    usage = response["response"]
                    if usage.get("model") == slug:
                        window = usage.get("maxTokens")
                    break
        if type(window) is int and window > 0:
            return window
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError, KeyError, TypeError):
        pass
    raise T3Error("The tool did not report a context size for this model. Choose another model.")
