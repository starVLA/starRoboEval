# Results

This is the public result namespace for the GPT6Astra agent-method profile.
Report each benchmark and protocol separately; a requested model name is not
backend identity attestation, and a single sample is not a benchmark-wide score.
Each benchmark uses the same small layout:

```text
<benchmark>/
  README.md                 human-readable scope and result links
  index.json                optional machine-readable list of closed runs
  reports/<run-id>/
    result.json             method, protocol, budget, episodes and outcomes
    index.html              rendered basic result (when exported)
  media/<run-id>/...        generated videos; local/release artifact, not Git data
  raw/<run-id>/...          immutable evaluator evidence before local archival
```

The current basic exporter writes `result.json` and `index.html` from closed
records. It requires consistent outcomes, denominators, counters, method and
protocol declarations—not interaction logs, videos, source snapshots or an
internal audit certificate. Interaction/media recording is optional and enabled
by default. Missing usage or provider attribution stays unknown.

Historical reports may also contain separate `episodes.json`, `media.json` and
audit files; retain their original formats. New reports may link optional
interaction histories and videos without making them publication requirements.
Videos may remain under `raw/<run-id>/client/episodes/...` or be exported to
`media/`; both generated locations are Git-ignored. Include their actual location
when sharing a result. Raw records can be relocated to Git-ignored `barks/` only
with a preserved copy and relocation index.
Review method configuration and optional histories for private information before
sharing; use shareable artifact or relative links instead of machine-local paths.

Hashes and detailed source audits support internal integrity checks; they are
not the public purpose of a result. Declare native environment/source versions,
asset provenance and relevant runtime differences when reporting comparability.
Framework-path validation, native task success and score parity are distinct.

Never rewrite a published failure, convert an infrastructure error into a model
failure, rename an anonymous run as a named model, or combine runs with different
protocols. A new evaluation creates a new run ID and a new report.

## Service validation: 2026-10-04 cohort

Snapshot: 2026-10-04, after the seven primary client records closed. This
development cohort starts from the `3857d6c` convergence baseline, with separately
frozen, reviewed integration
fixes. It checks one preselected model sample per service, not complete benchmark
coverage or a cross-benchmark leaderboard. RoboDojo's selected sample reached
native success; the other six samples ended without success. The separately
declared planned-method Dojo experiment has also closed and is reported below,
outside this seven-sample cohort.

Calls, executed action decisions and acknowledged controls are separate counts.
The control cap is the predeclared sample budget, not a claim that all protocols
use that engine horizon. Read each linked report for the exact protocol, native
runtime, rendering track, seed, method and inference accounting.

| Service / selected task | Calls / decisions / controls | Declared control cap | Outcome and evidence |
| --- | ---: | ---: | --- |
| RoboDojo / `classify_objects`, layout 0 | 154 / 152 / 758 | 1100 | [Native success; 100/100 on this selected case](robodojo/README.md#2026-10-04-cohort-one-closed-layout-0-development-sample) |
| SimplerEnv / `google_robot_pick_horizontal_coke_can` | 76 / 76 / 80 | 80 | [Native failure at cap](simpler_env/README.md) |
| LIBERO / spatial task 0, black bowl on plate | 54 / 53 / 215 | 220 | [Voluntary give-up; native failure](libero/README.md) |
| RoboCasa365 / `NavigateKitchen` | 90 / 90 / 450 | 450 | [Native failure at cap](robocasa365/README.md) |
| RoboTwin / `lift_pot` | 1 / 0 / 0 | 400 | [Voluntary give-up before any model-issued action](robotwin/README.md) |
| RoboCasa Tabletop / `PnPCupToDrawerClose` | 199 / 198 / 990 | 1000 | [Authorized resource-corrected run; native failure](robocasa_tabletop/README.md) |
| VLA-Arena / Level-0 fork on cabinet | 61 / 61 / 300 | 300 | [Native failure at declared development cap](vla_arena/README.md) |

Important limits:

- The seven primary model samples have no terminal engineering errors. Tabletop's
  earlier GPU-conflict launch is a separate retained error, with zero model
  calls and controls; its new run was explicitly user-authorized.
  Dojo's earlier reset/material diagnostic error is also retained and is not a
  scored model sample. Failed cases are not automatically retried or replaced.
- RoboTwin completed observation delivery and model invocation, but the model
  stopped without an action. This is a retained policy failure, **not** evidence
  of model-controlled motion. Its three one-frame videos are initial views.
  The [follow-up diagnosis](robotwin/README.md#follow-up-immediate-stop-diagnosis)
  identified missing proprioception in the old RGB-only track. The separately
  versioned state14 interface repair at `5c46000` passed offline checks; a new
  authorized native/model run is still needed. It does not change the old result.
- RoboCasa365 uses the disclosed `egl-owner-material-clamp-v1` rendering track;
  official native pixel parity is not claimed. VLA-Arena's 300-control cap follows
  its pinned Level-0 evaluator rollout, not its underlying 1000-control engine
  horizon; its ten settling controls are separate. Tabletop's 1000-control track
  remains development scope.
- Dojo serves the complete five-layout fast schedule; this declared development
  client selects only layout 0. It is not the five-layout panel success rate.
  The separately authorized `codex-planned/v1` policy-development sample on the
  same public interface does not replace the Direct result.
- The samples use benchmark servers and declared robot inputs. Requested
  `gpt-6-astra` identity is not provider attestation; counted policy calls are
  not known provider-request counts. Diagnostic controls and offline regressions
  are never added to model capability results.

The optional [central video gallery](media/2026-10-04-service-validation/index.html)
contains the seven primary samples plus the separate Planned experiment below:
eight closed samples and 18 original video files in total. It is
Git-ignored local/release media, absent from a source-only checkout. Open a
benchmark's report above for its retained result even without that gallery.

### Separate experiment: 2026-10-05 Planned v1 on RoboDojo

The [closed layout-0 experiment](robodojo/README.md#2026-10-05-separate-planned-v1-layout-0-experiment)
recorded **237 calls / 236 executed decisions / 1053 controls**, native benchmark
and process scores **40/100**, and `success=false`. The model chose
`policy:safety_stop` with 47 of 1100 controls unused; there were no rejected
actions or terminal errors. This is an additional development experiment, not
an eighth primary cohort case or a five-layout panel result. No automatic retry
occurred.

The comparison with Direct v2 changes feedback exposure, method-side action
sequencing and guards, stopping choices, prompt and planning/memory together;
the service's native action semantics are unchanged.
This single case therefore does not isolate the effect of planning or establish
overall method/model regression. Client/native results and three videos have
been audited; the complete remote copy and outer operator cleanup are verified.
The gallery includes all three Planned videos separately from the seven primary
samples above. Original records and earlier results remain unchanged.
