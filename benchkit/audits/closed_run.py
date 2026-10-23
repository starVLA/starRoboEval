#!/usr/bin/env python3
"""Offline runner-record consistency audit; never imports or queries a simulator."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path


class AuditError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AuditError(message)


def unique_object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_constant(value: str) -> None:
    raise AuditError(f"nonfinite JSON constant: {value}")


def finite_float(value: str) -> float:
    number = float(value)
    require(math.isfinite(number), "nonfinite JSON number")
    return number


def decode(payload: str):
    return json.loads(payload, object_pairs_hook=unique_object,
                      parse_constant=reject_constant, parse_float=finite_float)


class ClosedFiles:
    def __init__(self, root: Path):
        self.root = root.resolve(strict=True)
        self.hashes: dict[str, str] = {}

    def path(self, relative: str) -> Path:
        path = Path(relative)
        require(not path.is_absolute() and ".." not in path.parts, "unsafe artifact path")
        target = self.root
        for part in path.parts:
            target = target / part
            require(not target.is_symlink(), f"symlink in artifact path: {relative}")
        require(target.resolve().is_relative_to(self.root) and target.is_file(),
                f"missing/outside artifact: {relative}")
        return target

    def raw(self, relative: str) -> bytes:
        path = self.path(relative)
        require(path.stat().st_size <= 64 * 1024 * 1024, "audit input exceeds 64 MiB")
        payload = path.read_bytes()
        self.hashes[relative] = hashlib.sha256(payload).hexdigest()
        return payload

    def json(self, relative: str):
        return decode(self.raw(relative).decode("utf-8"))

    def jsonl(self, relative: str) -> list:
        return [decode(line) for line in self.raw(relative).decode("utf-8").splitlines() if line]

    def verify_unchanged(self) -> None:
        for relative, digest in self.hashes.items():
            require(hashlib.sha256(self.path(relative).read_bytes()).hexdigest() == digest,
                    f"artifact changed during audit: {relative}")


def audit_source(files: ClosedFiles, manifest: dict) -> int:
    source = manifest["harness_source"]
    index = files.json(source["path"])
    require(files.hashes[source["path"]] == source["index_sha256"], "source index digest mismatch")
    rows = index["files"]
    paths = [row["path"] for row in rows]
    require(len(paths) == len(set(paths)) == index["file_count"] == source["file_count"],
            "source inventory count/identity mismatch")
    canonical = json.dumps(sorted(rows, key=lambda row: row["path"]), sort_keys=True,
                           separators=(",", ":"), ensure_ascii=False).encode()
    require(hashlib.sha256(canonical).hexdigest() == index["inventory_sha256"] == source["inventory_sha256"],
            "source inventory digest mismatch")
    total = 0
    for row in rows:
        relative = (Path(source["files_root"]) / row["path"]).as_posix()
        payload = files.raw(relative)
        require(len(payload) == row["size_bytes"] and files.hashes[relative] == row["sha256"],
                f"copied source mismatch: {row['path']}")
        total += len(payload)
    require(total == index["total_bytes"] == source["total_bytes"], "source byte total mismatch")
    root = files.root / source["files_root"]
    actual = set()
    for path in root.rglob("*"):
        require(not path.is_symlink(), "symlink in copied source inventory")
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    require(actual == set(paths), "extra/missing file in copied source inventory")
    return len(rows)


def counter(value, label: str) -> int:
    require(type(value) is int and value >= 0, f"invalid {label} counter")
    return value


def audit_configuration(config: dict, schema: dict, profile_id: str) -> None:
    """Independently validate captured scalar declarations, never captured code.

    Keep this stdlib-only: historical reports can load this auditor as a standalone
    file without importing the current harness or a frozen model implementation.
    """
    require(isinstance(schema, dict) and set(schema) - {"runtime_preflight"} == {
        "schema_version", "profile_id", "execution", "fields", "factory_parameters"}
        and ("runtime_preflight" not in schema or schema["runtime_preflight"] is True)
        and schema.get("schema_version") == "starvla-rsi.configuration-schema/v1"
        and schema.get("profile_id") == profile_id and schema.get("execution") == "direct",
        "invalid direct configuration schema")
    fields, parameters = schema["fields"], schema["factory_parameters"]
    require(isinstance(fields, dict) and 1 <= len(fields) <= 64 and isinstance(config, dict)
            and set(config) == set(fields) and isinstance(parameters, list)
            and all(isinstance(key, str) for key in parameters) and len(parameters) == len(set(parameters))
            and not set(parameters) - {"prompt", "timeout_s", "max_chunk_length",
                                       "min_action_decisions_before_give_up", "control_method",
                                       "enforce_action_guard", "protocol_preset", "image_max_edge", "safety_stop",
                                       "stagnation_review", "stagnation_window", "allow_task_completion"},
            "invalid direct configuration fields or factory parameters")
    forbidden = {"api_key", "apikey", "authorization", "credentials", "credential", "secret", "client_secret",
                 "password", "token", "api_token", "access_token", "refresh_token", "bearer_token"}

    def scalar(value, kind):
        if kind == "number":
            return type(value) is int or (type(value) is float and math.isfinite(value))
        return type(value) is {"string": str, "integer": int, "boolean": bool, "null": type(None)}.get(kind)

    for key, rule in fields.items():
        require(isinstance(key, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key)
                and key not in forbidden
                and not any(key.endswith("_" + name) for name in ("api_key", "token", "secret", "password", "credentials"))
                and isinstance(rule, dict)
                and not set(rule) - {"type", "const", "enum", "minimum", "maximum"}
                and isinstance(rule.get("type"), str)
                and rule["type"] in {"string", "integer", "number", "boolean", "null"},
                "unsafe or unsupported direct configuration field schema")
        kind, value = rule["type"], config[key]
        require(scalar(value, kind), "direct configuration type mismatch")
        if "const" in rule:
            require(scalar(rule["const"], kind) and value == rule["const"], "direct configuration constant mismatch")
        if "enum" in rule:
            choices = rule["enum"]
            require(isinstance(choices, list) and 1 <= len(choices) <= 32
                    and all(scalar(choice, kind) for choice in choices) and value in choices,
                    "direct configuration choice mismatch")
        for bound in ("minimum", "maximum"):
            if bound in rule:
                require(kind in {"number", "integer"} and scalar(rule[bound], "number"),
                        "invalid direct configuration bound")
                require(value >= rule[bound] if bound == "minimum" else value <= rule[bound],
                        "direct configuration exceeds declared bounds")
    require(not set(parameters) - {"prompt"} - set(fields), "direct factory parameter has no declared field")


def audit_direct_protocol(preset: dict, effective: dict, parameters: dict, config: dict, schema: dict) -> set:
    """Independently bind the optional selector to the frozen model's table."""
    added = {"protocol_presets", "protocol_preset", "native_horizon"}
    if not (added.intersection(preset) or "protocol_preset" in parameters or "protocol_preset" in config):
        return set()
    table = preset.get("protocol_presets")
    rule = schema.get("fields", {}).get("protocol_preset", {})
    require(added.issubset(preset) and isinstance(table, dict) and 1 <= len(table) <= 8
            and isinstance(rule, dict) and rule.get("type") == "string"
            and isinstance(rule.get("enum"), list) and len(rule["enum"]) == len(table)
            and set(rule["enum"]) == set(table) and "protocol_preset" in schema["factory_parameters"],
            "invalid captured Direct protocol declaration")
    for name, entry in table.items():
        require(isinstance(name, str) and re.fullmatch(r"[a-z][a-z0-9-]{0,63}", name)
                and isinstance(entry, dict) and set(entry) == {"required_protocol", "native_horizon"}
                and isinstance(entry["required_protocol"], str)
                and re.fullmatch(r"[a-z0-9][a-z0-9._/-]{0,255}", entry["required_protocol"])
                and type(entry["native_horizon"]) is int and 1 <= entry["native_horizon"] <= 1000000,
                "invalid captured Direct protocol entry")
    default, selected = preset.get("protocol_preset"), parameters.get("protocol_preset")
    require(type(default) is str and default in table and config.get("protocol_preset") == default
            and type(selected) is str and selected in table and effective.get("protocol_preset") == selected,
            "Direct protocol selector differs from captured declaration")
    for actual, expected in ((preset, table[default]), (effective, table[selected])):
        require(all(type(actual.get(key)) is type(value) and actual.get(key) == value
                    for key, value in expected.items()),
                "Direct protocol/horizon differs from selected captured preset")
    return {"protocol_preset", "required_protocol", "native_horizon"}


