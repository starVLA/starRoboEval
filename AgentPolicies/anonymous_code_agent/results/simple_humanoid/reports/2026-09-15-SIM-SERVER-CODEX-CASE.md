# SIMPLE: one Codex-controlled SIM-server case

One selected `G1WholebodyOpenFaucetTeleop-v0` attempt finished with native
success **false**: 30 policy calls, 29 executed action decisions and 145 control
ticks. The last call voluntarily stopped after repeated contact attempts without
clear observed actuation; it executed no action. No first native success was
recorded. Native scoring, not the policy's explanation or video appearance,
determines the result. The attempt was not retried.

## Conditions and limits

- Source: `c2a54f323ebb2b7bafacd6dab8ca27dc7208a52d`.
- Independent SIM service and evaluator, `starvla-rsi.sim-server/v1`.
  Policy access was restricted to its declared observation mailbox.
- Pilot scope, domain-randomization level 0, seed 20260907, one episode.
  This historically scoring task was selected for integration validation,
  not as a representative sample or a rerun of the previous policy.
- Decision track: 200-call maximum, up to 5 controls per response, 1000-control
  cap. The reference native horizon remains 1000; control frequency is 50 Hz.
- Public head-camera RGB and 31 measured joint encoders; direct 36-dimensional
  physical joint/navigation actions. The fixed SONIC controller is native
  low-level actuation, not an added task-solving model.
- Fresh Codex context, no configured model API and no task-solving fallback.
  Provider/model snapshot and token/cost accounting remain unknown, so this
  is not a verified GPT6Astra score. Ordinary give-up minimum was 0; persistence
  is model-owned, not a benchmark requirement.

Both evaluator and server exited 0 with no recorded native/cleanup errors.
The generic closed-record audit passed. This establishes recorded integration
behavior, not full native parity, trusted provider accounting or a benchmark-wide
capability score. Do not merge this single case with historical coverage totals.

Independent closed inspection matched all 2,762 exported files against native
originals and downloaded copies (1,916,634,592 bytes), and all 30 public camera
observations against their native PNGs pixel-for-pixel. Both videos decode 146
frames. Spot checks at controls 0, 75 and 145 show upright, visibly changing
robot motion; they do not replace scoring or prove every frame is correct.

The run exposed avoidable transfer overhead: 2,601 files / 1,863,982,185 bytes
were native `cache/` data, mostly Omniverse texture cache (about 97.3% of export
bytes). Preserve this run's original exports and receipt; any later exclusion
change applies only to future services, not retroactively to this result.

## Records and media

The [hash-bound index](../indices/2026-09-15-G1WholebodyOpenFaucetTeleop-v0-open-water-faucet-sim-server-v1/index.json)
retains the result, first-success fields and two exact-byte video copies with
camera identity. The [original run](../raw/2026-09-15-G1WholebodyOpenFaucetTeleop-v0-open-water-faucet-sim-server-v1/)
retains public observations, controls, native receipts and source captures.
Raw records/media are Git-ignored; this report and lightweight index are trackable.
