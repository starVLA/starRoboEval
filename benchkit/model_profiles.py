"""Explicit model profiles, with no eager provider imports.

A profile lives in ``AgentPolicies/<id>/configs/profile.json`` and names its own
factory, configuration, configuration schema and prompt. This module reads those
declarations and applies generic schema checks; field meanings stay with the policy.
"""

from __future__ import annotations

from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import replace
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import sys
from typing import Any

PROFILE_SCHEMA = "starvla-rsi.model-profile/v2"
_CONFIGURATION_SCHEMA = "starvla-rsi.configuration-schema/v2"
_ROOT = Path(__file__).absolute().parents[1]
# Config keys that bind a run to its declared policy; never overridable.
_IDENTITY_CONFIG_KEYS = frozenset({"schema_version", "profile_id", "transport", "provider", "model"})
_CREDENTIAL_FIELDS = frozenset({"api_key", "apikey", "authorization", "credentials", "credential",
                               "secret", "client_secret", "password", "token", "api_token",
                               "access_token", "refresh_token", "bearer_token"})


def _json(payload: bytes) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate model JSON key: {key}")
            result[key] = value
        return result

    def constant(value):
        raise ValueError(f"invalid model JSON constant: {value}")

    return json.loads(payload, object_pairs_hook=pairs, parse_constant=constant)


def _scalar_type(value: Any, kind: str) -> bool:
    if kind == "number":
        return type(value) is int or (type(value) is float and math.isfinite(value))
    return type(value) is {"string": str, "integer": int, "boolean": bool, "null": type(None)}.get(kind)


def validate_configuration(profile_id: str, config: dict, schema: dict) -> dict[str, Any]:
    """Validate bounded declarative scalar fields; never execute model code."""
    if (not isinstance(schema, dict) or set(schema) - {"runtime_preflight"} != {
            "schema_version", "profile_id", "fields", "factory_parameters"}
            or ("runtime_preflight" in schema and schema["runtime_preflight"] is not True)
            or schema.get("schema_version") != _CONFIGURATION_SCHEMA
            or schema.get("profile_id") != profile_id):
        raise ValueError("invalid model configuration schema")
    fields = schema["fields"]
    parameters = schema["factory_parameters"]
    if (not isinstance(fields, dict) or not 1 <= len(fields) <= 64
            or not isinstance(config, dict) or set(config) != set(fields)
            or not isinstance(parameters, list) or any(not isinstance(key, str) for key in parameters)
            or len(parameters) != len(set(parameters))):
        raise ValueError("model configuration fields or factory parameters differ from schema")
    for key, rule in fields.items():
        if (not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key)
                or key in _CREDENTIAL_FIELDS
                or any(key.endswith("_" + name) for name in ("api_key", "token", "secret", "password", "credentials"))
                or not isinstance(rule, dict)
                or set(rule) - {"type", "const", "enum", "minimum", "maximum"}
                or rule.get("type") not in ("string", "integer", "number", "boolean", "null")):
            raise ValueError("unsafe or unsupported model configuration field schema")
        kind, value = rule["type"], config[key]
        if not _scalar_type(value, kind):
            raise ValueError(f"invalid model configuration type: {key}")
        if "const" in rule and (not _scalar_type(rule["const"], kind) or value != rule["const"]):
            raise ValueError(f"model configuration constant mismatch: {key}")
        if "enum" in rule:
            choices = rule["enum"]
            if (not isinstance(choices, list) or not 1 <= len(choices) <= 32
                    or any(not _scalar_type(choice, kind) for choice in choices) or value not in choices):
                raise ValueError(f"invalid model configuration choice: {key}")
        for bound in ("minimum", "maximum"):
            if bound in rule:
                limit = rule[bound]
                if kind not in {"integer", "number"} or not _scalar_type(limit, "number"):
                    raise ValueError(f"invalid model configuration bound: {key}")
                if (bound == "minimum" and value < limit) or (bound == "maximum" and value > limit):
                    raise ValueError(f"model configuration exceeds declared bounds: {key}")
    if set(parameters) - {"prompt"} - set(fields):
        raise ValueError("model factory parameters must bind declared configuration fields")
    # A policy declares its overridable fields in its own schema, except the
    # identity keys that bind a run to its declared policy.
    if set(parameters) & _IDENTITY_CONFIG_KEYS:
        raise ValueError("model factory parameters must not override identity fields")
    return {"factory_parameters": tuple(parameters),
            **({"runtime_preflight": True} if "runtime_preflight" in schema else {})}


