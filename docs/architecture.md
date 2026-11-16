# Architecture

The unit of evaluation is a complete **agent method**, including its model
composition, prompts, tools, memory and decision behavior. A fixed-prompt model
baseline is one method, not the only integration shape. Compare results within
declared benchmark/protocol conditions, with inference cost disclosed rather
than constrained by a new universal budget. See [method integration](agent-methods.md).

The SIM-server boundary prohibits oracle access; it does not impose an RGB-only
policy. A versioned benchmark interface may explicitly provide measured robot
joints, end-effector poses and other declared robot sensors. That permission
does not include object ground truth, private reset layouts, hidden task scores
or hypothetical simulator rollouts. Sensor/action track selection stays with
the benchmark; model prompts, memory and target selection stay with the agent.

The primary architecture has two control ends: an agent-owned evaluation driver
and a benchmark-owned SIM service. `benchkit` provides shared communication and
output/data libraries, not a third mandatory control process. These are responsibility boundaries, not an OS
sandbox. The trusted driver retains the administrative client; the model actor
receives only declared observations and execution counters. The benchmark
service alone owns native environments. See the [SIM service protocol](../benchmarks/simBenchmarks/SERVER_PROTOCOL.md).

Current source roots are `benchmarks/`, `AgentPolicies/` and `benchkit/`.

![starRoboEval architecture: agent methods, benchmark services and evaluation records](../assets/architecture.svg)

## One entrypoint, benchmark-specific capabilities

`rsi-bench list` shows the 14 implemented development service routes.
`rsi-bench serve --benchmark <id> ...` selects one and delegates to its existing
`server.main(argv)`. The source-checkout equivalent is
`python -m benchkit`. The selector is a launch convenience, not a
new decision loop, proxy or persistent coordinator. Generic list/help needs no
simulator; selected-service help shows that wrapper's real launch options.
`python -m benchkit.sim_server` serves only the synthetic smoke world.

RoboDojo, SimplerEnv, LIBERO and SIMPLE share communication mechanisms, not a
single action space. In particular, SIMPLE's humanoid contract is not EEF16.
The selected adapter owns sensors, action semantics, task panel and scoring.
VLN-CE provides an R2R RGB navigation service; hardware is not listed as an available service route. An implemented
route does not prove asset readiness or full native validation.

`EvaluationRunner` is not the server layer. The reusable runner is an optional
**agent-side** trusted driver in `benchkit/driver/runner.py`; benchmark services execute
given actions and return declared observations. Shared report tools sit beside
this control path.

## Ownership

| Layer | Owns | Must not own |
| --- | --- | --- |
| `AgentPolicies/<profile>/` | Policy factory, model configuration, prompts, decisions, trusted evaluation entrypoint and results | Native simulator handles or task/scoring definitions; oracle information in model requests |
| `benchmarks/simBenchmarks/<benchmark>/` | Native environment, task inventory, observation/action mapping, scoring and sample-selection plans | Model prompts, task-solving heuristics or model-specific persistence requirements |
| `benchkit/` | Service selection, shared transport, case leasing, records/reports and record-consistency audits | Native task semantics or model inference/robot decisions |

No real-robot backend is integrated; future hardware adapters need their own
safety, timing and scoring validation.

### Case sequencing stays outside agent decisions

