# Direct native-vector control through a benchmark server

`codex-native/v1` is a separate model-owned method for declared numeric action
spaces, including SimplerEnv delta7, LIBERO OSC7 and SIMPLE physical36. It is
not the historical RoboDojo EEF16 `codex-direct/v2` method and does not establish matching
capability or reference scores. Never translate its vectors into Dojo poses.

The [policy](../methods/codex_native.py), [preset](../configs/codex_native_config.json), and
[prompt](../prompts/codex_native_prompt.txt) belong to this model. The selected benchmark
owns sensors, action semantics, reset schedule, control timing and native success.
Native low-level control remains on the service; no task-solving skill, learned
action proposal, hidden-state planner or local simulator fallback is added.

Each counted policy call obtains one action response through Codex CLI using the
existing login, with current original RGB, explicitly declared robot state,
the action contract, budgets and at most eight previously acknowledged action
chunks/notes. Only executed prefixes enter memory. Episode identity, reset
seed, oracle object state, reward and private scores never enter that request.
The transport uses [Codex structured output](https://learn.chatgpt.com/docs/non-interactive-mode)
and rejects observed tool calls. This trusted-local wrapper is not an OS
sandbox, provider identity attestation or provider request meter. Requested
model/effort are pinned to `gpt-6-astra`/`xhigh`; an output-token cap is **not**
enforced by this CLI wrapper (`max_output_tokens: null`). No API key or SDK
fallback is used by this method. Recoverable pre-action transport failures may
be retried within that same policy call, as described below. Provider-internal
request and retry counts remain unknown.

For new SimplerEnv runs, select `interaction_mode: "agent_method"` explicitly
in the server parameters. Its `/agent-method/v1` protocol permits declared
method-internal inference without claiming a provider-request count. This CLI
method uses bounded, recorded CLI attempts per counted decision and rejects
observed tool calls; the benchmark mode does not change those method settings.
One CLI invocation is insufficient evidence for SimplerEnv's historical
`single_response` provider-request restriction. Existing runs retain their
original track and accounting limitations.

### Wait and recover before an action

The native preset allows **10 total attempts, including the initial attempt**,
at one decision point, with a 10-second delay between recoverable failures.
Each attempt retains its own timeout (300 seconds in the default preset).
These are policy transport settings, not extra benchmark episodes or controls.

Stderr is bounded diagnostic output, not by itself a failed action or a reason
to kill a running CLI. The wrapper waits for structured completion, process
exit or the attempt deadline. The official
[non-interactive CLI documentation](https://learn.chatgpt.com/docs/non-interactive-mode)
describes stderr as a progress channel. This does not establish that every CLI
error is harmless or that model-catalog refresh errors are always recoverable.

After a classified recoverable failure, the wrapper cleans up its owned process
before trying the same frozen input again. The simulation remains at the last
acknowledged control boundary: no reset, extra observation query or `step` is
sent. Only a valid returned decision reaches the driver. A response is not
discarded and regenerated merely because its proposed action is invalid or
unsuccessful. Action rejection remains a separate, counted feedback path.

If all 10 attempts fail, retain an **infrastructure interruption**, not a native
task failure. Security/identity violations, forbidden tool activity, invalid
event streams, failed process cleanup and uncertain robot execution are not
ordinary retry conditions. They must not be hidden by another invocation.

One `Policy.act` call can therefore contain several recorded transport attempts;
it still produces at most one decision. Receipts record attempts, recoverability,
backoff and available usage. Any unreported inference cost remains unknown,
not zero. Recovery does not imply that the provider made only one request.

### CLI interruption evidence

New receipts include `stderr_diagnostic`: capture time, observed byte count and
SHA-256, a bounded-prefix hash, recognized diagnostic phrases/statuses, and
whether collection was incomplete. Only fixed allowlisted phrases are retained;
unknown text, credentials, provider bodies and reasoning are not copied into
receipts. Recognized phrases are observed hints, **not verified root causes**.
`wrapper_terminated_running_process` distinguishes wrapper cleanup of a running
CLI from a previously exited process. Early rejection may lose later output;
hashes cover captured bytes, not a hypothetical complete stderr stream.

The episode error already binds these receipts to the policy call, timestamp
and executed control counts. Preserve original failed results; do not rewrite
old receipts or silently restart episodes to collect better diagnostics.

Invalid JSON/actions are rejected before execution, without clamping or repair.
When the declared interaction track supports feedback, the next ordinary counted
call gets the last acknowledged observation and a bounded validation issue.
An acknowledged prefix remains real. Uncertain robot execution is terminal, never
an invitation to replay actions. A finite policy-call cap is mandatory.
Model transport recovery and typed action rejection are distinct; native-runtime
failures remain terminal.
For SimplerEnv explicitly set `action_rejection_feedback: true` in the server
parameters; this adds `/action-feedback` before the `/agent-method/v1` suffix
for the new interaction mode.
The unchanged legacy fail-fast track does not permit feedback continuation.

## One-task sample

Start the benchmark server in its native environment following its README and
fixed parameter file. Set matching private `RSI_SIM_SERVER_TOKEN` on the service
and trusted driver; expose only loopback, using SSH forwarding across nodes.
Never place credentials in task JSON, prompts, published artifacts or Git.

```sh
python -B -m benchkit preflight-policy --model-profile gpt6_astra \
  --policy-args '{"control_method":"codex-native/v1"}'

python -B -m AgentPolicies.gpt6_astra.run \
  --sim-server http://127.0.0.1:8765 --benchmark simpler_env \
  --control-method codex-native/v1 --seed 20260907 --episodes 1 \
  --budget-mode horizon --max-policy-calls 200 --replan-interval 5 \
  --max-steps 80 \
  --output-dir AgentPolicies/gpt6_astra/results/simpler_env/raw \
  --run-id YYYY-MM-DD-google_robot_pick_horizontal_coke_can-can-picking-service-sample
```

This example uses SimplerEnv's horizontal-can native horizon of 80 controls,
with a separately declared method cap of 200 decision calls and prefix at most
five. Calls are not provider requests; the method cap does not extend native
execution. The server example selects `budget_mode: "horizon"`,
`interaction_mode: "agent_method"` and `action_rejection_feedback: true` before
launch; both interaction selections are part of the recorded benchmark protocol.
The explicit decision-200/prefix-5 development track remains available with
matching adapter/driver settings and a 1000-control cap, reported separately.
For LIBERO use `--benchmark libero`, for SIMPLE `--benchmark simple_humanoid`,
with their independently selected task/reset, native execution cap, method-call
cap and result namespace; do not copy the can task's 80-control limit. Do not add
`--action-guard` or `--image-max-edge`: those options configure Dojo methods,
not native-vector units or bounds. Select one task/reset before execution, run
it once, retain failures and typed infrastructure errors. A sample is neither
native full coverage nor a statistically meaningful success rate. Server and
client source plus both output directories must be retained under model results.

## Readiness is not a capability result

CPU tests check serialization, exact actions, image/state allowlists, rejection
feedback and source binding. Native import/renderer diagnostics check environment
readiness. Only a closed model-driven episode supplies a native task outcome.
Record model calls, executed decisions, controls and first-success counts
separately; never infer decisions by dividing controls by chunk length.