def audit_model_source(files: ClosedFiles, manifest: dict) -> int:
    """Check declared model bytes as data, without importing a model factory."""
    selected_policy = manifest.get("policy", {})
    selected_parameters = selected_policy.get("parameters", {})
    identity = selected_parameters.get("model_profile")
    snapshot = manifest.get("model_source")
    selected_method = selected_policy.get("version")
    if ((isinstance(selected_method, str) and selected_method.startswith("codex-direct/"))
            or selected_parameters.get("control_method") in ("codex-direct/v1", "codex-direct/v2", "codex-direct/v3", "codex-direct/v4")
            or selected_parameters.get("transport") == "codex-app-server/v1"):
        require(isinstance(identity, dict) and isinstance(snapshot, dict),
                "Codex Direct requires an explicit bound model source bundle")
    if ((isinstance(selected_method, str) and selected_method.startswith("codex-native/"))
            or selected_parameters.get("control_method") in ("codex-native/v1", "codex-native/v2")):
        require(isinstance(identity, dict) and isinstance(snapshot, dict),
                "Codex native requires an explicit bound model source bundle")
    if ((isinstance(selected_method, str) and selected_method.startswith("codex-planned/"))
            or selected_parameters.get("control_method") == "codex-planned/v1"):
        require(isinstance(identity, dict) and isinstance(snapshot, dict),
                "Codex planned requires an explicit bound model source bundle")
    if identity is None and snapshot is None:
        require(not (files.root / "model_source").exists(), "unbound model source directory")
        return 0
    require(isinstance(identity, dict) and isinstance(snapshot, dict), "incomplete model source identity")
    profile_id = identity.get("id")
    require(isinstance(profile_id, str) and re.fullmatch(r"[a-z][a-z0-9_]*", profile_id),
            "unsafe model profile ID")
    # Namespace changes require a new source schema, not rewriting frozen bytes
    # or accepting interchangeable directory/factory aliases in an old bundle.
    namespaces = {"starvla-rsi.model-source/v1": "starVLA",
                  "starvla-rsi.model-source/v2": "starVLA",
                  "starvla-rsi.model-source/v3": "AgentPolicies",
                  "starvla-rsi.model-source/v4": "AgentPolicies",
                  "starvla-rsi.model-source/v5": "AgentPolicies",
                  "starvla-rsi.model-source/v6": "AgentPolicies",
                  "starvla-rsi.model-source/v7": "AgentPolicies",
                  "starvla-rsi.model-source/v8": "AgentPolicies"}
    require(isinstance(snapshot.get("schema_version"), str) and snapshot["schema_version"] in namespaces
            and snapshot.get("path") == "model_source/index.json", "unknown model source schema/path")
    namespace = namespaces[snapshot["schema_version"]]
    grouped = snapshot["schema_version"] == "starvla-rsi.model-source/v4" and profile_id == "gpt6_astra"
    relocated_support = snapshot["schema_version"] == "starvla-rsi.model-source/v8"
    flat_native = relocated_support and profile_id == "gpt6_astra"
    review = snapshot["schema_version"] == "starvla-rsi.model-source/v7" and profile_id == "gpt6_astra"
    generic = snapshot["schema_version"] in ("starvla-rsi.model-source/v6", "starvla-rsi.model-source/v7") and profile_id == "gpt6_astra"
    current = snapshot["schema_version"] in ("starvla-rsi.model-source/v5", "starvla-rsi.model-source/v6", "starvla-rsi.model-source/v7") and profile_id == "gpt6_astra"
    # Independent v5 inventory: never import a producer allowlist or captured Python.
    current_names = (
        "__init__.py", "profile.json", "configuration.schema.json", "dependencies.json",
        "configs/config.json", "configs/codex_native_config.json",
        "configs/codex_direct_v2_config.json", "configs/codex_planned_config.json",
        "prompts/codex_native_prompt.txt", "prompts/codex_direct_v2_prompt.txt",
        "prompts/codex_planned_prompt.txt", "methods/__init__.py", "methods/codex_native.py",
        "methods/codex_direct.py", "methods/codex_planned.py", "transports/__init__.py",
        "transports/codex_cli.py", "transports/codex_app_server.py", "tools/__init__.py",
        "tools/factory.py", "tools/native_io.py", "tools/json_io.py", "tools/eef_contract.py",
        "tools/runtime_preflight.py", "tools/direct_public_context.py",
    )
    if generic:
        current_names = (
            "__init__.py", "profile.json", "configuration.schema.json", "dependencies.json",
            "configs/config.json", "configs/codex_native_config.json",
            "configs/codex_direct_v3_config.json", "configs/codex_planned_config.json",
            "prompts/codex_native_prompt.txt", "prompts/codex_direct_v3_prompt.txt",
            "prompts/codex_planned_prompt.txt", "methods/__init__.py", "methods/codex_native.py",
            "methods/codex_direct.py", "methods/codex_planned.py", "transports/__init__.py",
            "transports/codex_cli.py", "transports/codex_app_server.py", "tools/__init__.py",
            "tools/factory.py", "tools/native_io.py", "tools/json_io.py", "tools/persistent_runtime.py",
            "tools/runtime_preflight.py", "tools/public_observation.py",
        )
    if review:
        current_names += ("configs/codex_direct_v4_config.json", "prompts/codex_direct_v4_prompt.txt",
                          "tools/stagnation_review.py")

    if flat_native:
        current_names = (
            "__init__.py", "configs/profile.json", "configs/configuration.schema.json", "configs/dependencies.json",
            "codex_native.py", "configs/codex_native_config.json", "configs/codex_native_prompt.txt",
            "tools/__init__.py", "tools/persistent_runtime.py", "tools/public_observation.py", "tools/json_io.py",
            "tools/codex_app_server.py", "tools/codex_runtime.py", "tools/stagnation_review.py",
        )

    def relative(name):
        # Independently declared layouts, never import captured model code.
        if flat_native:
            name = {"config.json": "codex_native_config.json", "prompt.txt": "codex_native_prompt.txt"}.get(name, name)
            if name in {"profile.json", "configuration.schema.json", "dependencies.json",
                        "codex_native_config.json", "codex_native_prompt.txt"}:
                return "configs/" + name
            return name
        if current:
            if name == "prompt.txt":
                return "prompts/codex_native_prompt.txt"
            return next((path for path in current_names if path.rsplit("/", 1)[-1] == name), name)
        if not grouped:
            return name
        groups = {
            "methods": {"policy.py", "codex_policy.py", "codex_direct.py", "codex_native.py", "codex_planned.py",
                        "action_validation.py", "direct_public_context.py"},
            "transports": {"responses.py", "codex_cli.py", "codex_app_server.py"},
            "configs": {"config.json", "codex_config.json", "codex_v2_config.json",
                        "codex_direct_config.json", "codex_direct_v2_config.json", "codex_native_config.json", "codex_planned_config.json"},
            "prompts": {"prompt.txt", "codex_prompt.txt", "codex_v2_prompt.txt",
                        "codex_direct_prompt.txt", "codex_direct_v2_prompt.txt", "codex_native_prompt.txt", "codex_planned_prompt.txt"},
        }
        return next((directory + "/" + name for directory, names in groups.items() if name in names), name)
    require(set(snapshot) == {"schema_version", "path", "index_sha256", "inventory_sha256",
                             "file_count", "total_bytes"}, "unknown model snapshot fields")
    require(set(identity) == {"schema_version", "id", "factory", "profile_sha256", "config_sha256",
                             "prompt_sha256", "dependencies_sha256", "source_inventory_sha256"}
            and identity["schema_version"] == "starvla-rsi.model-profile/v1", "invalid model identity")
    count = audit_source(files, {"harness_source": {**snapshot, "files_root": "model_source/files"}})
    index = files.json("model_source/index.json")
    require(index.get("schema_version") == snapshot["schema_version"] and index.get("profile") == identity,
            "model bundle/descriptor identity mismatch")
    require(set(index) == {"schema_version", "profile", "files", "file_count", "total_bytes",
                          "inventory_sha256", "scope"}, "unknown model index fields")
    require(type(index["file_count"]) is int and type(index["total_bytes"]) is int
            and type(snapshot["file_count"]) is int and type(snapshot["total_bytes"]) is int
            and 0 < index["file_count"] <= 64 and 0 < index["total_bytes"] <= 1024 * 1024,
            "invalid model inventory bounds")
    for row in index["files"]:
        require(set(row) == {"path", "size_bytes", "sha256"}
                and type(row["size_bytes"]) is int and 0 <= row["size_bytes"] <= 256 * 1024,
                "invalid model source row")
    source_rows = [row for row in index["files"] if row["path"] != "campaign_prompt.txt"]
    source_bytes = json.dumps(sorted(source_rows, key=lambda row: row["path"]), sort_keys=True,
                              separators=(",", ":"), ensure_ascii=False).encode()
    require(hashlib.sha256(source_bytes).hexdigest() == identity["source_inventory_sha256"],
            "model source identity inventory mismatch")
    prefix = f"model_source/files/{namespace}/{profile_id}/"
    profile = files.json(prefix + relative("profile.json"))
    config = files.json(prefix + relative("config.json"))
    dependencies = files.json(prefix + relative("dependencies.json"))
    legacy = snapshot["schema_version"] == "starvla-rsi.model-source/v1"
    direct = profile_id == "gpt6_astra" and not legacy
    if direct:
        require(isinstance(profile, dict) and set(profile) == {
            "schema_version", "id", "display_name", "configured", "factory", "policy"}
            and profile.get("schema_version") == "starvla-rsi.model-profile/v1"
            and profile.get("display_name") == "GPT6Astra"
            and profile.get("factory") == f"{namespace}.gpt6_astra." +
                ("codex_native:create_policy" if flat_native else
                 "tools.factory:create_policy" if current else
                 "methods.policy:create_policy" if grouped else "policy:create_policy"),
            "invalid direct model profile semantics")
        configuration = files.json(prefix + relative("configuration.schema.json"))
        audit_configuration(config, configuration, profile_id)
        policy = profile.get("policy")
        require(config.get("schema_version") == "starvla-rsi.model-config/v1"
                and config.get("profile_id") == profile_id and isinstance(policy, dict)
                and set(policy) == {"name", "kind", "model", "provider"}
                and all(isinstance(value, str) and value.strip() for value in policy.values())
                and all(policy[key] == config.get(key) for key in ("provider", "model")),
                "invalid direct model configuration identity")
    else:
        # Retain the independently reviewed historical anonymous schema.
        require(profile_id == "anonymous_code_agent", "model profile has no reviewed executable audit schema")
        require(set(profile) == {"schema_version", "id", "display_name", "configured", "factory", "policy"}
                and profile.get("schema_version") == "starvla-rsi.model-profile/v1"
                and profile.get("display_name") == "Anonymous code agent"
                and profile.get("factory") == f"{namespace}.anonymous_code_agent.policy:create_policy"
                and profile.get("policy") == {"name": "code-agent-development", "kind": "external-code-agent",
                                              "model": None, "provider": None}, "invalid model profile semantics")
        require(set(config) == ({"schema_version", "profile_id", "transport", "history", "max_response_bytes"}
                                | (set() if legacy else {"policy_stop_rule_version", "min_action_decisions_before_give_up"}))
                and config.get("schema_version") == "starvla-rsi.model-config/v1"
                and config.get("profile_id") == profile_id and config.get("transport") == "mailbox"
                and config.get("history") == "current_observation_only"
                and type(config.get("max_response_bytes")) is int
                and 0 < config["max_response_bytes"] <= 1048576, "invalid model config semantics")
    if not legacy:
        require(config.get("policy_stop_rule_version") == "minimum-action-decisions/v2"
                and type(config.get("min_action_decisions_before_give_up")) is int
                and config["min_action_decisions_before_give_up"] >= 0, "invalid policy stopping configuration")
    require(profile.get("id") == profile_id and profile.get("factory") == identity.get("factory")
            and profile.get("configured") is True and isinstance(profile.get("policy"), dict),
            "unconfigured or mismatched model profile")
    require(all(manifest["policy"].get(key) == value for key, value in profile["policy"].items()),
            "run policy differs from captured model identity")
    require(dependencies.get("schema_version") == "starvla-rsi.model-dependencies/v1"
            and isinstance(dependencies.get("files"), list), "invalid model dependencies")
    # Independent versioned inventory; package markers do not import Codex code.
    common_files = ([f"{namespace}/__init__.py", f"{namespace}/gpt6_astra/__init__.py",
                     f"{namespace}/gpt6_astra/tools/__init__.py", f"{namespace}/gpt6_astra/tools/stop_rules.py"]
                    if relocated_support else
                    [f"{namespace}/__init__.py", f"{namespace}/policy_support/__init__.py",
                     f"{namespace}/policy_support/stop_rules.py"])
    allowed = sorted((["starVLA/__init__.py", "starVLA/model_profiles.py", "starVLA/providers/__init__.py",
                       "starVLA/providers/mailbox.py"] if legacy else
                      common_files + [f"{namespace}/anonymous_code_agent/mailbox.py",
                       f"{namespace}/anonymous_code_agent/prompts/control_guidance.txt",
                       f"{namespace}/anonymous_code_agent/prompts/actor_instructions.txt",
                       f"{namespace}/anonymous_code_agent/prompts/simpler_development.txt"]) + [f"{namespace}/{profile_id}/{name}" for name in
                      ("__init__.py", "profile.json", "config.json", "prompt.txt", "dependencies.json", "policy.py")])
    provider_sdk = None
    if direct:
        allowed = sorted(common_files + [f"{namespace}/{profile_id}/{name}" for name in
                         ("__init__.py", "profile.json", "config.json", "prompt.txt", "dependencies.json", "policy.py",
                          "responses.py", "configuration.schema.json")])
        method = manifest["policy"].get("version")
        parameters = manifest["policy"]["parameters"]
        if flat_native:
            require(method == "codex-native/v2" and parameters.get("control_method") == method
                    and config.get("control_method") == method
                    and config.get("transport") == "codex-app-server/v1"
                    and type(config.get("min_action_decisions_before_give_up")) is int
                    and config["min_action_decisions_before_give_up"] == 0
                    and not any(key in config for key in ("codex_direct_extension", "codex_direct_context_extension",
                                                          "codex_native_extension", "codex_planned_extension", "enforce_action_guard")),
                    "v8 source requires its single persistent Codex native v2 method")
        if current:
            direct_methods = {"codex-direct/v3", "codex-direct/v4"} if review else {"codex-direct/v3"} if generic else {"codex-direct/v2"}
            require(method in {"codex-native/v1", *direct_methods, "codex-planned/v1"}
                    and parameters.get("control_method") == method,
                    "unsupported or mismatched versioned model method")
            require(method == "codex-direct/v4" or not {"stagnation_review", "stagnation_window", "allow_task_completion"}.intersection(parameters),
                    "completion and stagnation-review parameters require Direct v4")
            require(config.get("control_method") in {"codex-native/v1", *direct_methods, "codex-planned/v1"}
                    and not any(key in config for key in ("codex_direct_extension", "codex_direct_context_extension",
                                                          "codex_native_extension", "codex_planned_extension")),
                    "versioned registry requires an active method without historical extension markers")
            require(not generic or "enforce_action_guard" not in config,
                    "native-vector registry cannot declare the retired Dojo action guard")
        persistent_methods = current or "codex_direct_extension" in config
        context_methods = current or "codex_direct_context_extension" in config
        native_methods = current or "codex_native_extension" in config
        planned_methods = current or "codex_planned_extension" in config
        require(current or not planned_methods or (grouped and native_methods and context_methods
                and config["codex_planned_extension"] == "planned-native/v1"),
                "unsupported planned-native source extension declaration")
        if (parameters.get("control_method") == "codex-planned/v1"
                or (isinstance(method, str) and method.startswith("codex-planned/"))):
            require(method == "codex-planned/v1" and planned_methods,
                    "unsupported or undeclared Codex planned method version")
        require(current or not native_methods or ("control_method" in config
                and config["codex_native_extension"] == "native-vectors/v1"),
                "unsupported native-vector source extension declaration")
        if (parameters.get("control_method") == "codex-native/v1"
                or (isinstance(method, str) and method.startswith("codex-native/"))) and not flat_native:
            require(method == "codex-native/v1" and native_methods,
                    "unsupported or undeclared Codex native method version")
        require(current or not context_methods or (persistent_methods
                and config["codex_direct_context_extension"] == "public-context/v2"),
                "unsupported public context source extension declaration")
        require(current or not persistent_methods or (config["codex_direct_extension"] == "persistent-tools/v1"
                and "control_method" in config and "enforce_action_guard" in config),
                "unsupported persistent model source extension declaration")
        require("enforce_action_guard" not in config or "control_method" in config,
                "feedback model source extension lacks method declaration")
        if method in ("codex-direct/v3", "codex-direct/v4") or parameters.get("control_method") in ("codex-direct/v3", "codex-direct/v4"):
            require(generic and method in ("codex-direct/v3", "codex-direct/v4")
                    and (method != "codex-direct/v4" or review) and parameters.get("control_method") == method,
                    "Codex Direct requires its versioned native-vector source layout")
        if ((parameters.get("transport") == "codex-app-server/v1" and method not in ("codex-planned/v1", "codex-direct/v3", "codex-direct/v4", "codex-native/v2"))
                or parameters.get("control_method") in ("codex-direct/v1", "codex-direct/v2")
                or (isinstance(method, str) and method.startswith("codex-direct/") and method not in ("codex-direct/v3", "codex-direct/v4"))):
            require(method in ("codex-direct/v1", "codex-direct/v2") and persistent_methods
                    and (method != "codex-direct/v2" or context_methods),
                    "unsupported or undeclared Codex Direct method version")
        # Old v2 bundles remain independently auditable with their old exact
        # allowlist. New selectable-method bundles declare their extra bytes.
        if "control_method" in config:
            if native_methods:
                allowed = sorted(allowed + [f"{namespace}/{profile_id}/{name}" for name in (
                    "codex_native.py", "codex_native_config.json", "codex_native_prompt.txt")])
            allowed = sorted(allowed + [f"{namespace}/{profile_id}/{name}" for name in (
                "codex_cli.py", "codex_policy.py", "codex_config.json", "codex_prompt.txt")])
            feedback_methods = "enforce_action_guard" in config
            if feedback_methods:
                allowed = sorted(allowed + [f"{namespace}/{profile_id}/{name}" for name in (
                    "action_validation.py", "codex_v2_config.json", "codex_v2_prompt.txt")])
                if persistent_methods:
                    allowed = sorted(allowed + [f"{namespace}/{profile_id}/{name}" for name in (
                        "codex_direct.py", "codex_direct_config.json", "codex_direct_prompt.txt",
                        "codex_app_server.py")])
                    if context_methods:
                        allowed = sorted(allowed + [f"{namespace}/{profile_id}/{name}" for name in (
                            "codex_direct_v2_config.json", "codex_direct_v2_prompt.txt", "direct_public_context.py")])
                        if planned_methods:
                            allowed = sorted(allowed + [f"{namespace}/{profile_id}/{name}" for name in (
                                "codex_planned.py", "codex_planned_config.json", "codex_planned_prompt.txt")])
            if flat_native or method in ("codex-direct/v3", "codex-direct/v4"):
                version = method.rsplit("/", 1)[-1]
                preset_path = prefix + relative("codex_native_config.json" if flat_native else f"codex_direct_{version}_config.json")
                preset = files.json(preset_path)
                effective = parameters.get("effective_config")
                overrides = {"timeout_s", "max_chunk_length", "image_max_edge"}
                # Optional stops are an explicit captured policy capability;
                # historical bundles retain their enabled, non-overridable rule.
                stop_rule = configuration.get("fields", {}).get("safety_stop")
                if stop_rule is not None:
                    require(stop_rule == {"type": "boolean"}
                            and "safety_stop" in configuration["factory_parameters"],
                            "invalid captured Direct safety-stop declaration")
                    overrides.add("safety_stop")
                if flat_native or method == "codex-direct/v4":
                    review_fields = {"stagnation_review": {"type": "boolean"},
                                     "stagnation_window": {"type": "integer", "minimum": 2, "maximum": 32}}
                    require(all(configuration.get("fields", {}).get(key) == rule
                                and key in configuration["factory_parameters"] for key, rule in review_fields.items()),
                            "invalid captured Direct stagnation-review declaration")
                    overrides.update(review_fields)
                    require(isinstance(preset, dict) and isinstance(effective, dict)
                            and all(type(source.get("stagnation_review")) is bool
                                    and type(source.get("stagnation_window")) is int
                                    and 2 <= source["stagnation_window"] <= 32 for source in (preset, effective)),
                            "invalid captured Direct stagnation-review configuration")
                    # Historical v7 captures without the preset flag retain
                    # their original non-completion policy; do not infer it.
                    if "allow_task_completion" in preset:
                        require(configuration.get("fields", {}).get("allow_task_completion") == {"type": "boolean"}
                                and "allow_task_completion" in configuration["factory_parameters"]
                                and all(type(source.get("allow_task_completion")) is bool for source in (preset, effective)),
                                "invalid captured Direct task-completion declaration")
                        overrides.add("allow_task_completion")
                    else:
                        require("allow_task_completion" not in parameters and "allow_task_completion" not in effective,
                                "historical Direct preset does not declare task completion")
                retired_fields = {"required_protocol", "protocol_presets", "protocol_preset", "native_horizon",
                                  "enforce_action_guard", "effective_action_rules", "public_feedback_schema",
                                  "workspace_context_version", "max_translation_per_decision_m",
                                  "max_rotation_per_decision_rad", "quaternion_norm_tolerance"}
                declarations = {"ordinary_give_up": False,
                                "feedback_projection": "acknowledged_counters_and_actions_plus_declared_robot_state",
                                "initial_state_reference": "first_public_observation_not_action"}
                if stop_rule is None:
                    declarations["safety_stop"] = True
                require(isinstance(preset, dict) and isinstance(effective, dict)
                        and set(preset) == set(effective) and overrides <= set(effective)
                        and not retired_fields.intersection(preset) and not retired_fields.intersection(parameters)
                        and json.dumps({k: v for k, v in effective.items() if k not in overrides}, sort_keys=True, allow_nan=False)
                            == json.dumps({k: v for k, v in preset.items() if k not in overrides}, sort_keys=True, allow_nan=False),
                        "Codex Direct effective preset differs outside native-vector overrides")
                require(files.hashes[preset_path] == parameters.get("preset_sha256")
                        and preset.get("schema_version") == ("starvla-rsi.model-config/v1" if flat_native
                                                              else f"starvla-rsi.codex-direct-config/{version}")
                        and (not flat_native or (preset.get("profile_id") == "gpt6_astra" and stop_rule is not None
                            and preset.get("policy_stop_rule_version") == "minimum-action-decisions/v2"
                            and type(preset.get("min_action_decisions_before_give_up")) is int
                            and preset["min_action_decisions_before_give_up"] == 0))
                        and preset.get("control_method") == method
                        and parameters.get("transport") == "codex-app-server/v1"
                        and preset.get("transport") == "codex-app-server/v1"
                        and preset.get("history") == "persistent_same_episode_thread"
                        and preset.get("terminal_delivery") == "cancel_without_continuation"
                        and parameters.get("provider_calls", "missing") is None
                        and parameters.get("automatic_crash_resume") is False
                        and all(type(source.get(k)) is type(v) and source.get(k) == v
                                for source in (preset, parameters) for k, v in declarations.items())
                        and all(preset.get(k) == manifest["policy"].get(k) for k in ("provider", "model"))
                        and type(effective["timeout_s"]) in (int, float) and 0 < effective["timeout_s"] <= 900
                        and type(effective["max_chunk_length"]) is int and 1 <= effective["max_chunk_length"] <= 32
                        and type(effective["image_max_edge"]) is int and 0 <= effective["image_max_edge"] <= 4096
                        and type(preset.get("safety_stop")) is bool
                        and type(effective.get("safety_stop")) is bool
                        and all(type(parameters.get(k)) is type(effective[k]) and parameters[k] == effective[k] for k in overrides),
                        "Codex Direct native-vector configuration or method declaration changed")
            if method == "codex-planned/v1":
                preset_path = prefix + relative("codex_planned_config.json")
                preset = files.json(preset_path)
                effective = parameters.get("effective_config")
                overrides = {"timeout_s", "max_chunk_length", "image_max_edge"}
                require(isinstance(preset, dict), "invalid captured Codex planned preset")
                optional_stop = preset.get("schema_version") == "starvla-rsi.codex-planned-config/v2"
                if optional_stop:
                    # Direct already declared the global field in old Planned
                    # bundles. Planned's own v2 preset is the capability gate.
                    require(configuration.get("fields", {}).get("safety_stop") == {"type": "boolean"}
                            and "safety_stop" in configuration["factory_parameters"],
                            "invalid captured Planned safety-stop declaration")
                    overrides.add("safety_stop")
                else:
                    require(preset.get("safety_stop") is True and isinstance(effective, dict)
                            and effective.get("safety_stop") is True
                            and parameters.get("safety_stop", True) is True,
                            "historical Codex planned safety stop must remain enabled")
                require(planned_methods and isinstance(preset, dict) and isinstance(effective, dict)
                        and set(preset) == set(effective) and overrides <= set(effective)
                        and json.dumps({k: v for k, v in effective.items() if k not in overrides}, sort_keys=True, allow_nan=False)
                            == json.dumps({k: v for k, v in preset.items() if k not in overrides}, sort_keys=True, allow_nan=False),
                        "Codex planned effective preset differs outside declared overrides")
                require(files.hashes[preset_path] == parameters.get("preset_sha256")
                        and parameters.get("control_method") == method
                        and preset.get("control_method") == method
                        and preset.get("schema_version") in ("starvla-rsi.codex-planned-config/v1",
                                                             "starvla-rsi.codex-planned-config/v2")
                        and parameters.get("transport") == "codex-app-server/v1"
                        and preset.get("transport") == "codex-app-server/v1"
                        and preset.get("history") == "persistent_same_episode_thread_with_bounded_public_summary"
                        and preset.get("terminal_delivery") == "cancel_without_continuation"
                        and preset.get("ordinary_give_up") is False and parameters.get("ordinary_give_up") is False
                        and all(preset.get(k) == manifest["policy"].get(k) for k in ("provider", "model"))
                        and type(effective["timeout_s"]) in (int, float) and 0 < effective["timeout_s"] <= 900
                        and type(effective["max_chunk_length"]) is int and 1 <= effective["max_chunk_length"] <= 32
                        and type(effective["image_max_edge"]) is int and 0 <= effective["image_max_edge"] <= 4096
                        and type(preset.get("safety_stop")) is bool
                        and type(effective.get("safety_stop")) is bool
                        and all(type(parameters.get(k)) is type(effective[k]) and parameters[k] == effective[k] for k in overrides),
                        "Codex planned configuration or method declaration changed")
            if method == "codex-native/v1":
                preset_path = prefix + relative("codex_native_config.json")
                preset = files.json(preset_path)
                effective = parameters.get("effective_config")
                overrides = {"timeout_s", "max_chunk_length", "min_action_decisions_before_give_up"}
                if current:
                    require(type(preset.get("max_attempts")) is int and 1 <= preset["max_attempts"] <= 10
                            and type(preset.get("retry_backoff_s")) in (int, float)
                            and math.isfinite(preset["retry_backoff_s"]) and 0 <= preset["retry_backoff_s"] <= 10
                            and parameters.get("automatic_retry") == {
                                "scope": "same_policy_decision_before_action_submission",
                                "max_attempts": preset["max_attempts"], "retry_backoff_s": preset["retry_backoff_s"]},
                            "Codex native retry declaration differs from captured configuration")
                require(isinstance(preset, dict) and isinstance(effective, dict)
                        and set(effective) == set(preset)
                        and json.dumps({k: v for k, v in effective.items() if k not in overrides},
                                       sort_keys=True, allow_nan=False) ==
                            json.dumps({k: v for k, v in preset.items() if k not in overrides},
                                       sort_keys=True, allow_nan=False),
                        "Codex native effective preset differs outside declared overrides")
                require(files.hashes[preset_path] == parameters.get("preset_sha256")
                        and preset.get("control_method") == method
                        and parameters.get("control_method") == method
                        and parameters.get("transport") == "codex-exec/v1"
                        and parameters.get("max_output_tokens") is None
                        and parameters.get("invalid_action_handling") == "feedback"
                        and type(effective["timeout_s"]) in (int, float)
                        and 0 < effective["timeout_s"] <= 900
                        and type(effective["max_chunk_length"]) is int
                        and 1 <= effective["max_chunk_length"] <= 5
                        and type(effective["min_action_decisions_before_give_up"]) is int
                        and effective["min_action_decisions_before_give_up"] >= 0
                        and all(type(parameters.get(k)) is type(effective[k])
                                and parameters[k] == effective[k] for k in
                                ("timeout_s", "max_chunk_length", "history", "reasoning_effort"))
                        and parameters.get("policy_stop_rule", {}).get("min_action_decisions_before_give_up") ==
                            effective["min_action_decisions_before_give_up"],
                        "Codex native configuration or method declaration changed")
            if method in ("codex-eef/v1", "codex-eef/v2", "codex-direct/v1", "codex-direct/v2"):
                require(method != "codex-eef/v2" or feedback_methods,
                        "Codex feedback method has no declared source extension")
                persistent = method in ("codex-direct/v1", "codex-direct/v2")
                context_v2 = method == "codex-direct/v2"
                preset_path = prefix + relative({"codex-eef/v1": "codex_config.json",
                    "codex-eef/v2": "codex_v2_config.json", "codex-direct/v1": "codex_direct_config.json",
                    "codex-direct/v2": "codex_direct_v2_config.json"}[method])
                preset = files.json(preset_path)
                require(files.hashes[preset_path] == parameters.get("preset_sha256"),
                        "Codex preset digest mismatch")
                effective = parameters.get("effective_config")
                overrides = {"timeout_s", "max_chunk_length"}
                if method in ("codex-eef/v2", "codex-direct/v1", "codex-direct/v2"):
                    overrides.add("enforce_action_guard")
                if context_v2:
                    overrides.add("image_max_edge")
                    edge = effective.get("image_max_edge") if isinstance(effective, dict) else None
                    require(type(edge) is int and 0 <= edge <= 4096
                            and type(parameters.get("image_max_edge")) is int
                            and parameters["image_max_edge"] == edge
                            and all(type(parameters.get(key)) is str and parameters[key] == effective.get(key)
                                    for key in ("public_feedback_schema", "workspace_context_version")),
                            "invalid declared Direct image preview size")
                if persistent and isinstance(preset, dict) and isinstance(effective, dict):
                    overrides.update(audit_direct_protocol(preset, effective, parameters, config, configuration))
                require(isinstance(preset, dict) and isinstance(effective, dict) and set(effective) == set(preset)
                        and all(effective[key] == value for key, value in preset.items()
                                if key not in overrides),
                        "Codex effective preset differs outside declared overrides")
                require(type(effective["timeout_s"]) in (int, float)
                        and 0 < effective["timeout_s"] <= 900
                        and type(effective["max_chunk_length"]) is int
                        and 1 <= effective["max_chunk_length"] <= 5
                        and type(parameters.get("max_chunk_length")) is int
                        and parameters.get("max_chunk_length") == effective["max_chunk_length"]
                        and type(parameters.get("timeout_s")) is type(effective["timeout_s"])
                        and parameters.get("timeout_s") == effective["timeout_s"],
                        "Codex effective overrides exceed method bounds")
                require(parameters.get("control_method") == method and preset.get("control_method") == method
                        and parameters.get("transport") == ("codex-app-server/v1" if persistent else "codex-exec/v1")
                        and parameters.get("ordinary_give_up") is False,
                        "Codex method identity mismatch")
                if method in ("codex-eef/v2", "codex-direct/v1", "codex-direct/v2"):
                    guard = effective.get("enforce_action_guard")
                    require(type(guard) is bool and parameters.get("enforce_action_guard") is guard,
                            "Codex action guard configuration mismatch")
                if persistent:
                    require(json.dumps({key: effective[key] for key in preset if key not in overrides},
                                       sort_keys=True, allow_nan=False) ==
                            json.dumps({key: value for key, value in preset.items() if key not in overrides},
                                       sort_keys=True, allow_nan=False),
                            "Codex Direct fixed configuration type/value mismatch")
                    require(preset.get("schema_version") == ("starvla-rsi.codex-direct-config/v2" if context_v2
                                                            else "starvla-rsi.codex-direct-config/v1")
                            and preset.get("transport") == "codex-app-server/v1"
                            and preset.get("history") == "persistent_same_episode_thread"
                            and preset.get("terminal_delivery") == "cancel_without_continuation"
                            and preset.get("ordinary_give_up") is False
                            and all(preset.get(key) == manifest["policy"].get(key) for key in ("model", "provider"))
                            and "effective_action_rules" not in parameters,
                            "Codex Direct configuration or method declaration changed")
                if method == "codex-eef/v2":
                    # Declarative independent check, never import captured model code.
                    rules = {
                        "schema_version": "starvla-rsi.codex-eef-action-rules/v2",
                        "mandatory_interface": {
                            "finite_numeric_components": True, "pose_length": 7,
                            "target_quaternion_order": "wxyz",
                            "target_quaternion_norm_tolerance": 1e-5,
                            "measured_quaternion_norm_tolerance": 1e-4,
                            "opening_min": 0, "opening_max": 1,
                            "declared_action_spec_bounds": True,
                        },
                        "model_guard": {
                            "enforce_action_guard": guard, "binary_gripper_required": guard,
                            "max_translation_per_decision_m": effective["max_translation_per_decision_m"] if guard else None,
                            "max_rotation_per_decision_rad": effective["max_rotation_per_decision_rad"] if guard else None,
                        },
                        "rejection": {
                            "invalid_target_controls_executed": 0, "automatic_in_act_retry": False,
                            "feedback_on_next_normal_call": True,
                            "already_acknowledged_prefix_is_retained": True,
                        },
                    }
                    require(json.dumps(parameters.get("effective_action_rules"), sort_keys=True) ==
                            json.dumps(rules, sort_keys=True), "Codex effective action rules mismatch")
        provider_sdk = dependencies.get("provider_sdk")
        require(isinstance(provider_sdk, dict) and set(provider_sdk) == {"name", "version"}
                and isinstance(provider_sdk.get("name"), str)
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", provider_sdk["name"])
                and (provider_sdk.get("version") is None or (isinstance(provider_sdk.get("version"), str)
                    and provider_sdk["version"].strip() and len(provider_sdk["version"]) <= 128)),
                "invalid declared provider SDK dependency")
    if current or flat_native:
        allowed = sorted(set(common_files
                             + [f"{namespace}/{profile_id}/{name}" for name in current_names]))
    elif grouped:
        model_prefix = f"{namespace}/{profile_id}/"
        allowed = sorted([model_prefix + relative(path.removeprefix(model_prefix))
                          if path.startswith(model_prefix) else path for path in allowed]
                         + [model_prefix + "methods/__init__.py", model_prefix + "transports/__init__.py"])
    require(dependencies == {"schema_version": "starvla-rsi.model-dependencies/v1", "files": allowed,
                             "evaluation_dependency": "harness_source/index.json", "provider_sdk": provider_sdk},
            "model dependency declaration is not the reviewed allowlist")
    require({row["path"] for row in index["files"]} == set(dependencies["files"]) | {"campaign_prompt.txt"},
            "model dependency allowlist differs from captured files")
    for name in ("profile", "config", "prompt", "dependencies"):
        suffix = ".txt" if name == "prompt" else ".json"
        files.raw(prefix + relative(name + suffix))
        require(files.hashes[prefix + relative(name + suffix)] == identity.get(name + "_sha256"),
                f"model {name} identity digest mismatch")
    files.raw("model_source/files/campaign_prompt.txt")
    require(files.hashes["model_source/files/campaign_prompt.txt"] ==
            manifest["policy"]["parameters"].get("prompt_sha256"), "effective model prompt mismatch")
    for prompt_path in (prefix + relative("prompt.txt"), "model_source/files/campaign_prompt.txt"):
        prompt = files.raw(prompt_path).decode("utf-8")
        require(bool(prompt.strip()) and len(prompt) <= 32768, "invalid model prompt")
    root = files.root / "model_source/files"
    expected_dirs = {parent.as_posix() for row in index["files"] for parent in Path(row["path"]).parents
                     if parent != Path(".")}
    actual_dirs = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_dir()}
    require(actual_dirs == expected_dirs, "unexpected model source directory")
    return count


