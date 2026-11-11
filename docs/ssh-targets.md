# Run workflows on stage and production

Use two Linux VPS hosts you can reach by SSH. Each runs the same Nocturne version as
your computer, with its own local Palace. Install Python 3.12 with venv support,
Docker Engine with Compose, Git, bubblewrap and libseccomp2 on each host. The SSH user
needs Docker access and systemd; for a non-root user, enable lingering so its user
service survives logout (`sudo loginctl enable-linger USER`). Keep the app and Palace
ports bound to localhost. Only SSH needs an inbound port.

```sh
nocturne target add stage user@stage-host
nocturne target add prod user@prod-host
nocturne target init stage
nocturne target init prod
```

Initialization installs your exact package pair from PyPI, runs the ordinary setup
on each host, starts `nocturne up --no-open` as a service and runs `doctor`. Enter
your OpenRouter API key at the host's setup prompt. If versions differ, update the
older installation; a newer target is never downgraded. SSH aliases and addresses
such as `ssh://user@host:2222` work with your usual SSH keys and known hosts.

Build and check your workflow locally. Put only key names in `keys.example`.
Set the tool keys in each host's vault by piping values through SSH, never by
putting them in a command argument or recipe. For example, in a shell with `read -s`:

```sh
read -rs -p 'Fixture API key: ' workflow_key; printf '\n'
printf '%s' "$workflow_key" | ssh user@stage-host \
  '~/.local/share/nocturne/venv/bin/nocturne vault set forecast FIXTURE_API_KEY'
printf '%s' "$workflow_key" | ssh user@prod-host \
  '~/.local/share/nocturne/venv/bin/nocturne vault set forecast FIXTURE_API_KEY'
unset workflow_key
nocturne workflow check ./forecast
nocturne workflow pack ./forecast
nocturne push ./forecast.tar --to stage
```

A push checks the local bundle and the target's version and named vault keys before
saving a disabled candidate. It runs that candidate once and waits for the recipe's
exit check. PASS enables the trigger; failure keeps the previous proven release
enabled. Inspect the candidate's conversation on the target to understand a failure.

```sh
nocturne promote forecast --to prod
nocturne targets
nocturne rollback forecast --on prod
```

Promotion copies the exact digest currently enabled and proven on the target named
`stage`, then proves it again on production. It does not repack your edited local
folder. Rollback re-enables the previous proven digest without another model run;
wait for any active run to finish before switching releases. Each host retains its
append-only release history at `$NOCTURNE_HOME/releases/log.jsonl` (default home:
`~/.nocturne`). The Jobs module shows local, stage and production digests and last
verdicts, with Push and Promote for the available actions. All remote work travels
through SSH to the host's own CLI.
