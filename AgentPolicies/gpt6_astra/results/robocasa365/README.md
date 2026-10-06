# RoboCasa365: GPT6Astra agent-method sample

## 2026-10-04: one closed kitchen-navigation sample

The preselected `NavigateKitchen` sample completed with native failure:
**0 successes / 1 selected case**, 0 errors, 90 policy calls, 90 executed action
decisions and 450 controls. It stopped at the 450-control task horizon with
`environment:truncated`; no action was rejected and there was no automatic retry.

- Protocol: `target-first2-development/rgb/native-horizons/egl-owner-material-clamp-v1/v3`;
  pilot task 1, seed `20260907`, control budget 450.
- Method: `codex-native/v1`, requested `gpt-6-astra` with `xhigh` reasoning;
  method-owned policy-call cap 450 and chunk/replan setting 5, not universal
  server limits.
- Native sources: RoboCasa 1.0.1 at `b4684e6ee37d377cc392e98302a6b916d588b415`,
  Robosuite 1.5.2 at `85abee228d1c43ab1939bce33028099945d453b4`, MuJoCo 3.3.1.
- Observations: native language and left/right agent-view plus eye-in-hand RGB;
  no robot state or privileged object/reset information.

The selected `egl-owner-material-clamp-v1` rendering track applies the declared
EGL ownership repair and a temporary expanded-scene material shininess clamp.
**Pixels may change: this is not native-pixel parity or an official leaderboard
result.** The used-scene asset closure was verified; that is not verification of
the entire benchmark's asset universe. One explicit seeded reset is recorded;
upstream constructor initialization is separate, not falsely counted as absent.

The CLI model/provider identity is requested, not independently attested.
Provider-internal requests/retries and cost are unknown; available token counts
are CLI-reported. This is one selected sample, not a benchmark-wide success rate,
full 365-task evaluation or native score parity. Readiness diagnostics are
infrastructure evidence and are not included as scored model cases.

## Reports and optional videos

- [JSON result](reports/2026-10-04-NavigateKitchen-kitchen-navigation-post-convergence-once/result.json),
  [HTML result](reports/2026-10-04-NavigateKitchen-kitchen-navigation-post-convergence-once/index.html),
  and [result index](index.json).
- Raw-export videos: [left agent view](raw/2026-10-04-NavigateKitchen-kitchen-navigation-post-convergence-once/client/episodes/robocasa365-task01-attempt01/artifacts/sim_server_files/robot0_agentview_left.mp4),
  [right agent view](raw/2026-10-04-NavigateKitchen-kitchen-navigation-post-convergence-once/client/episodes/robocasa365-task01-attempt01/artifacts/sim_server_files/robot0_agentview_right.mp4),
  and [eye-in-hand](raw/2026-10-04-NavigateKitchen-kitchen-navigation-post-convergence-once/client/episodes/robocasa365-task01-attempt01/artifacts/sim_server_files/robot0_eye_in_hand.mp4).

Videos are optional Git-ignored artifacts, not bundled in this source checkout.
Each contains 451 frames: the initial observation plus 450 post-control frames.
Decoding or appearance is not a substitute for native success. Private audits
and raw records remain separate from the public result requirements.

See the [benchmark protocol](../../../../examples/simBenchmarks/Robocasa_365/EVALUATION_PROTOCOL.md)
and [result organization](../README.md).
