# Quick start: RoboCasa365

This example runs one **RoboCasa365 CloseBlenderLid** case, connects the
GPT-6-Astra reference client and exports a result page. Run commands from the
repository root, with separate terminals for the service and client.

## 1. Prepare the environment and client

Use Python 3.10 or newer. On a Linux benchmark host, follow the
[RoboCasa365 environment setup](../benchmarks/simBenchmarks/Robocasa_365/environment/README.md)
to install the pinned simulator, kitchen assets and graphics dependencies. Install
this repository in that environment:

```sh
python -m pip install --no-deps -e .
rsi-bench list
```

In the client environment, install the reference client's dependencies. It uses
an existing Codex CLI login with access to the model in its
[configuration](../AgentPolicies/gpt6_astra/configs/codex_native_config.json).

```sh
python -m pip install -e '.[gpt6-astra-codex]'
python -B -m benchkit preflight-policy --model-profile gpt6_astra
```

Set the same private `RSI_SIM_SERVER_TOKEN` in both terminals: 32–256 characters
using letters, digits, `_` or `-`. Also set these output variables in both
terminals, choosing a fresh run name for each evaluation:

```sh
BENCH_RESULTS=AgentPolicies/gpt6_astra/results/robocasa365
BENCH_RUN_ID=CloseBlenderLid-close-blender-lid-example01
```

## 2. Start RoboCasa365

In the prepared native environment:

```sh
MUJOCO_GL=egl PYOPENGL_PLATFORM=egl rsi-bench serve \
  --benchmark robocasa365 \
  --parameters benchmarks/simBenchmarks/Robocasa_365/server.example.json \
  --seed 20260907 --episodes 1 --port 8765 \
  --output-dir "$BENCH_RESULTS/server/$BENCH_RUN_ID"
```

The supplied configuration selects GPU 0 and the
`egl-owner-material-clamp-v1` rendering track. This command selects the first
case in its schedule, `CloseBlenderLid`, with a **900-control** task horizon.
See the [service guide](../benchmarks/simBenchmarks/Robocasa_365/README.md) to choose
a different schedule or rendering track. For a remote host, use
[SSH forwarding](../benchmarks/simBenchmarks/SERVER_PROTOCOL.md#launch-and-connect).

## 3. Connect the reference agent

In the client terminal:

```sh
python -B -m AgentPolicies.gpt6_astra.run \
  --sim-server http://127.0.0.1:8765 --benchmark robocasa365 \
  --seed 20260907 --episodes 1 --max-policy-calls 900 \
  --output-dir "$BENCH_RESULTS/client" --run-id "$BENCH_RUN_ID"
```

The 900-call allowance is an explicit setting for this example agent run.
The service separately enforces the task's control horizon and native outcome.
The [GPT-6-Astra client guide](../AgentPolicies/gpt6_astra/README.md) documents model
settings and execution behavior; a [Claude client](../AgentPolicies/claude_opus/README.md)
is also available.

## 4. View the result

After the client run closes:

```sh
python -B -m benchkit.reports.basic_result \
  --run-dir "$BENCH_RESULTS/client/$BENCH_RUN_ID" \
  --output-dir "$BENCH_RESULTS/report/$BENCH_RUN_ID"
```

Open `$BENCH_RESULTS/report/$BENCH_RUN_ID/index.html` in a browser. The adjacent
`result.json` provides the structured report. Native recordings remain under
the server output directory; client results retain their references.

Results include the selected cases, native outcomes, errors, method settings,
execution counters and available inference usage. Detailed
[interaction histories](evaluation.md#inspect-and-report) are available
when interaction recording is enabled. Generated results stay local and are
Git-ignored.

Next, [connect your own agent](agent-methods.md#add-your-policy) or explore the
[benchmark integrations](../benchmarks/simBenchmarks/README.md).
