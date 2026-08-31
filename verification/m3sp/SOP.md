# M3SP real owner-path reproduction

1. Start current Spine and Harness builds against a disposable pgvector
   database, with a unique `PRINCIPAL_ID`, `MACHINE_ID`, `AGENT_ID`, and
   `NOCTURNE_HOME`.
2. Configure `CHAT_MODEL=openrouter:openai/gpt-5.4` and make one owner turn with
   reasoning effort set to `high`. Review and continue the ordinary memory
   gate.
3. Make a short second owner turn, then perform one real `/remember` and one
   seed/search flow so the ledger contains conversation and non-conversation
   embedding receipts.
4. Read `/v1/rack/query?resource=spend_table&as_of=now`. Confirm the response is
   `live`, all decimals are fixed-point strings, the first conversation has
   non-zero reasoning tokens, and `purposes` contains `Embeddings`.
5. On the Stage, expand the first GLOBAL conversation, add another Spend from
   the Library, choose `Nearest source`, and place it beside the active channel.
   Confirm its chrome names the active conversation and its table excludes the
   other conversation and GLOBAL purpose rows.
6. Capture `global-attuned-live.png`, write `live-proof.json`, and regenerate
   `SHA256SUMS`.

Stop and discard the local processes, database container, transcript home, and
workspace after capture.