The benchmark service declares its schedule; the trusted driver claims each case
and runs it. `benchkit/sim_server/remote_run.py` leases gateway cases and skips
cases that already have a per-case `completion.json`. It is not an additional
per-action intermediary between the agent and benchmark server. See the
[workflow choices](evaluation.md#choose-a-workflow).

Resource-aware multi-service scheduling and restart reconciliation are future
extensions. Keep benchmark schedules and permanent attempt claims authoritative;
never replay uncertain controls or silently retry failed cases. A new run ID
alone is not permission to repeat a task.

### Benchmark interface

`BenchmarkAdapter` declares compatible observation/action contracts and selects
episodes. `EpisodeSession` implements observation delivery, control execution,
native metrics, artifacts and cleanup. Only this side can access private native
state; the policy receives a whitelisted public observation.

Each implemented benchmark service provides a top-level `server.py` entrypoint
and groups service implementation and protocol under `bench_server/`: the adapter
and private worker client sit beside the `protocol/` subpackage, which contains
task definitions and public feedback schemas. Native runtime code stays under
`environment/`. Its catalog is benchmark protocol data, while deployment
paths and the selected named panel are server configuration. See the
[RoboDojo directory guide](../benchmarks/simBenchmarks/RoboDojo/README.md#directory-responsibilities).
Service adapters live in `bench_server/adapter.py`. Separate protocol packages exist where definitions
are needed, not as empty layers. Task catalogs are immutable protocol data,
not assets or deployment paths; no task-specific server copy is required.
Their actions remain benchmark-native. An agent driver must supply vectors in
the selected service's declared action space; compatibility with one robot does
not imply compatibility with another.
The shared
`benchkit/sim_server/` transport provides a remote `BenchmarkAdapter`, fixed
server schedules, single-attempt session claims, serialized control and bounded
hash-checked artifact transfer. It has no task-solving methods. Server credentials
and management/scoring methods are evaluator-private; policies retain exactly
the same observation-to-decision interface. Idle service time does not schedule
native control. Lost step acknowledgments never trigger automatic replay.

The supplied agentic policies have trusted entrypoints under `AgentPolicies/<profile>/`.
These entrypoints require `--sim-server` and use the reusable loop in
`benchkit/driver/runner.py`. This trusted driver is distinct from the model actor: the
administrative client includes schedules, metrics and result export, and must
not be passed to an untrusted policy process. The general CLI
(`rsi-bench run`) also connects only through `--sim-server`. The service records its deployment source snapshot; the
client records its git revision and dirty flag, without claiming loaded-memory,
asset or provider attestation.

Unit conversion, fixed joint order, protocol-defined interpolation and native
low-level control belong to the adapter. Object localization from images,
grasp planning, trajectory selection and model-specific IK belong to the policy.
VLA action proposals, hybrid controllers, fallback task policies and autonomous
task-skill services are outside this repository's direct-control scope. Native
low-level control and protocol-fixed conversions must not plan the task for
the model or silently expand its available observations.

Services declare their fixed schedule in the adapter or its protocol data.
RoboDojo's server reads the immutable schedule from
`bench_server/protocol/task_catalog.json`: `classify_objects` has `evaluation_mode`
selections of 1, 5 or 50 layouts; `max` takes the first 50 reset-stable layouts
from a reset-stability manifest. Each attempts every selected layout once; none
covers every RoboDojo task. Supported task and case selection remains benchmark-specific.

### Policy interface

The wire protocol is the integration boundary; no language, SDK or Python base
class is mandatory. The optional `Policy.act` interface receives one scheduled observation and returns one structured action
chunk or stop. It has no direct reset/step API. Model behavior, prompt construction
and optional voluntary-stop preferences are versioned under the selected profile.
One call may involve multiple declared general-purpose model components. Their
usage is separate from decision-call/control counters. The method and accounting
versions are explicit; old one-request records remain data.

The method owns action chunk length, how many controls to execute from a decision
(including repeated targets), and when to replan. The trusted agent driver sends
these as successive single-action `step` requests; the service has no decision
boundary or universal five-control prefix. Each request still obeys sequencing,
action validity, native control/termination and the declared total execution
budget. Repeating a target means another acknowledged control, never replaying
an uncertain request. Native physics substeps, timing and protocol-fixed
interpolation remain benchmark-owned, not method-adjustable repeats.

A service advertises its native execution horizon (`environment_step_cap`) and,
where the benchmark limits model calls, a call allowance. The driver may override
either; the manifest records the service value and whether it was overridden.
No service couples call or prefix settings to the execution cap. CALVIN and
DOMINO's current protocols no longer require prefix one. The reference agent
driver discards an unexecuted chunk suffix when an acknowledged observation
contains a changed instruction, then asks its policy again. This uses public
language, not hidden subtask state. Shared tooling enforces a
`required_replan_interval` when a service declares one; no current service does.

Input validity belongs to the declared benchmark interface; optional motion and
gripper preferences belong to the model profile. A declared `feedback` mode can
reject invalid input before execution and return a bounded, public validation
issue to the next normal policy call using the last acknowledged observation.
It neither advances the simulator nor supplies a fresh observation. Calls and
rejections are counted separately from executed decisions and controls, with a
finite call budget. A lost acknowledgment or uncertain native execution remains
an error, never an invitation to replay. See [action validation](../benchmarks/simBenchmarks/RoboDojo/ACTION_VALIDATION.md).

A persistence or give-up preference is optional policy behavior. It does not
change success, the native horizon or another model's behavior. The runner
supplies non-privileged execution counters; the policy applies its own
preference. Native termination, hard limits, errors and declared safety stops
can still end earlier.

Shared fixed-action fixtures live under
`benchkit/diagnostics/`: implementing the `Policy` interface does not make an
infrastructure diagnostic a participant model.

### Reusable execution and output tools

`benchkit/contracts.py` and `interfaces.py` define the public types.
`benchkit/diagnostics/registry.py` names the shared diagnostic policies for `--policy`; benchmarks
come only from their services.
`benchkit/driver/runner.py` validates compatibility and executes the agent's bounded
action prefixes for every model driver and the general CLI. It calls `Policy.act`
for decisions; the decisions themselves stay in each `AgentPolicies/<profile>/`. Native validation and end conditions remain
authoritative on the server. `benchkit/sim_server/` is the single shared transport
implementation, imported directly by both ends; there is no forwarding service
package under `benchmarks`. Import the optional runner from
`benchkit.driver.runner`; there is no forwarding module under `AgentPolicies`.
`benchkit/driver/model_profiles.py` reads self-describing `configs/profile.json` files, validates
their configuration and factories, and records the profile ID; it does not
implement a provider.

Shared serializable DTOs and profile factory dispatch helpers
remain under `benchkit` for existing integrations. They are grouped into functional
packages; relocated entrypoints do not retain forwarding shells. New model
drivers construct their own model; shared declarative validation remains an
output/provenance tool. Historical results keep their original paths and semantics.

Agent profiles own their configuration schema, model connection, prompts,
memory, image preprocessing and action-generation loop. Shared tools can read
their declarations without implementing the model. The supplied
[agentic policies](../AgentPolicies/README.md) use the service path;
each profile documents its commands and settings in its own README.

Model-call recovery, voluntary completion, optional motion guards and persistence
preferences are method behavior. None can award native success, extend the
benchmark's execution budget or replay a robot command after an uncertain
acknowledgement. A completion declaration ends the method, not the native scorer's
responsibility to report the actual outcome.

The shared wire protocol, benchmark robot interface and agent method are
independently versioned. Changing a model prompt does not change the robot's
sensors or action semantics; changing the robot interface does not imply a
particular model implementation. Record the conditions actually used for each
result rather than inferring them from a method or benchmark name.

A profile can declare `runtime_preflight: true` in its configuration schema.
Its optional `preflight_runtime()` capability checks dependencies and credentials
using the profile's readiness procedure, which may contact the provider.
It does not start a benchmark episode or generate robot actions.
`benchkit preflight-policy --model-profile <id>` dispatches this profile-owned
check; benchkit does not contain provider-specific readiness logic.

`benchkit/diagnostics/` contains explicitly non-capability fixed-action diagnostics.
Their recorded native metrics
validate infrastructure and must not be interpreted as model capability scores.
`benchkit probe` (`diagnostics/probe.py`) is the shared connect-level readiness
check for every service: describe, claim, reset and close, with no policy or action.
Native-only asset and renderer checks that need no service remain under that
benchmark's `environment/` directory.

Generic auditing and reporting live under `benchkit/audits/` and `reports/`.
Benchmark-specific evidence checks stay beside the benchmark. An audit validates
records, not native replay, model identity or process isolation.

## Execution and records

The reference workflow below is not a protocol-first participation or
basic-report admission requirement for an independent driver.

1. Resolve the service schedule and a compatible policy configuration.
2. Record the git revision, dirty flag, diff digest, model profile, effective
   configuration and preset/prompt digests in the run manifest.
3. Run any declared local runtime preflight, then claim a scheduled case; a
   rerun skips cases that already have a per-case `completion.json`.
4. Deliver an allowed observation, accept one policy decision and execute its
   bounded prefix. Repeat until native end, policy stop, error or a hard limit.
5. Close the environment and retain native outcome, errors, counters and available
   usage; retain interactions and media according to the selected recording options.
6. Show closed outcomes and optional interaction history under the selected method's
   results; run the closed-run record audit separately when needed.

One call is not necessarily one action decision, control or physics tick. Stop
responses consume a call but execute no action. An action decision counts after
at least one control executes. Adapter-specific physics substeps remain separate.

## Basic results and optional interaction history

[`reports/basic_result.py`](../benchkit/reports/basic_result.py) produces a compact
HTML/JSON result from the closed manifest, status, episode results and summary.
No events, videos, source snapshot or hash audit is required. It shows the
selected denominator, failures/errors, method/model composition and measured
usage. This checks supplied records, not native execution or provider identity.
There is no cross-benchmark aggregate leaderboard in this version.

Detailed recording is optional and enabled by default. The reference driver
supports `standard`/`minimal` and granular retention switches; see
[recording scope and limitations](recording.md). Disabling them does not change
live agent input, native execution, score or publication eligibility. Client
retention does not turn off native-server capture. Service source snapshots and
recorded configuration remain separate from runtime interaction recording.

The default permanent visual record is the native camera video retained on the server,
when the adapter produces it; shared transport does not synthesize missing videos.
Clients retain references rather than duplicate media downloads. Frame images
remain available during execution. After successful native finalization/close,
eligible frames are removed only when nonempty, hash-stable video files meet the
declared-camera count check. Otherwise frames remain as fallback evidence with a
warning. This check does not attest decoding or camera/frame correspondence;
explicit frame retention and media downloads are opt-in. Historical records are unchanged.

[`reports/interaction_history.py`](../benchkit/reports/interaction_history.py)
exports a closed client run to standalone HTML and allowlisted JSON. It groups
events by policy call: reset/latest acknowledged observation supplied to
`Policy.act`, recorded output, proposed chunk, acknowledged controls, rejection
and termination. It also includes recorded action/state semantics and counters.
A control observation is not necessarily an additional model input; unattempted
action suffixes are not uncertain execution. Unrecorded rejected vectors cannot
be reconstructed from a chunk length.

The view's planned/unattempted counts cover the client-selected schedule in its
manifest. That can be a prefix of a larger service panel; this view alone does
not establish a full server or native-suite denominator.

This first view does not copy media, recover raw conversations or prove a
provider consumed an observation. It displays camera names and explicitly says
that pixels are not included. Unknown feedback schemas remain unexpanded.
Arbitrary native info, metadata, raw exceptions and provider receipts are not
forwarded into the public view. Users should still review task text and policy
notes before publishing their content.

Useful reproducibility information includes the recorded protocol, upstream Git
revision, native environment/controller and asset origin, where actually saved
in a supported format. These are not inferred from today's checkout. The
generic viewer initially exposes a bounded subset; benchmark-specific provenance
and video reports remain separate. It does not replace evidence checks.

## Internal source and result integrity

A client run records which version and configuration produced its score:
`manifest.runtime.git` holds the revision, dirty flag and a `diff` digest of
tracked changes across the whole checkout; `manifest.policy.parameters` holds
the model profile ID, effective configuration and `preset_sha256`/`prompt_sha256`. [`audits/closed_run.py`](../benchkit/audits/closed_run.py)
checks record consistency: episode count and order, per-episode events and
counters, summary sums and usage sums, with null meaning unknown. It does not
verify source files. Interaction export validates closed event/result consistency.

The client records its revision and configuration in the run manifest. Each
server deployment captures its own shared-service source snapshot
(`harness_source/` in the service root, limited to `SERVICE_SOURCE_FILES`) plus
the selected benchmark's supplemental files. It does not capture every
benchmark or require agentic policy implementation files. A source inventory describes
the bytes captured for that deployment, not today's checkout. Keep existing
records and results unchanged as data; live code does not read their source
bundles.

Model results use `AgentPolicies/<profile>/results/<benchmark>/`; the entire
result tree stays local and Git-ignored, including reports, indices and media.
Selected summaries can be published in documentation or the website.
Historical anonymous trials cannot be relabeled as a named
model's scores.

## Current limits

Long-term goals include automatic plugin discovery, central scheduling,
a comprehensive unified CLI and cross-benchmark leaderboards. They are not all
implemented here. The current version provides the service selector and case
leasing while stabilizing contracts and the public usage path. Future aggregate
rankings require explicit coverage, comparability, normalization and missing/error
denominators; per-benchmark results remain available.

The [service support matrix](../benchmarks/simBenchmarks/SERVICE_SUPPORT.md)
distinguishes implemented adapters from protocol drafts and their remaining
native acceptance gates. Installation and portability constraints differ by
benchmark and are documented at each entrypoint. Broader native task/reset
selection and unified hardware adapters are incomplete. Direct provider receipts are not independent
metering/identity attestation. OS-level isolation is planned for a later version.

See [evaluation workflow](evaluation.md) and the
[policy protocol](../benchmarks/simBenchmarks/POLICY_PROTOCOL.md) before comparing results.
