# M3RC — executable rules and the two CI failures

Run the Rules workflow on a disposable branch of the committed candidate.
For the first probe, remove the adjacent citation from the extraction-keyword
Field in `src/harness/agent.py`. GitHub run 34793889854, commit 9881039,
passes freeze and product rules, then fails the guard step with:
`src/harness/agent.py:138: guard lacks adjacent WALL/incident citation`.

For the second probe, start again from ec26dd5 and change axiom 0 in
`CLAUDE.md`. Run 34793890102, commit 3b24db2, fails the freeze step with:
`CLAUDE.md: frozen axioms differ from the master fingerprint`.
The screenshots are unmodified captures of those real GitHub job pages.
The signed-out browser shows step results; the CLI logs record exact errors.
The corrected candidate fe7d9e9 passes Rules in run 34794016917.

Full product suites ran in committed temporary worktrees with disposable
Postgres containers. Harness deselected only the three named remote contracts
in `tests/contract/test_spine_contract.py`: live create, live patch and live spend.
No Palace/provider credentials or owner Nocturne home were used. The standing
canon ran headlessly with isolated fixture homes and includes the packaged
heartbeat. It is ground proof, not the 49 additional feature-ledger walks.

`rules-checks.json` gives the result for each proposed mechanical row. Nine
unbuilt checks are explicit skips, not passes; their bodies fail if enabled
without replacement acceptance proof. The pending master citations and owner
coverage decision are documented in the private handoff, report 202, F078/F079.
No master-law change or feature-coverage approval is claimed.
