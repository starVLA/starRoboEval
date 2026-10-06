# RoboCasa Tabletop: GPT6Astra agent-method samples

## 2026-10-04: preserved resource error and authorized model sample

The authorized resource-corrected sample completed with native failure:
**0 successes / 1 selected case**, 0 errors, 199 policy calls, 198 executed action
decisions and 990 controls. The final call requested `give_up` and executed no
action. No action was rejected.

The original launch remains a separate infrastructure-error record. A concurrent
runtime occupied the selected GPU, so the existing idle-GPU guard rejected
initialization before the native constructor or any model/control call. The user
explicitly authorized one new run after resolving that resource conflict. The
original error was not erased or automatically retried.

| Preserved attempt | Outcome | Policy calls | Executed decisions | Controls |
| --- | --- | ---: | ---: | ---: |
| Original launch | Infrastructure error; success unknown | 0 | 0 | 0 |
| Authorized resource-corrected sample | Native failure; `policy:give_up` | 199 | 198 | 990 |

These are two attempts at one selected task/reset, only one of which reached
model-controlled execution. They are not a two-case benchmark score.

### Conditions and interpretation

- Task: `PnPCupToDrawerClose`, native task 0; seed `20260907`.
- Protocol: `gr1-tabletop-pilot-0-19/rgb256-qpos29/control-1000/v2`.
  This is an independent 1000-control **development** track, not native-full
  evaluation. The native engine also has horizon 1000 with `ignore_done=True`;
  that engine setting alone does not establish a full native evaluation protocol.
- The service has no decision-count or replan limit in this track. This method's
  trusted driver chose a 200-call cap and chunk/replan setting 5, permitting
  shorter chunks. The recorded 198 action decisions each executed five controls;
  the additional stop-only call executed none.
- Observation: one native 256×256 cropped/padded RGB view, task language and
  29 measured joint encoders in radians. No object truth or scorer feedback.
- Action: 29 absolute joint-position targets in radians at 20 Hz, including
  both arms, hands and waist; not Cartesian or normalized pose commands.
- Method: `codex-native/v1`, requested `gpt-6-astra` with `xhigh` reasoning.
  Runtime/model source was frozen at `63b30885bdb82706dc572ec981cd4430dd1e23af`.

All 990 acknowledged native controls reported false success. The final public
stop note reports an unconfirmed cup grasp and open drawer; that is the policy's
explanation, not an independently established failure cause. Native success alone
determines task outcome.

The requested model/backend identity is not independently attested. The 199
recorded wrapper invocations are not a provider-request count: provider-internal
requests/retries and cost remain unknown. Available tokens/latency are
CLI-reported aggregate usage; component attribution is unknown.

### Reports and optional video

- [Result index, including both attempts](index.json).
- [Authorized sample JSON](reports/2026-10-04-PnPCupToDrawerClose-cup-in-drawer-resource-fix-authorized-once-independent-audit/result.json) and
  [HTML](reports/2026-10-04-PnPCupToDrawerClose-cup-in-drawer-resource-fix-authorized-once-independent-audit/index.html).
- [Original resource-error JSON](reports/2026-10-04-PnPCupToDrawerClose-cup-in-drawer-post-convergence-once/result.json) and
  [HTML](reports/2026-10-04-PnPCupToDrawerClose-cup-in-drawer-post-convergence-once/index.html).
- [Raw-export egoview video](raw/2026-10-04-PnPCupToDrawerClose-cup-in-drawer-resource-fix-authorized-once/client/episodes/tabletop-task00-seed20260907-attempt1/artifacts/sim_server_files/ego_view_bg_crop_pad_res256_freq20.mp4).
- [Central video gallery](../media/2026-10-04-service-validation/index.html).

The video fully decodes to 991 RGB frames at 256×256 and 20 Hz: one initial
frame plus 990 post-control frames. Initial, middle and final source frames were
visually inspected for rendering. Native session closure, exported records and
owned-process cleanup were checked. These checks establish record/media
consistency, not independent native execution or provider attestation.

Raw records, videos and the central gallery are Git-ignored viewing evidence,
not bundled in this source checkout. The original resource-error run produced
no task video. Readiness diagnostics are not scored model cases.

See the [benchmark protocol](../../../../examples/simBenchmarks/Robocasa_tabletop/EVALUATION_PROTOCOL.md)
and [result organization](../README.md).
