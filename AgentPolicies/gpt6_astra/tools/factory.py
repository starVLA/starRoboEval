"""Explicit selection of the three active Codex methods; no retired entrypoints."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).absolute().parents[1]
METHODS = ("codex-native/v1", "codex-direct/v3", "codex-planned/v1")


def create_policy(*, config, identity, control_method=None, image_max_edge=None, **parameters):
    method = control_method or config.get("control_method", "codex-native/v1")
    if method not in METHODS:
        raise ValueError("unknown or retired model control method")
    if "safety_stop" in parameters and method not in ("codex-direct/v3", "codex-planned/v1"):
        raise ValueError("safety_stop override is supported only by Direct v3 or Planned v1")
    if "enforce_action_guard" in parameters:
        raise ValueError("retired robot-specific motion guards are not supported by active methods")
    # The registry default is Native. An explicit method selection owns its own
    # default prompt; an actually custom prompt remains an explicit override.
    default_prompt = (ROOT / "prompts/codex_native_prompt.txt").read_text()
    if parameters.get("prompt") == default_prompt:
        parameters["prompt"] = None
    if method == "codex-native/v1":
        if image_max_edge is not None:
            raise ValueError("Codex native uses original RGB, not image previews")
        from AgentPolicies.gpt6_astra.methods.codex_native import CodexNativePolicy
        return CodexNativePolicy(identity=identity, **parameters)
    if method == "codex-direct/v3":
        from AgentPolicies.gpt6_astra.methods.codex_direct import CodexDirectPolicy
        parameters.setdefault("safety_stop", config.get("safety_stop"))
        return CodexDirectPolicy(identity=identity, image_max_edge=image_max_edge, **parameters)
    from AgentPolicies.gpt6_astra.methods.codex_planned import CodexPlannedPolicy
    parameters.setdefault("safety_stop", config.get("safety_stop"))
    return CodexPlannedPolicy(identity=identity, image_max_edge=image_max_edge, **parameters)
