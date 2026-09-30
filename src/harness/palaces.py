"""Named owner Palaces on the existing Cloud SQL foundation (SPEC D.2 166)."""

from __future__ import annotations

import asyncio
import json
import re
import secrets
import shutil
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import TextIO
from urllib.parse import urlsplit

import httpx

from harness.deploy import (
    CLOUD_RUN_SERVICE,
    DATABASE_URL_SECRET,
    EMBED_BASE_URL,
    EMBED_MODEL,
    OPENROUTER_SECRET,
    PROJECT_ID,
    REGION,
    RUNTIME_SERVICE_ACCOUNT_EMAIL,
    SPINE_TOKEN_SECRET,
    SQL_CONNECTION_NAME,
    SQL_INSTANCE,
    GcloudDeployBackend,
)
from harness.onboarding import (
    NocturneConfig,
    OnboardingError,
    _atomic_write_config,
    _write_config,
    load_config,
    nocturne_home,
)

_SERVICE_PREFIX = "nocturne-palace-"


def palace_home(home: Path, name: str) -> Path:
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,29}", name):
        raise OnboardingError("Use a Palace name of 1–30 lowercase letters, digits or hyphens.")
    return home if name == "main" else home / "palaces" / name


def palace_for_url(url: str) -> str | None:
    """The owner Palace a Cloud Run URL serves: main, a named Palace, or None when not ours."""

    host = urlsplit(url).hostname or ""
    if not host.endswith(".run.app"):
        return None
    label, zone = host.split(".", 1)
    # SERVICE-PROJECTNUMBER.REGION.run.app, or the older SERVICE-HASH-REGIONCODE.a.run.app.
    service = label.rsplit("-", 2 if zone == "a.run.app" else 1)[0]
    if service == CLOUD_RUN_SERVICE:
        return "main"
    name = service.removeprefix(_SERVICE_PREFIX)
    if name != service and re.fullmatch(r"[a-z][a-z0-9-]{0,29}", name):
        return name
    return None


