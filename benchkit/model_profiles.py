"""Explicit model profiles and bounded snapshots, with no eager provider imports.

Profiles select source/configuration, not a claim about an unidentified provider.
The allowlists below are intentionally small: model results, credentials and
arbitrary neighboring files are never collected by source capture.
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
import stat
import sys
from typing import Any

from benchkit.artifacts import atomic_write_json
from benchkit.source_snapshot import _identity, _open_source_file, inventory_digest

PROFILE_SCHEMA = "starvla-rsi.model-profile/v1"
SOURCE_SCHEMA = "starvla-rsi.model-source/v6"
TOOLS_SOURCE_SCHEMA = "starvla-rsi.model-source/v5"
GROUPED_SOURCE_SCHEMA = "starvla-rsi.model-source/v4"
FLAT_AGENT_SOURCE_SCHEMA = "starvla-rsi.model-source/v3"
PREVIOUS_SOURCE_SCHEMA = "starvla-rsi.model-source/v2"
LEGACY_SOURCE_SCHEMA = "starvla-rsi.model-source/v1"
MAX_FILE_BYTES = 256 * 1024
MAX_TOTAL_BYTES = 1024 * 1024
_FACTORIES = {
    "anonymous_code_agent": "AgentPolicies.anonymous_code_agent.policy:create_policy",
    "gpt6_astra": "AgentPolicies.gpt6_astra.tools.factory:create_policy",
    "opus": "AgentPolicies.opus.policy:create_policy",
}
_GROUPED_FACTORIES = {**_FACTORIES, "gpt6_astra": "AgentPolicies.gpt6_astra.methods.policy:create_policy"}
_FLAT_FACTORIES = {**_FACTORIES, "gpt6_astra": "AgentPolicies.gpt6_astra.policy:create_policy"}
_HISTORICAL_FACTORIES = {profile: factory.replace("AgentPolicies.", "starVLA.", 1)
                         for profile, factory in _FLAT_FACTORIES.items()}
_COMMON_FILES = ("AgentPolicies/__init__.py", "AgentPolicies/policy_support/__init__.py", "AgentPolicies/policy_support/stop_rules.py")
# v5 is a complete reviewed inventory, not an extension of retired methods.
# Historical v1-v4 inventories below remain immutable and independently usable.
_GPT_V5_FILES = (
    "__init__.py", "profile.json", "configuration.schema.json", "dependencies.json",
    "configs/config.json", "configs/codex_native_config.json",
    "configs/codex_direct_v2_config.json", "configs/codex_planned_config.json",
    "prompts/codex_native_prompt.txt", "prompts/codex_direct_v2_prompt.txt",
    "prompts/codex_planned_prompt.txt",
    "methods/__init__.py", "methods/codex_native.py", "methods/codex_direct.py",
    "methods/codex_planned.py", "transports/__init__.py", "transports/codex_cli.py",
    "transports/codex_app_server.py", "tools/__init__.py", "tools/factory.py",
    "tools/native_io.py", "tools/json_io.py", "tools/eef_contract.py",
    "tools/runtime_preflight.py", "tools/direct_public_context.py",
)
_GPT_V6_FILES = (
    "__init__.py", "profile.json", "configuration.schema.json", "dependencies.json",
    "configs/config.json", "configs/codex_native_config.json",
    "configs/codex_direct_v3_config.json", "configs/codex_planned_config.json",
    "prompts/codex_native_prompt.txt", "prompts/codex_direct_v3_prompt.txt",
    "prompts/codex_planned_prompt.txt",
    "methods/__init__.py", "methods/codex_native.py", "methods/codex_direct.py",
    "methods/codex_planned.py", "transports/__init__.py", "transports/codex_cli.py",
    "transports/codex_app_server.py", "tools/__init__.py", "tools/factory.py",
    "tools/native_io.py", "tools/json_io.py", "tools/persistent_runtime.py",
    "tools/runtime_preflight.py", "tools/public_observation.py",
)
_LEGACY_COMMON_FILES = ("starVLA/__init__.py", "starVLA/model_profiles.py", "starVLA/providers/__init__.py")
_CONFIGURATION_SCHEMA = "starvla-rsi.configuration-schema/v1"
_FACTORY_PARAMETERS = frozenset({"prompt", "timeout_s", "max_chunk_length", "min_action_decisions_before_give_up",
                                 "control_method", "enforce_action_guard", "image_max_edge", "safety_stop"})
_CREDENTIAL_FIELDS = frozenset({"api_key", "apikey", "authorization", "credentials", "credential",
                               "secret", "client_secret", "password", "token", "api_token",
                               "access_token", "refresh_token", "bearer_token"})


class UnconfiguredModelProfile(ValueError):
    """A display label is not a verified, runnable provider integration."""


def profile_ids() -> tuple[str, ...]:
    return tuple(_FACTORIES)


def _source_namespace(source_schema: str) -> str:
    """Bind one exact package root to each immutable source schema."""
    if source_schema in (SOURCE_SCHEMA, TOOLS_SOURCE_SCHEMA, GROUPED_SOURCE_SCHEMA, FLAT_AGENT_SOURCE_SCHEMA):
        return "AgentPolicies"
    if source_schema in (LEGACY_SOURCE_SCHEMA, PREVIOUS_SOURCE_SCHEMA):
        return "starVLA"
    raise ValueError("unsupported model source schema")


def _profile_relative(profile_id: str, name: str, source_schema: str) -> str:
    """Each version owns its exact paths, including the v5 default prompt."""
    if source_schema in (SOURCE_SCHEMA, TOOLS_SOURCE_SCHEMA) and profile_id == "gpt6_astra":
        if name == "prompt.txt":
            return "prompts/codex_native_prompt.txt"
        names = _GPT_V6_FILES if source_schema == SOURCE_SCHEMA else _GPT_V5_FILES
        return next((path for path in names if path.rsplit("/", 1)[-1] == name), name)
    if source_schema != GROUPED_SOURCE_SCHEMA or profile_id != "gpt6_astra":
        return name
    if name in {"policy.py", "codex_policy.py", "codex_direct.py", "codex_native.py", "codex_planned.py",
                "action_validation.py", "direct_public_context.py"}:
        return "methods/" + name
    if name in {"responses.py", "codex_cli.py", "codex_app_server.py"}:
        return "transports/" + name
    if name in {"config.json", "codex_config.json", "codex_v2_config.json",
                "codex_direct_config.json", "codex_direct_v2_config.json", "codex_native_config.json", "codex_planned_config.json"}:
        return "configs/" + name
    if name in {"prompt.txt", "codex_prompt.txt", "codex_v2_prompt.txt",
                "codex_direct_prompt.txt", "codex_direct_v2_prompt.txt", "codex_native_prompt.txt", "codex_planned_prompt.txt"}:
        return "prompts/" + name
    return name


def _allowed_files(profile_id: str, *, legacy: bool = False, source_schema: str = SOURCE_SCHEMA,
                   method_extensions: bool = True,
                   feedback_extensions: bool = True, persistent_extensions: bool = True,
                   context_extensions: bool = True, native_extensions: bool = True,
                   planned_extensions: bool = True) -> tuple[str, ...]:
    if not isinstance(profile_id, str) or profile_id not in _FACTORIES:
        raise ValueError(f"unknown model profile: {profile_id!r}")
    if legacy:
        source_schema = LEGACY_SOURCE_SCHEMA
    namespace = _source_namespace(source_schema)
    if source_schema in (SOURCE_SCHEMA, TOOLS_SOURCE_SCHEMA) and profile_id == "gpt6_astra":
        names = _GPT_V6_FILES if source_schema == SOURCE_SCHEMA else _GPT_V5_FILES
        return tuple(sorted(_COMMON_FILES + tuple("AgentPolicies/gpt6_astra/" + name
                                                 for name in names)))
    legacy = source_schema == LEGACY_SOURCE_SCHEMA
    common = (tuple(path.replace("AgentPolicies/", namespace + "/", 1) for path in _COMMON_FILES)
              if not legacy else _LEGACY_COMMON_FILES)
    files = common + tuple(f"{namespace}/{profile_id}/{name}" for name in (
        "__init__.py", "profile.json", "config.json", "prompt.txt", "dependencies.json", "policy.py"))
    if profile_id == "anonymous_code_agent":
        files += ("starVLA/providers/mailbox.py" if legacy else f"{namespace}/anonymous_code_agent/mailbox.py",)
        if not legacy:
            files += (f"{namespace}/anonymous_code_agent/prompts/control_guidance.txt",
                      f"{namespace}/anonymous_code_agent/prompts/actor_instructions.txt",
                      f"{namespace}/anonymous_code_agent/prompts/simpler_development.txt")
    elif profile_id == "gpt6_astra" and not legacy:
        files += (f"{namespace}/gpt6_astra/responses.py", f"{namespace}/gpt6_astra/configuration.schema.json")
        if method_extensions:
            if native_extensions:
                files += tuple(f"{namespace}/gpt6_astra/" + name for name in (
                    "codex_native.py", "codex_native_config.json", "codex_native_prompt.txt"))
            files += tuple(f"{namespace}/gpt6_astra/" + name for name in (
                "codex_cli.py", "codex_policy.py", "codex_config.json", "codex_prompt.txt"))
            if feedback_extensions:
                files += tuple(f"{namespace}/gpt6_astra/" + name for name in (
                    "action_validation.py", "codex_v2_config.json", "codex_v2_prompt.txt"))
                if persistent_extensions:
                    files += tuple(f"{namespace}/gpt6_astra/" + name for name in (
                        "codex_direct.py", "codex_direct_config.json", "codex_direct_prompt.txt",
                        "codex_app_server.py"))
                    if context_extensions:
                        files += tuple(f"{namespace}/gpt6_astra/" + name for name in (
                            "codex_direct_v2_config.json", "codex_direct_v2_prompt.txt", "direct_public_context.py"))
                        if planned_extensions and native_extensions and source_schema == GROUPED_SOURCE_SCHEMA:
                            files += tuple(f"{namespace}/gpt6_astra/" + name for name in (
                                "codex_planned.py", "codex_planned_config.json", "codex_planned_prompt.txt"))
    if source_schema == GROUPED_SOURCE_SCHEMA and profile_id == "gpt6_astra":
        prefix = f"{namespace}/gpt6_astra/"
        files = tuple(prefix + _profile_relative(profile_id, path.removeprefix(prefix), source_schema)
                      if path.startswith(prefix) else path for path in files)
        files += (prefix + "methods/__init__.py", prefix + "transports/__init__.py")
    return tuple(sorted(files))


def _method_extensions(config: dict) -> dict[str, bool]:
    """Select historical file sets from captured data, never a live factory.

    A new extension is an exact version marker, not permission to silently
    expand the older Responses/EEF inventories or execute captured source.
    """
    method = "control_method" in config
    feedback = "enforce_action_guard" in config
    persistent = "codex_direct_extension" in config
    context = "codex_direct_context_extension" in config
    native = "codex_native_extension" in config
    planned = "codex_planned_extension" in config
    if planned and (not context or not native or config["codex_planned_extension"] != "planned-native/v1"):
        raise ValueError("unsupported planned-native source extension")
    if native and (not method or config["codex_native_extension"] != "native-vectors/v1"):
        raise ValueError("unsupported native-vector source extension")
    if ((feedback and not method) or (persistent and (not feedback or not method))
            or (persistent and config["codex_direct_extension"] != "persistent-tools/v1")
            or (context and (not persistent or config["codex_direct_context_extension"] != "public-context/v2"))):
        raise ValueError("unsupported model source extension declaration")
    return {"method_extensions": method, "feedback_extensions": feedback,
            "persistent_extensions": persistent, "context_extensions": context, "native_extensions": native,
            "planned_extensions": planned}


def _read(root: Path, relative: str) -> bytes:
    """Read one allowlisted regular file through no-follow directory handles."""
    try:
        descriptor = _open_source_file(root, Path(relative))
        with os.fdopen(descriptor, "rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE_BYTES:
                raise ValueError(f"invalid or oversized model source: {relative}")
            payload = handle.read(MAX_FILE_BYTES + 1)
            if len(payload) > MAX_FILE_BYTES or _identity(os.fstat(handle.fileno())) != _identity(before):
                raise ValueError(f"model source changed while reading: {relative}")
        return payload
    except OSError as exc:
        raise ValueError(f"missing or unsafe model source: {relative}") from exc


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


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
    """Validate bounded declarative scalar fields; never execute captured model code."""
    if (not isinstance(schema, dict) or set(schema) - {"runtime_preflight"} != {
            "schema_version", "profile_id", "execution", "fields", "factory_parameters"}
            or ("runtime_preflight" in schema and schema["runtime_preflight"] is not True)
            or schema.get("schema_version") != _CONFIGURATION_SCHEMA
            or schema.get("profile_id") != profile_id or schema.get("execution") not in ("direct", "mailbox")):
        raise ValueError("invalid model configuration schema")
    fields = schema["fields"]
    parameters = schema["factory_parameters"]
    if (not isinstance(fields, dict) or not 1 <= len(fields) <= 64
            or not isinstance(config, dict) or set(config) != set(fields)
            or not isinstance(parameters, list) or any(not isinstance(key, str) for key in parameters)
            or len(parameters) != len(set(parameters)) or set(parameters) - _FACTORY_PARAMETERS):
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
    return {"execution": schema["execution"], "factory_parameters": tuple(parameters),
            **({"runtime_preflight": True} if "runtime_preflight" in schema else {})}


def _provider_sdk(value: Any) -> Any:
    if (not isinstance(value, dict) or set(value) != {"name", "version"}
            or not isinstance(value["name"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value["name"])
            or (value["version"] is not None and (not isinstance(value["version"], str)
                or not value["version"].strip() or len(value["version"]) > 128))):
        raise ValueError("invalid declared provider SDK dependency")
    return value


def _profile_data(profile_id: str, payloads: dict[str, bytes], *, require_configured: bool,
                  legacy: bool = False, source_schema: str = SOURCE_SCHEMA, method_extensions: bool = True,
                  feedback_extensions: bool = True, persistent_extensions: bool = True,
                  context_extensions: bool = True, native_extensions: bool = True,
                  planned_extensions: bool = True) -> dict[str, Any]:
    if legacy:
        source_schema = LEGACY_SOURCE_SCHEMA
    namespace = _source_namespace(source_schema)
    legacy = source_schema == LEGACY_SOURCE_SCHEMA
    factories = (_FACTORIES if source_schema in (SOURCE_SCHEMA, TOOLS_SOURCE_SCHEMA) else
                 _GROUPED_FACTORIES if source_schema == GROUPED_SOURCE_SCHEMA else
                 _FLAT_FACTORIES if namespace == "AgentPolicies" else _HISTORICAL_FACTORIES)
    prefix = f"{namespace}/{profile_id}/"
    profile = _json(payloads[prefix + "profile.json"])
    config_path = prefix + _profile_relative(profile_id, "config.json", source_schema)
    prompt_path = prefix + _profile_relative(profile_id, "prompt.txt", source_schema)
    config = _json(payloads[config_path])
    dependencies = _json(payloads[prefix + "dependencies.json"])
    if not isinstance(dependencies, dict):
        raise ValueError("model dependencies must be an object")
    schema_path = prefix + "configuration.schema.json"
    configuration = (_json(payloads[schema_path]) if schema_path in payloads else None)
    execution = {"execution": "mailbox", "factory_parameters": tuple(sorted(_FACTORY_PARAMETERS | {"directory"}))}
    if configuration is not None:
        execution = validate_configuration(profile_id, config, configuration)
    if (not isinstance(profile, dict) or profile.get("schema_version") != PROFILE_SCHEMA
            or profile.get("id") != profile_id or profile.get("factory") != factories[profile_id]
            or type(profile.get("configured")) is not bool
            or profile.get("display_name") != {"anonymous_code_agent": "Anonymous code agent",
                                               "gpt6_astra": "GPT6Astra", "opus": "Opus"}[profile_id]
            or set(profile) != {"schema_version", "id", "display_name", "configured", "factory", "policy"}):
        raise ValueError("invalid model profile identity or factory")
    if (not isinstance(config, dict) or config.get("schema_version") != "starvla-rsi.model-config/v1"
            or config.get("profile_id") != profile_id):
        raise ValueError("invalid model configuration identity")
    direct_method = "codex-direct/v3" if source_schema == SOURCE_SCHEMA else "codex-direct/v2"
    if source_schema in (SOURCE_SCHEMA, TOOLS_SOURCE_SCHEMA) and profile_id == "gpt6_astra" and (
            config.get("control_method") not in ("codex-native/v1", direct_method, "codex-planned/v1")
            or any(key in config for key in ("codex_direct_extension", "codex_direct_context_extension",
                                             "codex_native_extension", "codex_planned_extension"))):
        raise ValueError("versioned registry requires an active method without historical extension markers")
    if source_schema == SOURCE_SCHEMA and profile_id == "gpt6_astra" and "enforce_action_guard" in config:
        raise ValueError("v6 registry cannot declare the retired Dojo action guard")
    if dependencies != {
        "schema_version": "starvla-rsi.model-dependencies/v1",
        "files": list(_allowed_files(profile_id, source_schema=source_schema, method_extensions=method_extensions,
                                     feedback_extensions=feedback_extensions,
                                     persistent_extensions=persistent_extensions,
                                     context_extensions=context_extensions, native_extensions=native_extensions,
                                     planned_extensions=planned_extensions)),
        "evaluation_dependency": "harness_source/index.json",
        "provider_sdk": _provider_sdk(dependencies.get("provider_sdk")) if configuration is not None else None,
    }:
        raise ValueError("model dependency declaration must match the explicit source allowlist")
    if profile_id == "anonymous_code_agent":
        expected_policy = {"name": "code-agent-development", "kind": "external-code-agent",
                           "model": None, "provider": None}
        if (profile.get("configured") is not True or profile.get("policy") != expected_policy
                or set(config) != ({"schema_version", "profile_id", "transport", "history", "max_response_bytes"}
                                  | (set() if legacy else {"policy_stop_rule_version", "min_action_decisions_before_give_up"}))
                or config.get("transport") != "mailbox"
                or config.get("history") != "current_observation_only"
                or type(config.get("max_response_bytes")) is not int
                or not 0 < config["max_response_bytes"] <= 1048576):
            raise ValueError("invalid anonymous mailbox profile configuration")
        if not legacy:
            from AgentPolicies.policy_support.stop_rules import validate_minimum
            validate_minimum(config.get("min_action_decisions_before_give_up"))
            if config.get("policy_stop_rule_version") != "minimum-action-decisions/v2":
                raise ValueError("invalid model policy stopping-rule version")
    elif configuration is not None:
        policy = profile.get("policy")
        if (legacy or not profile["configured"] or execution["execution"] != "direct"
                or not isinstance(policy, dict) or set(policy) != {"name", "kind", "model", "provider"}
                or any(not isinstance(policy[key], str) or not policy[key].strip() for key in policy)
                or any(policy[key] != config.get(key) for key in ("provider", "model"))):
            raise ValueError("invalid configured direct policy identity")
        from AgentPolicies.policy_support.stop_rules import validate_minimum
        validate_minimum(config.get("min_action_decisions_before_give_up"))
        if config.get("policy_stop_rule_version") != "minimum-action-decisions/v2":
            raise ValueError("invalid model policy stopping-rule version")
    elif (set(config) != {"schema_version", "profile_id", "provider", "model", "status"}
          or config.get("status") != "unconfigured; user-facing label only"
          or profile["configured"] or profile.get("policy") is not None
          or config.get("provider") is not None or config.get("model") is not None):
        raise ValueError("named model scaffold has no verified provider integration")
    if require_configured and not profile["configured"]:
        raise UnconfiguredModelProfile(
            f"{profile_id} is unconfigured: its user-facing label has no verified provider/model ID or adapter")
    prompt = payloads[prompt_path].decode("utf-8")
    if not prompt.strip() or len(prompt) > 32768:
        raise ValueError("profile prompt must be nonempty and at most 32768 characters")
    rows = [{"path": path, "size_bytes": len(payload), "sha256": _sha(payload)}
            for path, payload in sorted(payloads.items())]
    identity = {"schema_version": PROFILE_SCHEMA, "id": profile_id, "factory": profile["factory"],
                "profile_sha256": _sha(payloads[prefix + "profile.json"]),
                "config_sha256": _sha(payloads[config_path]),
                "prompt_sha256": _sha(payloads[prompt_path]),
                "dependencies_sha256": _sha(payloads[prefix + "dependencies.json"]),
                "source_inventory_sha256": inventory_digest(rows)}
    return {"profile": profile, "config": config, "prompt": prompt, "identity": identity,
            "files": rows, "payloads": payloads, "configuration": configuration, **execution}


def load_profile(profile_id: str, *, repository: Path | None = None,
                 require_configured: bool = True) -> dict[str, Any]:
    root = Path(repository) if repository is not None else Path(__file__).absolute().parents[1]
    payloads = {relative: _read(root, relative) for relative in _allowed_files(profile_id)}
    if sum(map(len, payloads.values())) > MAX_TOTAL_BYTES:
        raise ValueError("model source exceeds total byte limit")
    return _profile_data(profile_id, payloads, require_configured=require_configured)


def validate_policy_parameters(data: dict[str, Any], parameters: dict[str, Any]) -> None:
    """Check factory overrides using captured declarations, without importing a model."""
    allowed = set(data["factory_parameters"])
    if set(parameters) - allowed:
        raise ValueError(f"unsupported profile policy parameters: {sorted(set(parameters) - allowed)}")
    if data["configuration"] is not None:
        effective = {**data["config"], **{key: value for key, value in parameters.items()
                                       if key != "prompt" and value is not None}}
        validate_configuration(data["profile"]["id"], effective, data["configuration"])


def create_policy(profile_id: str, **parameters):
    """Resolve one configured factory lazily and bind its exact source identity."""
    data = load_profile(profile_id)
    validate_policy_parameters(data, parameters)
    parameters.setdefault("prompt", data["prompt"])
    module_name, function_name = data["profile"]["factory"].split(":")
    module = importlib.import_module(module_name)
    expected = Path(__file__).absolute().parents[1] / (module_name.replace(".", "/") + ".py")
    if Path(module.__file__).absolute() != expected:
        raise ValueError("model factory was imported outside the selected package")
    policy = getattr(module, function_name)(config=data["config"], identity=data["profile"]["policy"], **parameters)
    policy.descriptor = replace(policy.descriptor, parameters={
        **policy.descriptor.parameters, "model_profile": data["identity"],
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


def capture_model_source(output: Path, profile_id: str, prompt: str, *,
                         repository: Path | None = None,
                         freeze: bool = True) -> tuple[dict[str, Any], dict[str, Any]]:
    """Copy only declared runtime bytes plus the exact combined campaign prompt."""
    data = load_profile(profile_id, repository=repository)
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 32768:
        raise ValueError("effective policy prompt must be nonempty and at most 32768 characters")
    payloads = {**data["payloads"], "campaign_prompt.txt": prompt.encode("utf-8")}
    destination = output / "model_source"
    destination.mkdir(exist_ok=False)
    rows = []
    for relative, payload in sorted(payloads.items()):
        target = destination / "files" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(payload)
        if freeze and relative.startswith("AgentPolicies/"):
            frozen = output / "frozen" / relative
            frozen.parent.mkdir(parents=True, exist_ok=True)
            if relative == "AgentPolicies/__init__.py" and frozen.exists():
                if _read(output / "frozen", relative) != payload:
                    raise ValueError("model and harness package initializers differ")
            else:
                with frozen.open("xb") as stream:
                    stream.write(payload)
        rows.append({"path": relative, "size_bytes": len(payload), "sha256": _sha(payload)})
    index = {"schema_version": SOURCE_SCHEMA, "profile": data["identity"], "files": rows,
             "file_count": len(rows), "total_bytes": sum(row["size_bytes"] for row in rows),
             "inventory_sha256": inventory_digest(rows),
             "scope": "explicit model factory/config/prompt/dependency bytes and combined campaign prompt"}
    atomic_write_json(destination / "index.json", index, overwrite=False)
    snapshot = {"schema_version": SOURCE_SCHEMA, "path": "model_source/index.json",
                "index_sha256": _sha((destination / "index.json").read_bytes()),
                "inventory_sha256": index["inventory_sha256"], "file_count": len(rows),
                "total_bytes": index["total_bytes"]}
    return data["identity"], snapshot


def _inventory(root: Path, *, skip_evaluation: bool = False) -> set[str]:
    """Check every frozen entry, including .txt, extensionless and hidden files."""
    files = set()
    directories = set()
    entries = 0
    for directory, folders, names in os.walk(root, followlinks=False):
        for name in folders + names:
            entries += 1
            if entries > 256:
                raise ValueError("model source inventory exceeds entry limit")
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                raise ValueError("symlink in model source inventory")
            if name in names:
                if not path.is_file():
                    raise ValueError("non-regular model source inventory entry")
                files.add(relative)
            elif not (skip_evaluation and relative == "evaluation"):
                directories.add(relative)
        if skip_evaluation and Path(directory) == root:
            folders[:] = [name for name in folders if name != "evaluation"]
    expected_directories = {parent.as_posix() for relative in files for parent in Path(relative).parents
                            if parent != Path(".")}
    if directories != expected_directories:
        raise ValueError("unexpected directory in model source inventory")
    return files


_AGENT_DRIVER_FILES = frozenset({"AgentPolicies/policy_support/runner.py", "AgentPolicies/gpt6_astra/run.py"})


def _captured_driver_paths(output: Path, reference: dict | None, *, source_schema: str) -> set[str]:
    """Verify exact shared driver bytes independently of the policy inventory.

    Older frozen bundles have no driver paths and retain their exact model
    allowlist. New evaluation-source snapshots may contain only these explicit
    agent-side drivers; an arbitrary neighboring model file is never exempted.
    """
    if reference is None:
        return set()
    if (not isinstance(reference, dict) or reference.get("path") != "harness_source/index.json"
            or reference.get("files_root") != "harness_source/files"):
        raise ValueError("unsupported driver source reference")
    payload = _read(output, "harness_source/index.json")
    if _sha(payload) != reference.get("index_sha256"):
        raise ValueError("driver source index changed")
    index = _json(payload)
    rows = index.get("files") if isinstance(index, dict) else None
    if (not isinstance(index, dict) or index.get("schema_version") != "starvla-rsi.harness-source/v2"
            or not isinstance(rows, list) or any(not isinstance(row, dict) or not isinstance(row.get("path"), str)
                                        for row in rows)
            or len({row["path"] for row in rows}) != len(rows)
            or inventory_digest(rows) != reference.get("inventory_sha256")):
        raise ValueError("driver source inventory changed")
    namespace = _source_namespace(source_schema)
    other_namespace = "starVLA" if namespace == "AgentPolicies" else "AgentPolicies"
    allowed = {path.replace("AgentPolicies/", namespace + "/", 1) for path in _AGENT_DRIVER_FILES}
    selected = set()
    for row in rows:
        relative = row["path"]
        if relative.startswith(other_namespace + "/"):
            raise ValueError("driver source namespace differs from model source schema")
        if relative not in allowed:
            continue
        source = _read(output / "harness_source/files", relative)
        if (type(row.get("size_bytes")) is not int or len(source) != row["size_bytes"]
                or _sha(source) != row.get("sha256") or _read(output / "frozen", relative) != source):
            raise ValueError("captured agent driver changed")
        selected.add(relative)
    return selected


def _verify_bundle(output: Path, identity: dict, snapshot: dict, *, freeze: bool,
                   driver_snapshot: dict | None = None) -> tuple[dict, bytes]:
    from benchkit.campaigns.workflow import _campaign_path

    if not isinstance(identity, dict) or not isinstance(snapshot, dict):
        raise ValueError("profile campaigns require an explicit model source bundle")
    profile_id = identity.get("id")
    schema = snapshot.get("schema_version")
    namespace = _source_namespace(schema)
    legacy = schema == LEGACY_SOURCE_SCHEMA
    if (snapshot.get("path") != "model_source/index.json"
            or set(snapshot) != {"schema_version", "path", "index_sha256", "inventory_sha256", "file_count", "total_bytes"}):
        raise ValueError("unsupported model source bundle")
    _campaign_path(output, "model_source/index.json")
    index_payload = _read(output, "model_source/index.json")
    if _sha(index_payload) != snapshot.get("index_sha256"):
        raise ValueError("model source index changed")
    index = _json(index_payload)
    if not isinstance(index, dict):
        raise ValueError("model source index must be an object")
    extensions = {"method_extensions": True, "feedback_extensions": True, "persistent_extensions": True,
                  "context_extensions": True}
    if profile_id == "gpt6_astra" and not legacy and schema not in (SOURCE_SCHEMA, TOOLS_SOURCE_SCHEMA):
        # Read as bounded data only; the authenticated index, file hashes and
        # complete inventory are checked below. Original Responses-only v2
        # bundles predate the selectable method and keep their exact allowlist.
        captured_config = _json(_read(output / "model_source/files", f"{namespace}/gpt6_astra/"
                                     + _profile_relative(profile_id, "config.json", schema)))
        if not isinstance(captured_config, dict):
            raise ValueError("model configuration must be an object")
        extensions = _method_extensions(captured_config)
    allowed = set(_allowed_files(profile_id, source_schema=schema, **extensions))
    rows = index.get("files")
    expected = allowed | {"campaign_prompt.txt"}
    if (index.get("schema_version") != schema or index.get("profile") != identity
            or set(index) != {"schema_version", "profile", "files", "file_count", "total_bytes", "inventory_sha256", "scope"}
            or not isinstance(rows, list) or len(rows) != len(expected)
            or any(not isinstance(row, dict) for row in rows)
            or any(not isinstance(row.get("path"), str) for row in rows)
            or {row.get("path") for row in rows} != expected
            or any(set(row) != {"path", "sha256", "size_bytes"}
                   or type(row.get("size_bytes")) is not int or not 0 <= row["size_bytes"] <= MAX_FILE_BYTES
                   for row in rows)):
        raise ValueError("model source index inventory or identity changed")
    if sum(row["size_bytes"] for row in rows) > MAX_TOTAL_BYTES:
        raise ValueError("model source bundle exceeds total byte limit")
    for key, value in (("inventory_sha256", inventory_digest(rows)), ("file_count", len(rows)),
                       ("total_bytes", sum(row["size_bytes"] for row in rows))):
        if (type(index.get(key)) is not type(value) or type(snapshot.get(key)) is not type(value)
                or index[key] != value or snapshot[key] != value):
            raise ValueError("model source inventory metadata changed")
    files_root = _campaign_path(output, "model_source/files", directory=True)
    if _inventory(files_root) != expected:
        raise ValueError("model source inventory changed")
    if freeze:
        package = _campaign_path(output, f"frozen/{namespace}", directory=True)
        other_namespace = "starVLA" if namespace == "AgentPolicies" else "AgentPolicies"
        other_package = output / "frozen" / other_namespace
        if other_package.exists() or other_package.is_symlink():
            raise ValueError("mixed frozen model source namespaces")
        driver_paths = set() if legacy else _captured_driver_paths(output, driver_snapshot, source_schema=schema)
        if _inventory(package, skip_evaluation=legacy) != {
                path.removeprefix(namespace + "/") for path in allowed | driver_paths}:
            raise ValueError("frozen model source inventory changed")
    payloads = {}
    prompt_payload = b""
    for row in rows:
        relative = row["path"]
        payload = _read(files_root, relative)
        if len(payload) != row["size_bytes"] or _sha(payload) != row["sha256"]:
            raise ValueError(f"model source changed: {relative}")
        if relative in allowed:
            if freeze and _read(output / "frozen", relative) != payload:
                raise ValueError(f"frozen model source changed: {relative}")
            payloads[relative] = payload
        else:
            prompt_payload = payload
    data = _profile_data(profile_id, payloads, require_configured=True, source_schema=schema, **extensions)
    if data["identity"] != identity:
        raise ValueError("model source identity changed")
    return data, prompt_payload


def verify_model_source(output: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Fail closed on campaign identity, declarations and all frozen siblings."""
    data, prompt = _verify_bundle(output, manifest.get("model_profile"), manifest.get("model_source"), freeze=True,
                                 driver_snapshot=manifest.get("harness_source"))
    if (data["profile"]["policy"] != manifest["policy"]
            or prompt != manifest["policy_prompt"].encode("utf-8")
            or _sha(manifest["policy_prompt"].encode("utf-8")) != manifest.get("policy_prompt_sha256")):
        raise ValueError("campaign model profile/configuration identity changed")
    return data


