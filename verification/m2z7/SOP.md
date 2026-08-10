# M2Z7 experiential verification

This SOP proves A-052 through the real owner app and real OpenRouter routes. It
does not use H5, a scenario response, a fake model, or owner identity. The
checked-in witness is synthetic and contains no credential or durable owner
fact.

## Isolated launch

From `harness/`, create a mode-0700 temporary home and launch the current
factory on a confirmed-free port with the production remote configuration but
verification provenance:

```sh
env NOCTURNE_HOME=<private-temp-home> \
  PRINCIPAL_ID=m2z7-sop-verification \
  MACHINE_ID=m2z7-sop-verification \
  AGENT_ID=m2z7-sop-verification \
  RUN_REQUEST_LIMIT=2 \
  RUN_TOTAL_TOKENS_LIMIT=25000 \
  PYTHONPATH=src \
  uv run --locked uvicorn harness.daemon:create_dev_app --factory \
  --host 127.0.0.1 --port 8799
```

The recorded run used disposable home `/private/tmp/nocturne-m2z7.7ICyAw` and
served only `127.0.0.1:8799`. The exact process was stopped with Ctrl-C before
each restart and at cleanup; no broad process command was used.

## Positive owner path

1. Open the current SPA. In a fresh thread, send
   `/model openrouter:google/gemini-2.5-flash-lite`. Verify the command returns
   a 1,048,576-token window with zero provider usage.
2. In Model Device set thread-local Max tokens to 64. This bounds the proof; it
   does not weaken or spoof the route's catalog context.
3. Put `visual-witness.jpg` on the browser clipboard, focus only the chat
   composer, and paste. Verify one preview named `clipboard.jpeg`, media/size
   `JPEG · 27 KiB`, and a Remove action. Paste again while it is pending and
   require the local remedy `Remove the current image before attaching
   another.` Remove, then paste the same image again.
4. Send exactly: `Read the attached screenshot. In one sentence, give the
   signal count and compass bearing. Do not call tools.` The prompt contains
   neither answer. The normal first-turn memory review must show zero injected
   and zero near-miss memories; continue once.
5. Require one real provider request and the visual answer. The recorded answer
   was `The signal count is 47 amber moths and the compass bearing is
   Northwest.` Usage was 2,134 input / 16 output tokens. Thread-current Vitals
   reported two broker receipts totaling `$0.000219800000` for
   `google/gemini-2.5-flash-lite`.
6. Stop and restart the exact daemon with the same home and identity. Reload the
   thread. Require the prompt, compact attached-image view, answer, and model to
   rehydrate. GET the displayed message image URL; require HTTP 200,
   `content-type: image/jpeg`, `cache-control: private, immutable`, length
   27,863, ETag equal to the source digest, and returned bytes equal to the
   checked-in JPEG.

## Refusal owner path

1. Create a second thread and send
   `/model openrouter:deepseek/deepseek-v4-flash-0731`. At the proof timestamp,
   the exact OpenRouter catalog row declared text input but not image input.
2. Paste the same witness, send `Read this screenshot.`, and require a normal
   completed refusal:

   `openrouter:deepseek/deepseek-v4-flash-0731 does not accept image input, so
   I did not send this image. Switch to an image-capable OpenRouter model in
   Model or with /model openrouter:provider/model, then resend it.`

3. Require `image_refusal(reason=unsupported)`, `end_turn`, `partial=false`,
   and `requests=0`, `input_tokens=0`, `output_tokens=0`. No gate opens. The
   final user revision must say `model_visible=false`; the capable turn says
   `model_visible=true`.
4. Restart the exact daemon again. Require the refused user image and refusal
   to rehydrate without a queued orphan or provider call.

## Projection, responsive, and journal checks

- Inspect the two private JSONL files before deletion. Each image prompt has
  exactly one `attachment` row containing base64. Every message revision,
  `run.started`, queue, and snapshot view carries only media type, byte count,
  and SHA-256. The browser/Rack snapshot tests additionally pin universal
  stripping of base64, local filenames, and optimistic preview URLs at the
  iframe boundary.
- At 390×844 require the chat document `clientWidth=390` and
  `scrollWidth=390`, readable refusal copy, visible attach control, and a
  `52.515625 × 44` CSS-pixel Remove target. Reset the viewport override after
  the check.
- Require the browser warning/error log to be empty.

## Cleanup and retained residue

The verification principal showed zero active memories and the accepted gate
selected zero memories, so no Palace memory cleanup was required. The positive
injection event and exact broker receipts are append-only verification evidence
under `m2z7-sop-verification`; they were not deleted. No owner identity,
activation, scorer control, deployment, backup, IAM, or cloud mutation was
touched.

After hashing the two mode-0600 journals into `trace-summary.json`, stop the
exact daemon, confirm port 8799 has no listener, finalize the browser tab, and
remove only the validated `/private/tmp/nocturne-m2z7.*` home. The retained
packet must pass:

```sh
jq -e . verification/m2z7/trace-summary.json
shasum -a 256 -c verification/m2z7/SHA256SUMS
pattern='sk-or-''v1-|Bear''er [A-Za-z0-9._~-]{16,}|OPENROUTER''_API_KEY\s*=|SPINE''_TOKEN\s*='
rg -n "$pattern" verification/m2z7
```

The final `rg` is expected to return no matches.
