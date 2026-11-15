"""Portable declarations for agent methods, independent of a Python policy SDK.

These are participant declarations, not provider identity or usage attestation.
Configuration is explicitly public: never include credentials or private paths.
"""
from __future__ import annotations

import math
import re

METHOD_SCHEMA = "starvla-rsi.method/v1"
USAGE_ACCOUNTING_VERSION = "starvla-rsi.method-usage/v2"
USAGE_FIELDS = ("calls", "input_tokens", "output_tokens", "cached_input_tokens",
                "estimated_cost_usd", "latency_s")
_SECRET = {"password", "secret", "credentials", "authorization", "api_key", "apikey",
           "api_token", "access_token", "refresh_token", "bearer_token", "client_secret"}


def _text(value, label, *, optional=False, identifier=False):
    if optional and value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ValueError(f"invalid {label}")
    if any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise ValueError(f"invalid {label}")
    if identifier and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value) is None:
        raise ValueError(f"invalid {label} identifier")
    if value.startswith(("/", "~/", "\\\\")) or re.match(r"^[A-Za-z]:[\\/]", value):
        raise ValueError(f"private path in {label}")
    return value


def _configuration(value):
    remaining = 8192

    def walk(item, depth=0):
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > 8:
            raise ValueError("method configuration exceeds bounds")
        if item is None or type(item) in (bool, int):
            return item
        if type(item) is float and math.isfinite(item):
            return item
        if isinstance(item, str):
            if len(item) > 16384 or any(0xD800 <= ord(c) <= 0xDFFF for c in item):
                raise ValueError("invalid method configuration text")
            if item.startswith(("/", "~/", "\\\\")) or re.match(r"^[A-Za-z]:[\\/]", item):
                raise ValueError("private path in public method configuration")
            return item
        if type(item) is list:
            return [walk(child, depth + 1) for child in item]
        if type(item) is dict:
            out = {}
            for key, child in item.items():
                if not isinstance(key, str) or not key or len(key) > 128:
                    raise ValueError("invalid method configuration key")
                lowered = key.lower().replace("-", "_")
                if lowered in _SECRET or any(lowered.endswith("_" + name) for name in _SECRET):
                    raise ValueError("credential field in public method configuration")
                out[key] = walk(child, depth + 1)
            return out
        raise ValueError("method configuration must be finite JSON")

    if type(value) is not dict:
        raise ValueError("method configuration must be an object")
    return walk(value)


def normalize_method(value):
    """Validate a public method declaration; reject undeclared top-level fields."""
    if type(value) is not dict or set(value) - {"schema_version", "id", "version", "models", "configuration"}:
        raise ValueError("invalid method declaration fields")
    if value.get("schema_version") != METHOD_SCHEMA:
        raise ValueError("unsupported method schema")
    models = value.get("models")
    if type(models) is not list or len(models) > 64:
        raise ValueError("method models must be a bounded list")
    normalized = []
    for row in models:
        if type(row) is not dict or set(row) - {"id", "role", "provider", "model", "version"}:
            raise ValueError("invalid model component fields")
        normalized.append({"id": _text(row.get("id"), "component ID", identifier=True),
                           "role": _text(row.get("role"), "component role"),
                           **{key: _text(row.get(key), "component " + key, optional=True)
                              for key in ("provider", "model", "version")}})
    if len({row["id"] for row in normalized}) != len(normalized):
        raise ValueError("duplicate method model component")
    return {"schema_version": METHOD_SCHEMA,
            "id": _text(value.get("id"), "method ID"),
            "version": _text(value.get("version"), "method version", optional=True),
            "models": normalized, "configuration": _configuration(value.get("configuration", {}))}


def method_from_policy(descriptor):
    """Project a policy descriptor without a method file; never guess provider/model/configuration."""
    policy = descriptor.to_dict() if hasattr(descriptor, "to_dict") else descriptor
    if type(policy) is not dict:
        raise ValueError("policy descriptor must be an object")
    models = []
    if policy.get("model") is not None or policy.get("provider") is not None:
        models = [{"id": "primary", "role": "policy", "model": policy.get("model"),
                   "provider": policy.get("provider"), "version": None}]
    return normalize_method({"schema_version": METHOD_SCHEMA, "id": policy.get("name"),
                             "version": policy.get("version"), "models": models,
                             "configuration": {}})


def normalize_usage(value):
    """Missing fields are unavailable, never implicitly zero."""
    if value is None:
        value = {}
    if type(value) is not dict or set(value) - set(USAGE_FIELDS):
        raise ValueError("invalid component usage fields")
    out = {}
    for key in USAGE_FIELDS:
        number = value.get(key)
        kinds = (int,) if key in USAGE_FIELDS[:4] else (int, float)
        if number is not None and (type(number) not in kinds or number < 0
                                   or type(number) is float and not math.isfinite(number)
                                   or type(number) is int and number > 2**63 - 1):
            raise ValueError("invalid component usage value")
        out[key] = number
    if (out["cached_input_tokens"] is not None and out["input_tokens"] is not None
            and out["cached_input_tokens"] > out["input_tokens"]):
        raise ValueError("cached input tokens exceed input tokens")
    return out


def normalize_component_usage(value, method):
    """Map declared IDs to reported usage; every absent component stays unknown."""
    ids = [row["id"] for row in normalize_method(method)["models"]]
    if value is None:
        value = {}
    if type(value) is not dict or set(value) - set(ids):
        raise ValueError("usage names an undeclared model component")
    return {identifier: normalize_usage(value.get(identifier)) for identifier in ids}


def sum_component_usage(left, right, method):
    """Sum declared component ledgers with unknown propagation, not allocation."""
    left, right = normalize_component_usage(left, method), normalize_component_usage(right, method)
    return {identifier: {key: None if left[identifier][key] is None or right[identifier][key] is None
                          else left[identifier][key] + right[identifier][key]
                          for key in USAGE_FIELDS} for identifier in left}