def capture_policy_source(run_dir: Path, policy) -> dict[str, Any]:
    """Capture standalone run dependencies before reset, bound to its descriptor."""
    identity = policy.descriptor.parameters["model_profile"]
    prompt = policy.prompt
    if not isinstance(prompt, str) or _sha(prompt.encode("utf-8")) != policy.descriptor.parameters["prompt_sha256"]:
        raise ValueError("effective model policy prompt changed before capture")
    captured, snapshot = capture_model_source(run_dir, identity["id"], prompt, freeze=False)
    if captured != identity:
        raise ValueError("model policy source changed after factory creation")
    verify_policy_source(run_dir, policy.descriptor.to_dict(), snapshot)
    return snapshot


def _direct_protocol_overrides(preset: dict, effective: dict, parameters: dict, data: dict) -> set[str]:
    """Bind a selected protocol to captured data, not a server or live factory.

    Historical Direct bundles without this declaration retain their original
    fixed required_protocol and three ordinary method overrides.
    """
    added = {"protocol_presets", "protocol_preset", "native_horizon"}
    if not (added.intersection(preset) or "protocol_preset" in parameters
            or "protocol_preset" in data["config"]):
        return set()
    table = preset.get("protocol_presets")
    rule = (data["configuration"] or {}).get("fields", {}).get("protocol_preset", {})
    if (not added.issubset(preset) or not isinstance(table, dict) or not 1 <= len(table) <= 8
            or not isinstance(rule, dict) or rule.get("type") != "string"
            or not isinstance(rule.get("enum"), list) or len(rule["enum"]) != len(table)
            or set(rule["enum"]) != set(table)
            or "protocol_preset" not in data["factory_parameters"]):
        raise ValueError("invalid captured Direct protocol preset declaration")
    for name, entry in table.items():
        if (not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", name)
                or not isinstance(entry, dict) or set(entry) != {"required_protocol", "native_horizon"}
                or not isinstance(entry["required_protocol"], str)
                or not re.fullmatch(r"[a-z0-9][a-z0-9._/-]{0,255}", entry["required_protocol"])
                or type(entry["native_horizon"]) is not int or not 1 <= entry["native_horizon"] <= 1000000):
            raise ValueError("invalid captured Direct protocol preset entry")
    default, selected = preset.get("protocol_preset"), parameters.get("protocol_preset")
    if (type(default) is not str or default not in table or data["config"].get("protocol_preset") != default
            or type(selected) is not str or selected not in table or effective.get("protocol_preset") != selected):
        raise ValueError("Direct protocol selector differs from captured declaration")
    for actual, expected in ((preset, table[default]), (effective, table[selected])):
        if any(type(actual.get(key)) is not type(value) or actual.get(key) != value
               for key, value in expected.items()):
            raise ValueError("Direct protocol/horizon differs from selected captured preset")
    return {"protocol_preset", "required_protocol", "native_horizon"}


