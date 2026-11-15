# Shared benchmark service

This package implements the [SIM server protocol](../../benchmarks/simBenchmarks/SERVER_PROTOCOL.md).
New integrations follow the [RoboDojo-derived conventions](../../benchmarks/simBenchmarks/SERVICE_CONVENTIONS.md).
Each benchmark's `server.py` selects its native adapter; these shared modules
provide strict JSON transport, single-attempt sessions and artifact transfer.
They do not generate actions, call a model or run a separate scheduling service.

- `server.py` owns the administrative RPC lifecycle and serialized native calls.
- `wire.py` serializes the declared observations and evaluator-private transitions.
- `launch.py` supplies common launch mechanics to benchmark-owned entrypoints.
  `--episode-id ID` serves one explicit episode from the complete native
  schedule (recorded as `selection` in the description); `--list-episodes`
  prints that schedule without a token, output directory or HTTP listener.
- `client.py` is an **administrative client for a trusted run driver**, not a
  model-facing tool. It can read schedules, deployment information, native
  metrics and finalized artifacts. Never give it, its endpoint or its bearer
  credential to the model actor.
- `gateway.py` (bench host) and `remote_run.py` (agent host) run catalog cases
  across hosts; see [Separate bench host](#separate-bench-host).

An agent-owned trusted driver may use this client and pass only the declared
observation to its model. Returning an action does not give the model native
simulator access. The model owns target selection, memory and voluntary stopping;
the benchmark owns native control conversion, termination and scoring. Results
and videos belong under `AgentPolicies/<profile>/results/<benchmark>/`.

Reward and transition information are evaluator-private, not policy inputs.
The trusted driver may obtain cached metrics before closing the episode;
artifact downloads require finalized, closed-file inventory. Idle service time
does not step physics, lost acknowledgements do not replay controls, and a
failed attempt is not automatically replaced.

This is an ownership/protocol boundary, not OS-enforced isolation. A trusted
driver's administrative permissions are not safe capabilities for an untrusted
actor. If the actor itself must access a service, an independently reviewed
episode-scoped public control interface is required; this client does not
implement that interface. What reaches the model is the policy's responsibility.

## Separate bench host

The simulators can run on a bench host that the agent host cannot log in to.
Switching benchmark, task or episode is then a choice among operator-declared
cases, not a shell command on the bench host.

**Bench host (operator).** A catalog fixes the slots (loopback ports and
device environment, e.g. one GPU each) and the profiles (one benchmark
deployment each: service ID, Python, source snapshot, parameters, seed):

```json
{"schema_version": "starvla-rsi.gateway-catalog/v1",
 "slots": [{"id": "gpu0", "port": 18801, "env": {"CUDA_VISIBLE_DEVICES": "0"}}],
 "profiles": {"vln_ce": {"service": "vln_ce", "python": "/abs/env/bin/python",
   "source": "/abs/source-snapshot", "parameters": "/abs/vln_ce-max.json", "seed": 0,
   "default_per_task": null}}}
```

```sh
rsi-bench gateway inventory --catalog catalog.json --state-dir state --profile vln_ce
RSI_GATEWAY_TOKEN=... rsi-bench gateway serve --catalog catalog.json --state-dir state --port 18800
```

`inventory` lists the profile's complete native schedule once with
`--list-episodes`; each episode is one case, `PROFILE:EPISODE_ID`. Two panels
are derived: `full` keeps every native episode, and `default` keeps the first
`default_per_task` episodes of each task (5 if unset; `null` means all). Configure
the profile parameters for the benchmark's complete episode set so that nothing
beyond the default is lost. The gateway refuses a stale inventory.
A benchmark whose service requires its complete schedule (RoboDojo) declares so
in the listing: both panels are then the full schedule, `default_per_task` does
not apply, and `remote-run` refuses `--case-file` and `--limit` for it.

`launch` starts the case's service with `--episode-id` on the
requested slot, with a fresh per-lease token, and waits for a matching
description. A service that listens but fails the client's description checks
fails the launch at once (`service_contract_mismatch`; the cause is in the
gateway's `events.jsonl`). The slot port relays to that service until `release`, which sends
SIGTERM to the owned process group and verifies that it is gone; it never
SIGKILLs. An unverified stop quarantines the slot. Every launch is a new lease
with its own record under `state/leases/`; any case can be launched again.
A profile's `startup_timeout_s` (default 900) plus `stop_timeout_s` (default 180)
must stay 120 s under the driver's 3600 s wait for one reply. On SIGTERM or
Ctrl-C the gateway refuses new launches, stops every ready or still-starting
service and writes its release record before exiting.

**Agent host (trusted driver).** Forward the control and slot ports, then run
the cases with any client command:

```sh
ssh -N -L 18800:127.0.0.1:18800 -L 28801:127.0.0.1:18801 bench-host
RSI_GATEWAY_TOKEN=... rsi-bench remote-run --gateway http://127.0.0.1:18800 \
  --profile vln_ce --panel default --slot gpu0=28801 \
  --client-command client.json --run-id-prefix 2026-11-01- --output-dir records/
```

`client.json` holds `{"argv": [...], "cwd": ..., "env": {...}}` with the
placeholders `{endpoint}`, `{benchmark}`, `{seed}`, `{episodes}`, `{run_id}`,
`{case_id}`, `{episode_id}` and `{output_dir}`, for example
`["python", "-m", "<driver>", "--sim-server", "{endpoint}", ...]`. `{run_id}` is
the prefix, the case and the lease ID, so every attempt has its own. The client gets the
lease token as `RSI_SIM_SERVER_TOKEN` and never the gateway token. Each slot is
one sequential lane. A lane stops at its first engineering error (nonzero exit,
unverified cleanup, or no opened episode); ordinary failures are results.
`--case-file` fixes an explicit case order. The first start writes `plan.json`
(profile, panel and the planned case IDs, before `--limit`); it is the
denominator of a [publication](../reports/README.md#publication), and a rerun
that would plan other cases is refused. Rerunning with the same output
directory skips completed cases and leases the others again, keeping each
earlier attempt directory; an unreadable or inconsistent `completion.json`
stops the run before any lease. A crash is not an attempt, but a nonzero exit after
an episode opened can also be a recorded policy error, which is a result:
review the client record before rerunning such a case. Nothing stops a new
output directory from running completed cases again; doing so would be an
unauthorized second attempt.

To make the separation OS-enforced on the bench host, give the agent host's SSH
key forwarding rights only, for example in `authorized_keys`:

```text
restrict,port-forwarding,command="/bin/false",permitopen="127.0.0.1:18800",permitopen="127.0.0.1:18801" ssh-ed25519 AAAA... agent-host
```

The agent host then has no shell, file access or process control on the bench
host; server-side videos and records stay there, and the operator copies them.
This separates hosts, not the model from its driver: the driver and the model
still share the agent host, as described above.

## Ownership and source capture

`benchkit/sim_server/` is the sole implementation, not an import alias. Reusable
communication belongs here; task catalogs, native adapters and scoring belong
under `benchmarks/simBenchmarks/<benchmark>/`; decisions belong under `AgentPolicies/`.
This is a library used by the two control ends, not a third scheduling process.
The temporary `benchmarks/simBenchmarks/service/` package is removed, without
changing RPC version, fields, schedules, scoring, actions or artifact limits.
Old records and source bundles remain data; live code does not read them.
Generic contracts remain in `benchkit/contracts.py` and
`benchkit/interfaces.py`.

`python -B -m benchkit.sim_server` starts only the dependency-free synthetic
diagnostic service; `make smoke` starts it on an ephemeral port and runs its
self-check through it. It is not a native robot benchmark or capability evidence.
For a native benchmark, use its own
`benchmarks.simBenchmarks.<benchmark>.server` entrypoint.

New service snapshots capture the explicit shared-service runtime inventory and
the selected wrapper's supplemental files. Starting one service does not require
other benchmarks or model drivers. Agent-side clients capture no source; they
record their git revision and dirty flag. Existing inventories are unchanged.
Run only from a stable versioned source snapshot;
never update files inside an active or historical run.

Cross-benchmark contract checks stay local and untracked. New changes need
independent contract validation and a connect-level check through a running
service. Offline validation does not replace native readiness or model-sample checks.