REJECTION_VERSION = "starvla-rsi.action-rejection-feedback/v1"
USAGE_COUNTERS = {"calls", "input_tokens", "output_tokens", "cached_input_tokens"}
USAGE_FIELDS = USAGE_COUNTERS | {"estimated_cost_usd", "latency_s"}


def finite_number(value) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def audit_usage(value) -> dict:
    """Mirror the data contract independently, retaining unknown rather than zero."""
    require(type(value) is dict and set(value) == USAGE_FIELDS, "missing/invalid call usage")
    for key, number in value.items():
        require(number is None or ((type(number) is int if key in USAGE_COUNTERS
                                     else finite_number(number)) and number >= 0),
                f"invalid usage component: {key}")
    return value


def sum_usage(left: dict, right: dict) -> dict:
    return {key: None if left[key] is None or right[key] is None else left[key] + right[key]
            for key in USAGE_FIELDS}


def same_usage(actual: dict, expected: dict) -> bool:
    audit_usage(actual)
    return all(actual[key] is None if expected[key] is None else (
        actual[key] is not None and (actual[key] == expected[key] if key in USAGE_COUNTERS
        else math.isclose(actual[key], expected[key], rel_tol=1e-12, abs_tol=1e-9)))
        for key in USAGE_FIELDS)