def verify_policy_source(run_dir: Path, policy_descriptor: dict, snapshot: dict) -> None:
    """Verify a run's versioned bundle against its original policy descriptor."""
    identity = policy_descriptor.get("parameters", {}).get("model_profile")
    data, prompt = _verify_bundle(run_dir, identity, snapshot, freeze=False)
    if (any(policy_descriptor.get(key) != value for key, value in data["profile"]["policy"].items())
            or _sha(prompt) != policy_descriptor.get("parameters", {}).get("prompt_sha256")):
        raise ValueError("run policy identity or effective prompt differs from model source bundle")
    if snapshot.get("schema_version") in (PREVIOUS_SOURCE_SCHEMA, FLAT_AGENT_SOURCE_SCHEMA,
                                          GROUPED_SOURCE_SCHEMA, TOOLS_SOURCE_SCHEMA, SOURCE_SCHEMA):
        namespace = _source_namespace(snapshot["schema_version"])
        parameters = policy_descriptor.get("parameters", {})
        method = policy_descriptor.get("version")
        generic = snapshot["schema_version"] == SOURCE_SCHEMA and identity["id"] == "gpt6_astra"
        current = snapshot["schema_version"] in (SOURCE_SCHEMA, TOOLS_SOURCE_SCHEMA) and identity["id"] == "gpt6_astra"
        direct_method = "codex-direct/v3" if generic else "codex-direct/v2"
        if current and (method not in {"codex-native/v1", direct_method, "codex-planned/v1"}
                        or parameters.get("control_method") != method):
            raise ValueError("unsupported or mismatched versioned model method")
        if identity["id"] == "gpt6_astra" and (method == "codex-direct/v3"
                                               or parameters.get("control_method") == "codex-direct/v3"):
            if not generic or method != "codex-direct/v3" or parameters.get("control_method") != method:
                raise ValueError("Codex Direct v3 requires its v6 native-vector source layout")
            path = f"{namespace}/gpt6_astra/configs/codex_direct_v3_config.json"
            preset = _json(data["payloads"][path])
            effective = parameters.get("effective_config")
            overrides = {"timeout_s", "max_chunk_length", "image_max_edge"}
            # Only newly declared profiles permit this override. Historical v3
            # bundles keep their original mandatory enabled preset.
            stop_rule = (data["configuration"] or {}).get("fields", {}).get("safety_stop")
            if stop_rule is not None:
                if (stop_rule != {"type": "boolean"}
                        or "safety_stop" not in data["factory_parameters"]):
                    raise ValueError("invalid captured Direct safety-stop declaration")
                overrides.add("safety_stop")
            retired_fields = {"required_protocol", "protocol_presets", "protocol_preset", "native_horizon",
                              "enforce_action_guard", "effective_action_rules", "public_feedback_schema",
                              "workspace_context_version", "max_translation_per_decision_m",
                              "max_rotation_per_decision_rad", "quaternion_norm_tolerance"}
            declarations = {"ordinary_give_up": False,
                            "feedback_projection": "acknowledged_counters_and_actions_plus_declared_robot_state",
                            "initial_state_reference": "first_public_observation_not_action"}
            if stop_rule is None:
                declarations["safety_stop"] = True
            if (not isinstance(preset, dict) or not isinstance(effective, dict)
                    or set(effective) != set(preset) or not overrides <= set(effective)
                    or retired_fields.intersection(preset) or retired_fields.intersection(parameters)
                    or json.dumps({k: v for k, v in effective.items() if k not in overrides}, sort_keys=True, allow_nan=False)
                       != json.dumps({k: v for k, v in preset.items() if k not in overrides}, sort_keys=True, allow_nan=False)
                    or parameters.get("preset_sha256") != _sha(data["payloads"][path])
                    or preset.get("schema_version") != "starvla-rsi.codex-direct-config/v3"
                    or preset.get("control_method") != method
                    or parameters.get("transport") != "codex-app-server/v1"
                    or preset.get("transport") != "codex-app-server/v1"
                    or preset.get("history") != "persistent_same_episode_thread"
                    or preset.get("terminal_delivery") != "cancel_without_continuation"
                    or parameters.get("provider_calls", "missing") is not None
                    or parameters.get("automatic_crash_resume") is not False
                    or any(type(source.get(k)) is not type(v) or source.get(k) != v
                           for source in (preset, parameters) for k, v in declarations.items())
                    or any(preset.get(k) != policy_descriptor.get(k) for k in ("provider", "model"))
                    or type(effective["timeout_s"]) not in (int, float) or not 0 < effective["timeout_s"] <= 900
                    or type(effective["max_chunk_length"]) is not int or not 1 <= effective["max_chunk_length"] <= 32
                    or type(effective["image_max_edge"]) is not int or not 0 <= effective["image_max_edge"] <= 4096
                    or type(preset.get("safety_stop")) is not bool
                    or type(effective.get("safety_stop")) is not bool
                    or any(type(parameters.get(k)) is not type(effective[k]) or parameters[k] != effective[k]
                           for k in overrides)):
                raise ValueError("Codex Direct v3 differs from captured native-vector configuration")
            return
        if identity["id"] == "gpt6_astra" and (
                parameters.get("control_method") == "codex-planned/v1"
                or (isinstance(method, str) and method.startswith("codex-planned/"))):
            if method != "codex-planned/v1" or snapshot["schema_version"] not in (GROUPED_SOURCE_SCHEMA, TOOLS_SOURCE_SCHEMA, SOURCE_SCHEMA):
                raise ValueError("unsupported or mismatched Codex planned method version")
            path = f"{namespace}/gpt6_astra/configs/codex_planned_config.json"
            if (not current and not _method_extensions(data["config"])["planned_extensions"]) or path not in data["payloads"]:
                raise ValueError("Codex planned lacks captured source declaration")
            preset = _json(data["payloads"][path])
            effective = parameters.get("effective_config")
            overrides = {"timeout_s", "max_chunk_length", "image_max_edge"}
            if not isinstance(preset, dict):
                raise ValueError("invalid captured Codex planned preset")
            optional_stop = preset.get("schema_version") == "starvla-rsi.codex-planned-config/v2"
            if optional_stop:
                # The global field existed for Direct before Planned supported
                # it. Only Planned's new preset version grants this override.
                stop_rule = (data["configuration"] or {}).get("fields", {}).get("safety_stop")
                if stop_rule != {"type": "boolean"} or "safety_stop" not in data["factory_parameters"]:
                    raise ValueError("invalid captured Planned safety-stop declaration")
                overrides.add("safety_stop")
            elif (preset.get("safety_stop") is not True
                    or not isinstance(effective, dict) or effective.get("safety_stop") is not True
                    or parameters.get("safety_stop", True) is not True):
                raise ValueError("historical Codex planned safety stop must remain enabled")
            if (not isinstance(preset, dict) or not isinstance(effective, dict)
                    or set(effective) != set(preset) or not overrides <= set(effective)
                    or json.dumps({k: v for k, v in effective.items() if k not in overrides}, sort_keys=True, allow_nan=False)
                       != json.dumps({k: v for k, v in preset.items() if k not in overrides}, sort_keys=True, allow_nan=False)
                    or parameters.get("preset_sha256") != _sha(data["payloads"][path])
                    or parameters.get("control_method") != method
                    or preset.get("control_method") != method
                    or preset.get("schema_version") not in ("starvla-rsi.codex-planned-config/v1",
                                                            "starvla-rsi.codex-planned-config/v2")
                    or parameters.get("transport") != "codex-app-server/v1"
                    or preset.get("transport") != "codex-app-server/v1"
                    or preset.get("history") != "persistent_same_episode_thread_with_bounded_public_summary"
                    or preset.get("terminal_delivery") != "cancel_without_continuation"
                    or preset.get("ordinary_give_up") is not False
                    or parameters.get("ordinary_give_up") is not False
                    or any(preset.get(k) != policy_descriptor.get(k) for k in ("provider", "model"))
                    or type(effective["timeout_s"]) not in (int, float)
                    or not 0 < effective["timeout_s"] <= 900
                    or type(effective["max_chunk_length"]) is not int or not 1 <= effective["max_chunk_length"] <= 32
                    or type(effective["image_max_edge"]) is not int or not 0 <= effective["image_max_edge"] <= 4096
                    or type(preset.get("safety_stop")) is not bool
                    or type(effective.get("safety_stop")) is not bool
                    or any(type(parameters.get(k)) is not type(effective[k]) or parameters[k] != effective[k]
                           for k in overrides)):
                raise ValueError("Codex planned differs from captured configuration")
            return
        if identity["id"] == "gpt6_astra" and (
                parameters.get("control_method") == "codex-native/v1"
                or (isinstance(method, str) and method.startswith("codex-native/"))):
            if method != "codex-native/v1":
                raise ValueError("unsupported or mismatched Codex native method version")
        if identity["id"] == "gpt6_astra" and method == "codex-native/v1":
            path = f"{namespace}/gpt6_astra/" + _profile_relative("gpt6_astra", "codex_native_config.json",
                                                                  snapshot["schema_version"])
            if (not current and not _method_extensions(data["config"])["native_extensions"]) or path not in data["payloads"]:
                raise ValueError("Codex native lacks captured source declaration")
            preset = _json(data["payloads"][path])
            effective = parameters.get("effective_config")
            overrides = {"timeout_s", "max_chunk_length", "min_action_decisions_before_give_up"}
            if current and (
                    type(preset.get("max_attempts")) is not int or not 1 <= preset["max_attempts"] <= 10
                    or type(preset.get("retry_backoff_s")) not in (int, float)
                    or not math.isfinite(preset["retry_backoff_s"]) or not 0 <= preset["retry_backoff_s"] <= 10
                    or parameters.get("automatic_retry") != {
                        "scope": "same_policy_decision_before_action_submission",
                        "max_attempts": preset["max_attempts"], "retry_backoff_s": preset["retry_backoff_s"]}):
                raise ValueError("Codex native retry declaration differs from captured configuration")
            if (not isinstance(effective, dict) or set(effective) != set(preset)
                    or any(effective[k] != v for k, v in preset.items() if k not in overrides)
                    or parameters.get("preset_sha256") != _sha(data["payloads"][path])
                    or parameters.get("control_method") != method
                    or parameters.get("transport") != "codex-exec/v1"
                    or parameters.get("max_output_tokens") is not None
                    or parameters.get("invalid_action_handling") != "feedback"
                    or type(effective["timeout_s"]) not in (int, float) or not 0 < effective["timeout_s"] <= 900
                    or type(effective["max_chunk_length"]) is not int or not 1 <= effective["max_chunk_length"] <= 5
                    or any(type(parameters.get(k)) is not type(effective[k]) or parameters.get(k) != effective[k] for k in
                           ("timeout_s", "max_chunk_length", "history", "reasoning_effort"))
                    or parameters.get("policy_stop_rule", {}).get("min_action_decisions_before_give_up") !=
                       effective["min_action_decisions_before_give_up"]):
                raise ValueError("Codex native differs from captured configuration")
        if identity["id"] == "gpt6_astra" and (
                parameters.get("transport") == "codex-app-server/v1"
                or parameters.get("control_method") in ("codex-direct/v1", "codex-direct/v2")
                or (isinstance(method, str) and method.startswith("codex-direct/"))):
            if method not in ("codex-direct/v1", "codex-direct/v2"):
                raise ValueError("unsupported or mismatched Codex Direct method version")
        if identity["id"] == "gpt6_astra" and method in ("codex-eef/v1", "codex-eef/v2", "codex-direct/v1", "codex-direct/v2"):
            # Verify this captured model preset as data. Its safety-only stop
            # behavior must not be replaced by another method's give-up floor.
            persistent = method in ("codex-direct/v1", "codex-direct/v2")
            context_v2 = method == "codex-direct/v2"
            if context_v2 and not current and not _method_extensions(data["config"])["context_extensions"]:
                raise ValueError("Codex Direct v2 lacks declared public context source extension")
            if persistent and not current and not _method_extensions(data["config"])["persistent_extensions"]:
                raise ValueError("Codex Direct method has no declared persistent source extension")
            preset_name = {"codex-eef/v1": "codex_config.json",
                "codex-eef/v2": "codex_v2_config.json", "codex-direct/v1": "codex_direct_config.json",
                "codex-direct/v2": "codex_direct_v2_config.json"}[method]
            path = f"{namespace}/gpt6_astra/" + _profile_relative("gpt6_astra", preset_name,
                                                                  snapshot["schema_version"])
            if path not in data["payloads"]:
                raise ValueError("Codex method has no declared source extension")
            payload = data["payloads"][path]
            preset, effective = _json(payload), parameters.get("effective_config")
            overrides = {"timeout_s", "max_chunk_length"}
            if method in ("codex-eef/v2", "codex-direct/v1", "codex-direct/v2"):
                overrides.add("enforce_action_guard")
            if context_v2:
                overrides.add("image_max_edge")
                edge = effective.get("image_max_edge") if isinstance(effective, dict) else None
                if (type(edge) is not int or not 0 <= edge <= 4096
                        or type(parameters.get("image_max_edge")) is not int
                        or parameters["image_max_edge"] != edge
                        or any(type(parameters.get(key)) is not str or parameters[key] != effective.get(key)
                               for key in ("public_feedback_schema", "workspace_context_version"))):
                    raise ValueError("invalid declared Direct image preview size")
            if persistent and isinstance(preset, dict) and isinstance(effective, dict):
                overrides.update(_direct_protocol_overrides(preset, effective, parameters, data))
            if (not isinstance(preset, dict) or not isinstance(effective, dict) or set(effective) != set(preset)
                    or any(effective[key] != value for key, value in preset.items()
                           if key not in overrides)
                    or parameters.get("preset_sha256") != _sha(payload)
                    or parameters.get("ordinary_give_up") is not False
                    or parameters.get("control_method") != method
                    or preset.get("control_method") != method
                    or parameters.get("transport") != ("codex-app-server/v1" if persistent else "codex-exec/v1")
                    or type(effective["timeout_s"]) not in (int, float)
                    or not 0 < effective["timeout_s"] <= 900
                    or type(effective["max_chunk_length"]) is not int
                    or not 1 <= effective["max_chunk_length"] <= 5
                    or type(parameters.get("max_chunk_length")) is not int
                    or parameters.get("max_chunk_length") != effective["max_chunk_length"]
                    or type(parameters.get("timeout_s")) is not type(effective["timeout_s"])
                    or parameters.get("timeout_s") != effective["timeout_s"]):
                raise ValueError("Codex method preset differs from captured configuration")
            if method in ("codex-eef/v2", "codex-direct/v1", "codex-direct/v2") and (
                    type(effective.get("enforce_action_guard")) is not bool
                    or type(parameters.get("enforce_action_guard")) is not bool
                    or parameters["enforce_action_guard"] is not effective["enforce_action_guard"]):
                raise ValueError("Codex action guard must be a declared boolean")
            if persistent:
                # Versioned configuration and requested identity, not proof of
                # a model invocation, native execution, sandbox or token usage.
                if (json.dumps({key: effective[key] for key in preset if key not in overrides},
                               sort_keys=True, allow_nan=False) !=
                        json.dumps({key: value for key, value in preset.items() if key not in overrides},
                                   sort_keys=True, allow_nan=False)
                        or preset.get("schema_version") != ("starvla-rsi.codex-direct-config/v2" if context_v2
                                                            else "starvla-rsi.codex-direct-config/v1")
                        or preset.get("transport") != "codex-app-server/v1"
                        or preset.get("history") != "persistent_same_episode_thread"
                        or preset.get("terminal_delivery") != "cancel_without_continuation"
                        or preset.get("ordinary_give_up") is not False
                        or any(preset.get(key) != policy_descriptor.get(key) for key in ("model", "provider"))
                        or "effective_action_rules" in parameters):
                    raise ValueError("Codex Direct configuration or method declaration changed")
            if method == "codex-eef/v2":
                enabled = effective["enforce_action_guard"]
                # Validate this declaration as data, never by importing the model.
                rules = {
                    "schema_version": "starvla-rsi.codex-eef-action-rules/v2",
                    "mandatory_interface": {
                        "finite_numeric_components": True, "pose_length": 7,
                        "target_quaternion_order": "wxyz", "target_quaternion_norm_tolerance": 1e-5,
                        "measured_quaternion_norm_tolerance": 1e-4,
                        "opening_min": 0, "opening_max": 1, "declared_action_spec_bounds": True},
                    "model_guard": {
                        "enforce_action_guard": enabled, "binary_gripper_required": enabled,
                        "max_translation_per_decision_m": effective["max_translation_per_decision_m"] if enabled else None,
                        "max_rotation_per_decision_rad": effective["max_rotation_per_decision_rad"] if enabled else None},
                    "rejection": {
                        "invalid_target_controls_executed": 0, "automatic_in_act_retry": False,
                        "feedback_on_next_normal_call": True, "already_acknowledged_prefix_is_retained": True}}
                if json.dumps(parameters.get("effective_action_rules"), sort_keys=True) != json.dumps(rules, sort_keys=True):
                    raise ValueError("Codex action rules differ from captured configuration")
            return
        from AgentPolicies.policy_support.stop_rules import stop_constraint, validate_minimum, with_stop_rule_prompt
        rule = policy_descriptor.get("parameters", {}).get("policy_stop_rule", {})
        minimum = validate_minimum(rule.get("min_action_decisions_before_give_up"))
        if (rule != stop_constraint(minimum)
                or prompt.decode("utf-8") != with_stop_rule_prompt(prompt.decode("utf-8"), minimum)):
            raise ValueError("run policy stopping rule or effective prompt differs from declared model policy")
