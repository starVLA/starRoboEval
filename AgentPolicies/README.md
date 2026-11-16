# AgentPolicies

This directory holds reference clients and your own agent methods for
[starRoboEval](../README.md). Each method keeps its implementation and trusted
evaluation entrypoint together, including its models, prompts, memory, tools
and decision loop. Name its directory after the method; it may use one or several
general-purpose models.

## Add your own method

Create `AgentPolicies/<your_method>/` and keep its code, configuration and usage
instructions together. A suggested Python layout is:

```text
AgentPolicies/my_agent/
├── README.md       # Dependencies, configuration and launch command
├── __init__.py
├── run.py          # Trusted entrypoint connecting to a benchmark service
├── policy.py       # Observation-to-action decision logic
├── configs/        # Method configuration and prompts
├── tools/          # Optional method helpers
└── results/        # Local outputs by benchmark; Git-ignored
```

Use only the folders your method needs. Document its dependencies and run its
own entrypoint from the repository root, such as
`python -m AgentPolicies.my_agent.run`, with the arguments in its README.

Follow the [agentic policy integration guide](../docs/agent-methods.md#add-your-policy)
for the shared Python runner or your own protocol driver. Profile loading is
optional; source-checkout use requires no central model registration. Including
the method in a built wheel also requires updating package and data inclusion
in `pyproject.toml`. `rsi-bench run --policy` is reserved for diagnostics.

## Existing clients

- [`gpt6_astra/`](gpt6_astra/README.md): a Codex-based agentic policy with a
  persistent conversation and numeric robot actions through `robot_act`.
- [`claude_opus/`](claude_opus/README.md): a Messages API agentic policy with
  its own configuration and runtime, using the same benchmark service contract.

Each client's README documents its installation, configuration and launch
command. The [protocol skill](../docs/bench-server-protocol/SKILL.md) provides
optional integration notes and an educational example.

## Shared services and results

The reusable [runner](../benchkit/driver/runner.py) and
[service client](../benchkit/sim_server/client.py) are available to every method.
Benchmark environments, task definitions, native control and scoring belong
under [`benchmarks/`](../benchmarks/simBenchmarks/README.md).

Keep service credentials and administrative operations in the trusted driver.
The model receives only the declared observations and execution feedback.
Planning, memory, model composition and action decisions belong to the method.

Save outputs under `AgentPolicies/<method>/results/<benchmark>/`. The entire
results tree is local and Git-ignored, including reports, indices and media.
Preserve original outcomes, errors and method identities; publish selected
summaries in documentation or the website. [Recording options](../docs/recording.md)
control optional interaction and media retention while keeping essential results.