def audit_validation_issue(issue) -> None:
    # Closed public DTO, deliberately independent of live/frozen Python modules.
    codes = {"invalid_json", "unexpected_fields", "invalid_type", "invalid_length", "non_finite",
             "out_of_bounds", "quaternion_not_unit", "translation_limit", "rotation_limit",
             "gripper_binary_required", "invalid_stop", "invalid_action"}
    fields = {"action", "response", "steps", "memory", "note", "safety_stop", "left", "right",
              "left.pose", "right.pose", "left.opening", "right.opening", "left.translation_m",
              "right.translation_m", "left.rotation_rad", "right.rotation_rad",
              "left.quaternion_norm", "right.quaternion_norm"}
    require(type(issue) is dict and set(issue) == {"code", "field", "actual", "limit", "action_index"},
            "invalid rejection issue fields")
    require(type(issue["code"]) is str and issue["code"] in codes
            and type(issue["field"]) is str and issue["field"] in fields,
            "unknown rejection issue code/field")
    require(all(issue[key] is None or finite_number(issue[key]) for key in ("actual", "limit")),
            "unsafe rejection issue values")
    require(issue["action_index"] is None or (type(issue["action_index"]) is int
            and 0 <= issue["action_index"] <= 2**31 - 1), "invalid rejection component index")