class PalaceCloud(GcloudDeployBackend):
    """Reuse deploy's credential handling, SQL proxy and private secret transport."""

    def __init__(self, config: NocturneConfig):
        super().__init__(image_tag="palaces", openrouter_key=config.openrouter_api_key)

    def command(self, *args: str):
        return self._json_document(("gcloud", *args, f"--project={PROJECT_ID}", "--format=json"))

    def services(self) -> dict[str, dict]:
        rows = self._json_list(
            (
                "gcloud",
                "run",
                "services",
                "list",
                f"--project={PROJECT_ID}",
                f"--region={REGION}",
                "--format=json",
            )
        )
        result = {}
        for service in rows:
            metadata = service["metadata"]
            name = metadata.get("labels", {}).get("nocturne-palace")
            if metadata["name"] == CLOUD_RUN_SERVICE:
                name = "main"
            if name:
                result[name] = service
        return result

    @staticmethod
    def resource(name: str) -> str:
        palace_home(Path("."), name)
        if name == "main":
            raise OnboardingError("The main Palace cannot be dropped or replaced.")
        return f"{_SERVICE_PREFIX}{name}"

    def token(self, name: str) -> str:
        return self._access_secret(
            SPINE_TOKEN_SECRET if name == "main" else f"{self.resource(name)}-token"
        )

    def database_url(self, name: str, port: int) -> str:
        from sqlalchemy.engine import make_url

        # Reuse the owner's managed SQL login without rotating it. Each Palace
        # has a separate database; no tables or settings in main are changed.
        url = make_url(self._access_secret(DATABASE_URL_SECRET))
        return url.set(host="127.0.0.1", port=port, database=name, query={}).render_as_string(
            hide_password=False
        )

    def create(self, name: str, config: NocturneConfig, home: Path) -> dict:
        resource = self.resource(name)
        services = self.services()
        if name in services:
            raise OnboardingError(
                f"Palace {name} already exists. Use `nocturne palace use {name}`."
            )
        main = services.get("main")
        if main is None:
            raise OnboardingError("Deploy your main Palace before creating another Palace.")
        database = resource.replace("-", "_")
        token = secrets.token_urlsafe(32)
        record = {
            "name": name,
            "project": PROJECT_ID,
            "instance": SQL_INSTANCE,
            "database": database,
            "service": resource,
            "state": "creating",
        }
        home.mkdir(parents=True, exist_ok=True, mode=0o700)
        receipt = home / "custody.json"
        if receipt.exists():
            raise OnboardingError(f"Palace {name} has an unfinished custody record; drop it first.")
        self.command("sql", "databases", "create", database, f"--instance={SQL_INSTANCE}")
        _atomic_write_config(receipt, json.dumps(record) + "\n")

        def secret(suffix: str, value: str):
            self._create_secret(f"{resource}-{suffix}", value)
            self._add_secret_role(f"{resource}-{suffix}")

        with self._cloud_sql_proxy() as port:
            database_url = self.database_url(database, port)
            from spine.db.migrate import upgrade_head
            from sqlalchemy.engine import make_url

            cloud_url = (
                make_url(database_url)
                ._replace(host=None, port=None, query={"host": f"/cloudsql/{SQL_CONNECTION_NAME}"})
                .render_as_string(hide_password=False)
            )
            with ThreadPoolExecutor(max_workers=3) as pool:
                futures = [
                    pool.submit(secret, "token", token),
                    pool.submit(secret, "database", cloud_url),
                    pool.submit(upgrade_head, database_url),
                ]
                for future in futures:
                    future.result()

        image = main["spec"]["template"]["spec"]["containers"][0]["image"]
        principal = f"palace-agent-{uuid.uuid4()}"
        # Test Palaces are ordinary independent Palaces. Their own principal is
        # the owner there; main's verification identity/hygiene stays unchanged.
        service = self.command(
            "run",
            "deploy",
            resource,
            f"--region={REGION}",
            f"--image={image}",
            "--execution-environment=gen2",
            "--port=8000",
            "--min-instances=0",
            "--max-instances=1",
            f"--service-account={RUNTIME_SERVICE_ACCOUNT_EMAIL}",
            f"--add-cloudsql-instances={SQL_CONNECTION_NAME}",
            f"--set-secrets=SPINE_DATABASE_URL={resource}-database:latest,"
            f"SPINE_TOKEN={resource}-token:latest,SPINE_OPENAI_API_KEY={OPENROUTER_SECRET}:latest",
            f"--set-env-vars=SPINE_EMBED_BASE_URL={EMBED_BASE_URL},"
            f"SPINE_EMBED_MODEL={EMBED_MODEL},SPINE_OWNER_PRINCIPAL_ID={principal}",
            f"--labels=nocturne-palace={name}",
            "--allow-unauthenticated",
            "--no-invoker-iam-check",
            "--quiet",
        )
        url = service["status"]["url"]
        with httpx.Client(timeout=60) as client:
            response = client.get(f"{url}/health", headers={"Authorization": f"Bearer {token}"})
            if response.status_code != 200:
                raise OnboardingError(
                    f"Palace {name} was created but is not healthy (HTTP {response.status_code}). "
                    f"Its custody record is saved; use `nocturne palace drop {name}` to remove it."
                )
        _write_config(
            replace(
                config,
                home=home,
                palace_name=name,
                palace_mode="remote",
                spine_url=url,
                spine_token=token,
                principal_id=principal,
                machine_id=f"palace-agent-{uuid.uuid4()}",
                postgres_volume=None,
                transcript_backup=False,
            )
        )
        record.update(state="ready", url=url, principal_id=principal)
        _atomic_write_config(receipt, json.dumps(record) + "\n")
        return record

    def memory_count(self, record: dict) -> int:
        import asyncpg

        async def count(url: str) -> int:
            connection = await asyncpg.connect(url.replace("postgresql+asyncpg:", "postgresql:"))
            try:
                exists = await connection.fetchval("SELECT to_regclass('public.memory_unit')")
                return (
                    int(await connection.fetchval("SELECT count(*) FROM memory_unit"))
                    if exists
                    else 0
                )
            finally:
                await connection.close()

        with self._cloud_sql_proxy() as port:
            return asyncio.run(count(self.database_url(record["database"], port)))

    def drop(self, name: str, record: dict) -> None:
        resource = self.resource(name)
        if record["database"] != resource.replace("-", "_") or record["service"] != resource:
            raise OnboardingError("Palace custody record does not match its name.")
        if name in self.services():
            self.command("run", "services", "delete", resource, f"--region={REGION}", "--quiet")
        # Deleted Cloud Run revisions can retain pooled connections while draining.
        # Terminate only sessions on the explicitly named disposable database.
        import asyncpg

        async def disconnect(url: str):
            connection = await asyncpg.connect(url.replace("postgresql+asyncpg:", "postgresql:"))
            try:
                await connection.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = $1",
                    record["database"],
                )
            finally:
                await connection.close()

        with self._cloud_sql_proxy() as port:
            asyncio.run(disconnect(self.database_url("postgres", port)))
        self.command(
            "sql",
            "databases",
            "delete",
            record["database"],
            f"--instance={SQL_INSTANCE}",
            "--quiet",
        )
        existing = self._json_list(
            (
                "gcloud",
                "secrets",
                "list",
                f"--project={PROJECT_ID}",
                "--format=json",
            )
        )
        names = {row["name"].rsplit("/", 1)[-1] for row in existing}
        for suffix in ("token", "database"):
            if f"{resource}-{suffix}" in names:
                self.command("secrets", "delete", f"{resource}-{suffix}", "--quiet")


