# Opus

This folder reserves the user-facing label only. No provider/API model ID or
one-call provider adapter has been verified. `--model-profile opus` fails before
native benchmark launch. Its configuration deliberately has null provider and
model identities; no anonymous historical run is attributed to this label.

The scaffold separates profile, configuration, prompt and policy factory so a
verified integration can be implemented and reviewed explicitly. Future
results belong in `results/<benchmark>/<new-run>/`.