def audit_episode(result: dict, events: list, protocol: dict, policy: dict | None = None) -> dict:
    usage_version = protocol.get("usage_accounting_version")
    require(usage_version in (None, "starvla-rsi.method-usage/v1"),
            "unknown method usage accounting version")
    multiple_inferences = usage_version == "starvla-rsi.method-usage/v1"
    require(events and events[0]["event"] == "episode_start" and events[-1]["event"] == "episode_end",
            "episode event boundaries missing")
    require(sum(e["event"] == "episode_start" for e in events) == 1
            and sum(e["event"] == "episode_end" for e in events) == 1, "duplicate episode boundary")
    require(events[0]["episode"] == result["episode"] and events[-1]["result"] == result,
            "episode boundary/result mismatch")
    calls = counter(result["policy_calls"], "policy")
    controls = counter(result["environment_steps"], "control")
    require(controls <= protocol["max_steps"], "control budget exceeded")
    require(protocol["max_policy_calls"] is None or calls <= protocol["max_policy_calls"],
            "decision budget exceeded")
    completed = result["status"] == "completed"
    minimum = counter(protocol.get("min_action_decisions_before_give_up", 0), "voluntary-stop floor")
    feedback_version = protocol.get("execution_feedback_version")
    new_counters = feedback_version == "starvla-rsi.execution-feedback/v1"
    require(feedback_version is None or new_counters, "unknown execution feedback contract")
    control_schema = protocol.get("control_feedback_schema")
    if control_schema is not None:
        require(isinstance(control_schema, str) and 1 <= len(control_schema) <= 128
                and protocol.get("control_acknowledgement_version") == "starvla-rsi.control-acknowledgement/v1"
                and new_counters, "unbound public control acknowledgement extension")
    else:
        require("control_acknowledgement_version" not in protocol, "undeclared public control channel")
    rejection_mode = protocol.get("invalid_action_handling", "terminate")
    require(rejection_mode in ("terminate", "feedback"), "unknown invalid-action handling")
    recover_rejections = rejection_mode == "feedback"
    if recover_rejections:
        require(protocol.get("action_rejection_feedback_version") == REJECTION_VERSION and new_counters,
                "unbound rejection feedback extension")
        require(type(protocol["max_policy_calls"]) is int and protocol["max_policy_calls"] > 0,
                "rejection feedback requires a finite positive integer call cap")
        require(type(protocol["max_steps"]) is int and protocol["max_steps"] > 0
                and (protocol["replan_interval"] is None or (type(protocol["replan_interval"]) is int
                     and protocol["replan_interval"] > 0)), "invalid feedback-mode control/prefix budget")
        counter(result.get("rejected_actions"), "rejected actions")
    else:
        require("action_rejection_feedback_version" not in protocol,
                "rejection feedback extension requires feedback mode")
    policy_rule = (policy or {}).get("parameters", {}).get("policy_stop_rule")
    if new_counters:
        require(not {"min_action_decisions_before_give_up", "stop_constraint_version",
                     "early_policy_stop_exception"} & set(protocol),
                "policy stopping preference must not be a benchmark protocol")
        if policy_rule is not None:
            require(isinstance(policy_rule, dict) and set(policy_rule) == {
                "stop_constraint_version", "min_action_decisions_before_give_up",
                "early_policy_stop_exception", "scope"}, "invalid policy stop configuration")
            minimum = counter(policy_rule["min_action_decisions_before_give_up"], "policy stop preference")
            require(policy_rule["stop_constraint_version"] == "minimum-action-decisions/v2"
                    and policy_rule["early_policy_stop_exception"] == "safety_stop_with_nonempty_note"
                    and policy_rule["scope"] == "policy", "unknown policy stop configuration")
    elif minimum:
        require(protocol.get("stop_constraint_version") == "minimum-action-decisions/v1"
                and protocol.get("early_policy_stop_exception") == "safety_stop_with_nonempty_note",
                "unknown voluntary-stop protocol")
    else:
        require("stop_constraint_version" not in protocol and "action_decisions" not in result,
                "unbound voluntary-stop extension")
    require(completed or result["status"] == "error", "unknown episode status")
    require((type(result["success"]) is bool and result["error"] is None
             and result["metrics"].get("success") == result["success"]) if completed
            else (result["success"] is None and isinstance(result["error"], dict)),
            "result success/error semantics disagree")

    call = step = 0
    decision = chunk = None
    played = 0
    decisions = chunks = stops = 0
    terminal = False
    last_control = None
    reward = 0.0
    executed_calls = set()
    rejected = False
    rejections = rejected_acts = rejected_specs = 0
    observed = False
    metered_calls = set()
    usage_total = {key: 0 for key in USAGE_FIELDS}
    excess_provider_calls = False
    errors_seen = 0
    control_acks = []
    for event in events[1:-1]:
        kind = event["event"]
        if kind == "policy_call_start":
            require(not terminal, "decision after terminal event")
            require(not recover_rejections or observed, "policy call without initial observation")
            if call:
                require(rejected or (chunk is not None and played == chunk["maximum_executed_prefix"]),
                        "new decision before preceding prefix completed")
            require(not excess_provider_calls, "provider retry violation was not terminal")
            call += 1
            require(counter(event["policy_call"], "event policy") == call, "decision-start order mismatch")
            decision = chunk = None
            played = 0
            control_acks = []
            rejected = False
        elif kind == "policy_decision":
            require(call > 0 and decision is None and event["policy_call"] == call and not rejected
                    and (not recover_rejections or not terminal),
                    "unscheduled/duplicate policy decision")
            require(type(event["stop"]) is bool, "invalid stop flag")
            if recover_rejections:
                counter(event["policy_call"], "returned policy")
                counter(event["chunk_length"], "returned chunk length")
            metadata = event.get("metadata", {})
            response = metadata.get("structured_response")
            if response is not None:
                require(response.get("request_id") == metadata.get("request_id"),
                        "embedded response/request ID mismatch")
                require(response.get("stop", False) is event["stop"], "embedded response/stop mismatch")
                if event["stop"]:
                    require(response.get("stop_reason") == event["stop_reason"]
                            and "actions" not in response, "embedded stop content mismatch")
            decision = event
            decisions += 1
            if recover_rejections:
                reported = audit_usage(event.get("usage"))
                require(call not in metered_calls, "duplicate call accounting")
                metered_calls.add(call)
                usage_total = sum_usage(usage_total, reported)
                excess_provider_calls = (not multiple_inferences
                                         and reported["calls"] is not None and reported["calls"] > 1)
            if event["stop"]:
                require(event["chunk_length"] == 0, "stop contains an action chunk")
                if minimum:
                    safety = event["stop_reason"] == "safety_stop"
                    note = event.get("note")
                    valid = (isinstance(note, str) and bool(note.strip())) if safety else len(executed_calls) >= minimum
                    require(valid or (not completed and result["error"]["category"] == "policy"),
                            "premature/invalid stop was not recorded as a policy error")
                stops += 1
                terminal = True
        elif kind == "action_chunk":
            require(not terminal and not rejected and decision is not None and chunk is None
                    and event["policy_call"] == call, "unscheduled/duplicate action chunk")
            require(not excess_provider_calls, "control after provider retry violation")
            if recover_rejections:
                counter(event["policy_call"], "chunk policy")
            actions = event["actions"]
            require(isinstance(actions, list) and len(actions) == decision["chunk_length"] > 0,
                    "decision/action chunk length mismatch")
            expected = min(len(actions), protocol["max_steps"] - step)
            if protocol["replan_interval"] is not None:
                expected = min(expected, protocol["replan_interval"])
            require(counter(event["maximum_executed_prefix"], "prefix") == expected,
                    "executed-prefix budget mismatch")
            response = decision.get("metadata", {}).get("structured_response")
            if response is not None:
                require(response.get("actions") == actions, "embedded accepted response/action mismatch")
            chunk = event
            chunks += 1
        elif kind == "environment_step":
            require(not terminal and not rejected and chunk is not None and event["policy_call"] == call,
                    "control outside active action chunk")
            require(not excess_provider_calls, "control after provider retry violation")
            if recover_rejections:
                counter(event["policy_call"], "control policy")
                counter(event["chunk_index"], "control prefix index")
            require(event["chunk_index"] == played and played < chunk["maximum_executed_prefix"],
                    "control prefix index mismatch")
            require(event["action"] == chunk["actions"][played], "executed action differs from prefix")
            step += 1
            executed_calls.add(call)
            played += 1
            require(counter(event["environment_step"], "event control") == step, "control order mismatch")
            require(type(event["terminated"]) is bool and type(event["truncated"]) is bool,
                    "invalid environment terminal flags")
            terminal = event["terminated"] or event["truncated"]
            last_control = event
            public = event.get("observation", {})
            if control_schema is not None:
                payload = public.get("control_feedback")
                require(type(payload) is dict and payload.get("schema") == control_schema
                        and type(payload.get("control_target")) is int and payload["control_target"] == step
                        and type(public.get("step")) is int and public["step"] == step,
                        "uncorrelated public control acknowledgement")
                control_acks.append({"environment_step": step, "observation_step": step, "payload": payload})
            else:
                require("control_feedback" not in public, "undeclared public control payload")
            if recover_rejections:
                require(finite_number(event["reward"]), "invalid acknowledged reward")
            reward += event["reward"]
        elif kind == "action_rejected":
            require(recover_rejections, "action rejection without declared feedback extension")
            require(set(event) == {"event", "timestamp", "policy_call", "phase", "feedback", "usage",
                                   "usage_recorded_in", "metadata"}, "invalid rejection event fields")
            require(not terminal and not rejected and call > 0
                    and counter(event["policy_call"], "rejected policy") == call,
                    "unscheduled/duplicate action rejection")
            require(not excess_provider_calls, "provider retry violation cannot recover")
            phase, feedback = event["phase"], event["feedback"]
            require(type(feedback) is dict and set(feedback) == {
                "schema_version", "issue", "policy_calls", "action_decisions", "environment_steps",
                "executed_steps", "rejected_actions"} | ({"control_acks"} if control_schema is not None else set())
                and feedback["schema_version"] == REJECTION_VERSION,
                "invalid rejection feedback schema")
            if control_schema is not None:
                require(type(feedback["control_acks"]) is list and
                        json.dumps(feedback["control_acks"], sort_keys=True, allow_nan=False) ==
                        json.dumps(control_acks, sort_keys=True, allow_nan=False),
                        "rejection receipt differs from acknowledged control prefix")
            audit_validation_issue(feedback["issue"])
            rejections += 1
            for key, expected in (("policy_calls", call), ("action_decisions", len(executed_calls)),
                                  ("environment_steps", step), ("executed_steps", played),
                                  ("rejected_actions", rejections)):
                require(counter(feedback[key], "rejection " + key) == expected,
                        "rejection feedback counter mismatch: " + key)
            reported = audit_usage(event["usage"])
            require(type(event["metadata"]) is dict and len(json.dumps(event["metadata"], allow_nan=False,
                    separators=(",", ":")).encode("utf-8")) <= 16 * 1024,
                    "invalid rejection receipt metadata")
            if phase == "policy_act":
                require(decision is None and chunk is None and played == 0
                        and event["usage_recorded_in"] == "action_rejected"
                        and call not in metered_calls, "invalid policy-act rejection lifecycle/accounting")
                require(multiple_inferences or reported["calls"] is None or reported["calls"] <= 1,
                        "provider retry violation cannot recover")
                usage_total = sum_usage(usage_total, reported)
                metered_calls.add(call)
                rejected_acts += 1
            else:
                require(decision is not None and not decision["stop"] and call in metered_calls
                        and event["usage_recorded_in"] == "policy_decision"
                        and all(value is not None and value == 0 for value in reported.values()),
                        "post-decision rejection must not add provider usage")
                if phase == "action_spec":
                    require(chunk is None and played == 0, "invalid action-spec rejection lifecycle")
                    rejected_specs += 1
                else:
                    require(phase == "session_step" and chunk is not None
                            and played < chunk["maximum_executed_prefix"],
                            "invalid session-step rejection lifecycle")
            rejected = True
        elif kind == "observation":
            require(call == 0 and step == 0, "unexpected extra observation event")
            require(not recover_rejections or not observed, "duplicate initial observation")
            observed = True
            require(event.get("observation", {}).get("control_feedback") is None,
                    "reset reused a previous control acknowledgement")
        elif kind in ("error", "artifact_error"):
            require(not completed, "completed result contains an error event")
            recorded_error = event.get("error", {})
            if recover_rejections or "rejected_actions" in result:
                require(type(recorded_error) is dict, "invalid recorded error object")
            if recover_rejections and kind == "error":
                require(errors_seen == 0, "duplicate terminal error event")
                errors_seen += 1
            if kind == "error" and "rejected_actions" in result:
                typed = recorded_error.get("policy_call_error", recorded_error)
                require(type(typed) is dict, "invalid recorded policy-call error")
                if typed.get("type") == "ActionRejected":
                    audit_validation_issue(typed.get("issue"))
                phase = typed.get("action_rejection_phase")
                if phase is not None:
                    require(typed.get("type") == "ActionRejected" and call > 0 and not terminal
                            and not rejected, "unscheduled terminal action rejection")
                    if phase == "policy_act":
                        require(decision is None and chunk is None and played == 0
                                and counter(recorded_error.get("policy_call"), "terminal rejected policy") == call,
                                "invalid terminal policy-act rejection")
                        reported = audit_usage(recorded_error.get("usage"))
                        require(not recover_rejections or (not multiple_inferences and reported["calls"] is not None
                                and reported["calls"] > 1), "recoverable rejection mislabeled as terminal")
                    else:
                        require(phase == "session_step" and not recover_rejections and decision is not None
                                and not decision["stop"] and chunk is not None
                                and played < chunk["maximum_executed_prefix"],
                                "invalid terminal session-step rejection")
                    rejections += 1
            if recover_rejections and kind == "error" and "usage" in recorded_error:
                require(call > 0 and call not in metered_calls
                        and counter(recorded_error.get("policy_call"), "failed policy") == call,
                        "duplicate/unscheduled failed-call accounting")
                usage_total = sum_usage(usage_total, audit_usage(recorded_error["usage"]))
                metered_calls.add(call)
            terminal = True
        else:
            raise AuditError(f"unsupported event kind: {kind}")

    require(call == calls and step == controls, "logged/result counters disagree")
    if "rejected_actions" in result:
        require(counter(result["rejected_actions"], "rejected actions") == rejections,
                "logged/result rejection counters disagree")
    if recover_rejections:
        require(metered_calls == set(range(1, calls + 1)), "unmetered policy call in feedback mode")
        require(same_usage(result.get("usage"), usage_total), "logged/result usage mismatch")
        require(not excess_provider_calls or not completed,
                "provider retry violation must be an error")
        require(finite_number(result["reward_sum"]), "invalid total acknowledged reward")
    if minimum or new_counters:
        require(counter(result.get("action_decisions"), "executed action decisions") == len(executed_calls),
                "action-decision count differs from executed controls")
    require(math.isclose(reward, result["reward_sum"], rel_tol=1e-12, abs_tol=1e-9),
            "logged/result reward sum mismatch")
    if completed:
        require(decisions + rejected_acts == calls and chunks + stops + rejected_specs == decisions,
                "completed decision coverage incomplete")
        require(not chunk or terminal or rejected or played == chunk["maximum_executed_prefix"],
                "completed result has an unexplained partial prefix")
        if stops:
            require(result["termination_reason"] == f"policy:{decision['stop_reason']}", "stop reason mismatch")
        else:
            # Match runner.py precedence, including the decision-primary tie at
            # D*K: native termination wins, then the declared decision cap,
            # then native truncation and the ordinary step cap.
            call_limit = protocol["max_policy_calls"]
            calls_exhausted = call_limit is not None and call >= call_limit
            steps_exhausted = step >= protocol["max_steps"]
            if last_control is not None and last_control["terminated"]:
                expected_reason = "environment:terminated"
            elif protocol["budget_mode"] == "decisions" and steps_exhausted and calls_exhausted:
                expected_reason = "runner:policy_call_limit"
            elif last_control is not None and last_control["truncated"]:
                expected_reason = "environment:truncated"
            elif steps_exhausted:
                expected_reason = "runner:step_limit"
            elif calls_exhausted:
                expected_reason = "runner:policy_call_limit"
            else:
                raise AuditError("completed episode has no applicable termination condition")
            require(result["termination_reason"] == expected_reason, "termination reason mismatch")
    else:
        # Failed act/validation/step/cleanup may leave one incomplete final turn.
        require(calls - decisions - rejected_acts in (0, 1), "multiple missing decisions hidden by error")
        require(result["termination_reason"] == f"error:{result['error']['category']}",
                "error termination reason mismatch")
    row = {"episode_id": result["episode"]["id"], "status": result["status"],
            "success": result["success"], "controls": controls, "decisions_started": calls,
            "decisions_returned": decisions, "action_chunks": chunks, "stop_decisions": stops,
            "termination_reason": result["termination_reason"]}
    if minimum or new_counters:
        row["action_decisions"] = len(executed_calls)
    if "rejected_actions" in result:
        row["rejected_actions"] = rejections
    return row