def palace_nocturne(
    action: str, name: str | None, *, stdout: TextIO = sys.stdout, prompt=input, cloud=None
) -> int:
    root = nocturne_home()
    config = load_config(home=root)
    cloud = cloud or PalaceCloud(config)
    if action == "list":
        for palace, service in sorted(cloud.services().items()):
            marker = "*" if palace == config.palace_name else " "
            print(f"{marker} {palace}  {service['status']['url']}", file=stdout)
        return 0
    assert name is not None
    home = palace_home(root, name)
    if action == "new":
        started = time.monotonic()
        cloud.create(name, config, home)
        print(
            f"Created Palace {name} in {time.monotonic() - started:.1f}s. "
            f"Run `nocturne palace use {name}`.",
            file=stdout,
        )
    elif action == "use":
        services = cloud.services()
        if name not in services:
            raise OnboardingError(f"No Palace named {name} exists in your project.")
        if not (home / "env").is_file():
            service = services[name]
            environment = service["spec"]["template"]["spec"]["containers"][0].get("env", [])
            principal = next(
                (
                    item["value"]
                    for item in environment
                    if item["name"] == "SPINE_OWNER_PRINCIPAL_ID"
                ),
                "local",
            )
            _write_config(
                replace(
                    config,
                    home=home,
                    palace_name=name,
                    palace_mode="remote",
                    spine_url=service["status"]["url"],
                    spine_token=cloud.token(name),
                    principal_id=principal,
                    machine_id=f"palace-agent-{uuid.uuid4()}",
                    postgres_volume=None,
                    transcript_backup=False,
                )
            )
            if name != "main":
                resource = cloud.resource(name)
                _atomic_write_config(
                    home / "custody.json",
                    json.dumps(
                        {
                            "name": name,
                            "project": PROJECT_ID,
                            "instance": SQL_INSTANCE,
                            "database": resource.replace("-", "_"),
                            "service": resource,
                            "state": "ready",
                            "url": service["status"]["url"],
                        }
                    )
                    + "\n",
                )
        _atomic_write_config(root / "palace-selection", name + "\n")
        print(f"Selected Palace {name}. Restart `nocturne up` to use it.", file=stdout)
    elif action == "drop":
        cloud.resource(name)  # Main is refused before reading or mutating anything.
        if config.palace_name == name:
            raise OnboardingError("Switch to another Palace before dropping this one.")
        receipt = home / "custody.json"
        if not receipt.is_file():
            raise OnboardingError(f"No custody record for {name}; no resources were removed.")
        record = json.loads(receipt.read_text())
        resource = cloud.resource(name)
        if record["database"] != resource.replace("-", "_") or record["service"] != resource:
            raise OnboardingError("Palace custody record does not match its name.")
        count = cloud.memory_count(record)
        try:
            answer = prompt(
                f"Drop Palace {name} and its {count} memories permanently? Type {name}: "
            )
        except EOFError:  # M3W5B-40: no terminal is no confirmation, not a traceback.
            answer = ""
        if answer.strip() != name:
            print("Palace kept.", file=stdout)
            return 0
        cloud.drop(name, record)
        shutil.rmtree(home)
        print(f"Dropped Palace {name} and its {count} memories.", file=stdout)
    return 0
