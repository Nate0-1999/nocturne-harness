# M3OM one conversation module verification

This evidence came from the production owner app served by `create_dev_app` at
`http://127.0.0.1:8798/` with a disposable local home and identity. No regression
fixture or scenario app was used. The Palace endpoint was deliberately unavailable:
M3OM changes local Stage identity, persistence, rendering posture, and attunement, not
provider or Palace behavior.

The real browser began with one `Conversation` instance in Focused mode. Its shared
Stage chrome switched that same instance to Stack, where the existing `The Deck`
surface appeared. The neighboring Context Bars badge changed from the exact focused
thread to `The Deck`. A reload retained Stack. Switching the instance back to Focused
restored the traditional thread and the neighbor immediately re-attuned to that thread.
There was exactly one iframe whose URL identified `rack_module=conversation`; only its
`conversation_mode` query changed. Browser console warnings and errors remained zero.

The v4 Chat/Deck to v5 Conversation migration is pinned by the Stage layout unit test,
including two distinct migrated instances, preserved geometry, preserved scopes, and
focused/stack posture. The existing Deck behavior test continues to pin editable
proposed replies, same-turn ordering, Enter-to-advance, queue scrolling, and journaled
owner interventions.

`focused-mode.png` and `stack-mode.png` are 1280 by 720 captures from this run.
`trace-summary.json` records the exact observed state, and `SHA256SUMS` binds the images.