def audit_run(run: Path) -> dict:
    auditor_path = Path(__file__).resolve()
    auditor_digest = hashlib.sha256(auditor_path.read_bytes()).hexdigest()
    files = ClosedFiles(run)
    status = files.json("status.json")
    require(status.get("status") in ("completed", "completed_with_errors"), "only closed runs may be audited")
    manifest = files.json("manifest.json")
    require(manifest["schema_version"] == "starvla-rsi.eval/v1", "unsupported run schema")
    require(manifest.get("observation_spec", {}).get("control_feedback_schema") ==
            manifest["protocol"].get("control_feedback_schema"), "public control channel binding mismatch")
    count = audit_source(files, manifest)
    model_count = audit_model_source(files, manifest)
    results = files.jsonl("episodes.jsonl")
    require(results and len(results) == status["episodes_written"], "closed episode count mismatch")
    ids = [row["episode"]["id"] for row in results]
    require(len(ids) == len(set(ids)), "duplicate result episode IDs")
    require(ids == manifest["protocol"]["episode_ids"][:len(ids)], "result order differs from selection")
    paths = sorted((files.root / "episodes").glob("*/result.json"))
    require(len(paths) == len(results), "episode directory/index count mismatch")
    found = {}
    for path in paths:
        relative = path.relative_to(files.root).as_posix()
        result = files.json(relative)
        episode_id = result["episode"]["id"]
        require(episode_id not in found, "duplicate episode directory identity")
        found[episode_id] = (result, path.parent.relative_to(files.root).as_posix())
    rows = []
    for indexed in results:
        require(indexed["episode"]["id"] in found, "indexed episode has no result")
        result, directory = found[indexed["episode"]["id"]]
        require(result == indexed, "episode index/result mismatch")
        rows.append(audit_episode(result, files.jsonl(directory + "/events.jsonl"),
                                  manifest["protocol"], manifest["policy"]))
    completed = sum(row["status"] == "completed" for row in rows)
    require(status["status"] == ("completed" if completed == len(rows) else "completed_with_errors"),
            "run/episode lifecycle mismatch")
    if len(rows) != len(manifest["protocol"]["episode_ids"]):
        require(manifest["protocol"]["fail_fast"] and results[-1]["status"] == "error",
                "selected episodes silently omitted")
    summary = files.json("summary.json")
    for key, expected in {"attempted": len(rows), "completed": completed, "errors": len(rows) - completed,
                          "successes": sum(row["success"] is True for row in rows),
                          "policy_calls": sum(row["decisions_started"] for row in rows)}.items():
        require(summary[key] == expected, f"summary {key} mismatch")
    if manifest["protocol"].get("invalid_action_handling") == "feedback":
        require(counter(summary.get("rejected_actions"), "summary rejected actions") ==
                sum(row["rejected_actions"] for row in rows), "summary rejected actions mismatch")
        usage = {key: 0 for key in USAGE_FIELDS}
        for result in results:
            usage = sum_usage(usage, audit_usage(result.get("usage")))
        require(same_usage(summary.get("usage"), usage), "summary usage mismatch")
    files.verify_unchanged()
    require(hashlib.sha256(auditor_path.read_bytes()).hexdigest() == auditor_digest,
            "auditor changed during audit")
    report = {"schema_version": "starvla-rsi.closed-record-audit/v1", "source_run": str(files.root),
            "auditor": {"path": str(auditor_path), "sha256": auditor_digest},
            "record_consistency": "passed", "source_files_verified": count, "episodes": rows,
            "read_file_sha256": files.hashes,
            "limitations": ["Read-only runner-record consistency, not native benchmark parity or execution attestation.",
                            "Does not follow mailbox, video or native asset paths; independent artifact audit is separate.",
                            "No OS isolation or trusted model/provider/usage attestation.",
                            "A consistent error or failed task is not a successful task."]}
    if model_count:
        report["model_source_files_verified"] = model_count
    if manifest["policy"].get("version") in ("codex-direct/v1", "codex-direct/v2", "codex-direct/v3",
                                             "codex-direct/v4", "codex-planned/v1", "codex-native/v2"):
        report["persistent_direct_artifacts_audited"] = False
        report["limitations"].append(
            "Persistent policy support checks captured configuration and the generic call/ACK ledger only; "
            "app-server thread/tool/token-watermark/closure receipts and native EEF artifacts are not audited here.")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="new evaluator-private report outside the closed run")
    args = parser.parse_args()
    require(not args.output.resolve().is_relative_to(args.run_dir.resolve()), "report must be outside the closed run")
    report = audit_run(args.run_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(args.output)


if __name__ == "__main__":
    main()
