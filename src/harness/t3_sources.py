"""Project T3's private provider inventory into the conversation source contract (A-095)."""

import hashlib
import re
from datetime import UTC, datetime

from harness.t3_client import T3Error

TOOLS = {
    "codex": ("Codex", {"chatgpt"}),
    "claudeAgent": ("Claude Code", {"max", "pro", "team", "enterprise"}),
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
            or auth.get("type") not in plans
            or auth.get("endpoint")
            or auth.get("action")
            or auth.get("subscriptionSharing")
            or limits.get("unavailable")
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
