"""One public-state echo through a SIM server, explicitly not a capability eval.

Use only after inspecting that every action is an absolute robot target with
the same units/frame as its identically named sensor. This does not infer action
semantics or guarantee physical holding. Never use on a real robot.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from benchkit.contracts import ActionChunk, PolicyDecision, PolicyDescriptor, Usage
from benchkit.errors import PolicyError
from AgentPolicies.gpt6_astra.tools.runner import EvaluationRunner, RunRequest
from benchkit.sim_server.client import SimServerBenchmarkAdapter


class StateEchoDiagnostic:
    descriptor = PolicyDescriptor(name="public-state-echo-infrastructure", kind="infrastructure-diagnostic",
        version="state-echo/v1", parameters={"model_calls": 0, "capability_evaluation": False,
            "actions": "echo identically named public sensors once; no task strategy"})

    def compatibility_errors(self, observation_spec, action_spec):
        if (observation_spec.privileged or not action_spec.names
                or len(set(observation_spec.state_names)) != len(observation_spec.state_names)
                or len(set(action_spec.names)) != len(action_spec.names)
                or not set(action_spec.names) <= set(observation_spec.state_names)):
            return ["state echo requires unique, explicitly matched nonprivileged sensor/target names"]
        return []

    def start_episode(self, context):
        errors = self.compatibility_errors(context.observation_spec, context.action_spec)
        if errors:
            raise PolicyError(errors[0])
        self.context, self.used = context, False

    def act(self, observation):
        if self.used or observation.step != 0 or observation.state is None:
            raise PolicyError("state echo permits exactly one initial diagnostic action")
        if len(observation.state) != len(self.context.observation_spec.state_names):
            raise PolicyError("diagnostic state differs from the declared sensors")
        measured = dict(zip(self.context.observation_spec.state_names, observation.state))
        vector = self.context.action_spec.validate([measured[name] for name in self.context.action_spec.names])
        self.used = True
        return PolicyDecision(action=ActionChunk.from_steps([vector]), usage=Usage(),
            note="One infrastructure-only public-state echo; not a task-solving model action")

    def end_episode(self):
        self.context = None


def completed_echo(result):
    """Check execution, not task success; a closed run is not necessarily a pass."""
    return (isinstance(result, dict) and result.get("status") == "completed" and result.get("error") is None
            and all(type(result.get(name)) is int and result[name] == 1
                    for name in ("environment_steps", "action_decisions", "policy_calls"))
            and isinstance(result.get("usage"), dict) and type(result["usage"].get("calls")) is int
            and result["usage"]["calls"] == 0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sim-server", required=True)
    parser.add_argument("--token-env", default="RSI_SIM_SERVER_TOKEN")
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--confirm-absolute-state-targets", action="store_true", required=True)
    args = parser.parse_args()
    benchmark = SimServerBenchmarkAdapter(args.sim_server, token=os.environ.get(args.token_env, ""), timeout=1200)
    if benchmark.parameters.get("diagnostic") is not True:
        raise ValueError("state echo requires an explicitly diagnostic-only SIM service")
    result = EvaluationRunner().run(benchmark, StateEchoDiagnostic(), RunRequest(
        output_dir=args.output, seed=args.seed, episode_limit=1, max_steps=1, max_policy_calls=1,
        replan_interval=1, run_id=args.run_id, fail_fast=True,
        repository=Path(__file__).absolute().parents[2]))
    print(result)
    with (result / "episodes.jsonl").open() as handle:
        first = handle.readline(1024 * 1024)
        extra = handle.read(1)
    return 0 if not extra and completed_echo(json.loads(first)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