def load_profile(profile_id: str) -> dict[str, Any]:
    """Read one profile's declarations from its own directory."""
    if not isinstance(profile_id, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", profile_id):
        raise ValueError(f"invalid model profile ID: {profile_id!r}")
    directory = _ROOT / "AgentPolicies" / profile_id
    profile_path = directory / "configs/profile.json"
    if not profile_path.is_file():
        raise ValueError(f"unknown model profile: {profile_id!r}")
    profile = _json(profile_path.read_bytes())
    if (not isinstance(profile, dict) or set(profile) != {
            "schema_version", "id", "display_name", "factory", "config", "configuration_schema", "prompt", "policy"}
            or profile["schema_version"] != PROFILE_SCHEMA or profile["id"] != profile_id
            or not isinstance(profile["factory"], str)
            or not re.fullmatch(rf"AgentPolicies\.{profile_id}(\.[a-z_][a-z0-9_]*)+:[a-z_][a-z0-9_]*",
                                profile["factory"])
            or any(not isinstance(profile[key], str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_./-]*", profile[key])
                   or ".." in Path(profile[key]).parts
                   for key in ("config", "configuration_schema", "prompt"))):
        raise ValueError("invalid model profile declaration")
    config_bytes = (directory / profile["config"]).read_bytes()
    config = _json(config_bytes)
    configuration = _json((directory / profile["configuration_schema"]).read_bytes())
    prompt = (directory / profile["prompt"]).read_text(encoding="utf-8")
    execution = validate_configuration(profile_id, config, configuration)
    policy = profile["policy"]
    if (config.get("schema_version") != "starvla-rsi.model-config/v1" or config.get("profile_id") != profile_id
            or not isinstance(policy, dict) or set(policy) != {"name", "kind", "model", "provider"}
            or any(not isinstance(policy[key], str) or not policy[key].strip() for key in policy)
            or any(policy[key] != config.get(key) for key in ("provider", "model"))):
        raise ValueError("invalid model profile policy identity")
    if not prompt.strip() or len(prompt) > 32768:
        raise ValueError("profile prompt must be nonempty and at most 32768 characters")
    return {"profile": profile, "config": config, "prompt": prompt, "configuration": configuration,
            "preset_sha256": hashlib.sha256(config_bytes).hexdigest(), **execution}


def validate_policy_parameters(data: dict[str, Any], parameters: dict[str, Any]) -> None:
    """Check factory overrides against the profile's declarations, without importing a model."""
    allowed = set(data["factory_parameters"])
    if set(parameters) - allowed:
        raise ValueError(f"unsupported profile policy parameters: {sorted(set(parameters) - allowed)}")
    effective = {**data["config"], **{key: value for key, value in parameters.items()
                                   if key != "prompt" and value is not None}}
    validate_configuration(data["profile"]["id"], effective, data["configuration"])


def create_policy(profile_id: str, **parameters):
    """Resolve one profile factory lazily; record the profile ID and configuration digest.

    The factory receives the loaded configuration, schema, identity and prompt;
    it does not read the profile files again.
    """
    data = load_profile(profile_id)
    validate_policy_parameters(data, parameters)
    parameters.setdefault("prompt", data["prompt"])
    module_name, function_name = data["profile"]["factory"].split(":")
    module = importlib.import_module(module_name)
    policy = getattr(module, function_name)(config=data["config"], schema=data["configuration"],
                                            identity=data["profile"]["policy"], **parameters)
    policy.descriptor = replace(policy.descriptor, parameters={
        **policy.descriptor.parameters, "model_profile": profile_id, "preset_sha256": data["preset_sha256"],
    })
    return policy


@contextmanager
def _quiet_runtime():
    """Silence Python and native fd output in the single-threaded preflight CLI.

    Dependency initialization can print before raising. Do not retain those
    bytes in memory or files. This is output hygiene, not process isolation.
    """
    sys.stdout.flush()
    sys.stderr.flush()
    with open(os.devnull, "w", encoding="utf-8") as sink, redirect_stdout(sink), redirect_stderr(sink):
        saved = []
        try:
            for descriptor in (1, 2):
                saved.append((descriptor, os.dup(descriptor)))
                os.dup2(sink.fileno(), descriptor)
            yield
        finally:
            sink.flush()
            for descriptor, original in reversed(saved):
                try:
                    os.dup2(original, descriptor)
                finally:
                    os.close(original)


def preflight_policy(policy) -> None:
    """Invoke a declared model capability, never native code or inference.

    Exception bodies from third-party imports/constructors are not public
    diagnostics. Reconstruct only a closed error code outside the handler.
    """
    from benchkit.errors import PolicyPreflightError

    code = None
    try:
        with _quiet_runtime():
            check = getattr(policy, "preflight_runtime", None)
            if not callable(check):
                code = "unsupported"
            elif check() is not None:
                code = "initialization_failed"
    except PolicyPreflightError as exc:
        code = exc.code
    except Exception:
        code = "initialization_failed"
    if code is not None:
        raise PolicyPreflightError(code) from None


def preflight_profile(profile_id: str, **parameters):
    """Construct and locally check a declared profile with closed diagnostics.

    No benchmark is imported; the returned policy has not started an episode.
    Use only at the single-threaded CLI boundary (output fds are process-wide).
    """
    from benchkit.errors import PolicyPreflightError

    code = None
    policy = None
    try:
        with _quiet_runtime():
            if not load_profile(profile_id).get("runtime_preflight"):
                raise PolicyPreflightError("unsupported")
            policy = create_policy(profile_id, **parameters)
            preflight_policy(policy)
    except PolicyPreflightError as exc:
        code = exc.code
    except Exception:
        code = "initialization_failed"
    if code is not None:
        raise PolicyPreflightError(code) from None
    return policy
