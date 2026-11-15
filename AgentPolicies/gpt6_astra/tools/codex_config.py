"""Codex app-server launch settings, and the check that Codex actually applied them."""
from __future__ import annotations

import json
from pathlib import Path
import sys

from benchkit.errors import PolicyError

PERMISSIONS = "rsi_direct_actor"  # profile defined here, selected by thread/start and turn/start
MAX_INHERITED_MCP_SERVERS = 128  # more inherited servers is rejected as invalid
MAX_MCP_NAME_BYTES = 1024  # UTF-8 size limit of one server name


def _toml(value, *, ensure_ascii=True):  # TOML text for "-c key=value"; dict -> inline table
    if isinstance(value, dict):
        return "{" + ", ".join(json.dumps(k, ensure_ascii=ensure_ascii) + "="
                              + _toml(v, ensure_ascii=ensure_ascii) for k, v in value.items()) + "}"
    return json.dumps(value, ensure_ascii=ensure_ascii)


def launch_settings(actor, public, model, provider, effort):
    """Codex settings for the actor: no web search, shell network, MCP servers, project documents
    or inherited shell environment, and write access only to the actor workspace.

    The app-server keeps the existing login; shell tools do not get it.
    """
    # Filesystem access of the profile: read the Python installs and public dir; write only the actor dir.
    files = {":minimal": "read", str(Path(sys.prefix).resolve()): "read",
             str(Path(sys.base_prefix).resolve()): "read",
             str(actor): "write", str(public): "read"}  # public: observation files written by the host
    runtime = Path(actor).parent / "runtime"  # persistent_runtime._boot creates this dir
    settings = {
        "model": model, "model_provider": provider, "model_reasoning_effort": effort,
        "approval_policy": "never",  # no approval prompts
        "default_permissions": PERMISSIONS, "permissions." + PERMISSIONS + ".filesystem": files,
        "permissions." + PERMISSIONS + ".network.enabled": False,  # no network for shell tools
        "shell_environment_policy.inherit": "none",  # shell tools start from an empty environment
        "shell_environment_policy.experimental_use_profile": False, "allow_login_shell": False,
        # Shell tools get only this PATH (this Python's bin dir first) and the C locale.
        "shell_environment_policy.set": {"PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin:/usr/sbin:/sbin",
                                          "LANG": "C", "LC_ALL": "C"},
        # No web search, MCP servers, project docs (AGENTS.md) or notify hooks.
        "web_search": "disabled", "mcp_servers": {}, "project_doc_max_bytes": 0, "notify": [],
        "agents.enabled": False, "history.persistence": "none",
        "sqlite_home": str(runtime / "db"), "log_dir": str(runtime / "logs"),  # Codex state in the episode's temp dir
        # Tools the actor keeps; the optional features below are switched off.
        "features.shell_tool": True, "features.view_image": True, "features.code_mode_host": True,
        "features.skip_host_skill_discovery": True,
    }
    for feature in ("apps", "plugins", "browser_use", "computer_use", "multi_agent", "multi_agent_v2",
                    "hooks", "goals", "memories", "skill_search", "skill_mcp_dependency_install",
                    "request_permissions_tool", "image_generation", "tool_suggest", "remote_control",
                    "remote_plugin", "auth_elicitation", "mcp_2026_07_28"):
        settings["features." + feature] = False
    return settings


def launch_command(executable, actor, public, model, provider, effort, *, disabled_mcp_names=()):
    # argv for StdioAppServer: one -c override per launch setting, then any MCP servers to disable.
    argv = [str(executable), "app-server", "--stdio", "--strict-config"]
    for key, value in launch_settings(actor, public, model, provider, effort).items():
        argv += ["-c", key + "=" + _toml(value)]
    # The pinned CLI's dotted override-key parser is not a TOML key parser.
    # Put names inside one TOML inline-table VALUE, with a plain top-level key.
    # Non-ASCII scalars stay literal: JSON surrogate pairs are not valid TOML.
    # Names come from persistent_runtime's first config/read; this call validates and sorts them.
    names, _ = inherited_mcp_names({"mcp_servers": {name: {"enabled": False} for name in disabled_mcp_names}})
    if names:
        argv += ["-c", "mcp_servers=" + _toml({name: {"enabled": False} for name in names}, ensure_ascii=False)]
    return argv


def verify_configuration(config, actor, public, model, provider, effort):
    """Fail before a turn if inherited user/project config expands capabilities.

    --strict-config validates config syntax; it does not ignore user config.
    Do not record the raw effective config: it may contain private credentials.
    """
    wanted = launch_settings(actor, public, model, provider, effort)
    # Each launch setting must read back unchanged; permissions and MCP are checked below.
    for key, expected in wanted.items():
        if key.startswith("permissions.") or key == "mcp_servers":
            continue
        actual = config
        for component in key.split("."):  # walk the dotted key through nested tables
            actual = actual.get(component) if isinstance(actual, dict) else None
        # bool must stay bool: in Python 1 == True and 0 == False.
        if actual != expected or (type(expected) is bool and type(actual) is not bool):
            raise PolicyError("effective Codex configuration differs from declared Direct settings")
    profile = (config.get("permissions") or {}).get(PERMISSIONS)
    # A profile that extends another or adds workspace roots could widen access.
    if not isinstance(profile, dict) or profile.get("extends") is not None or profile.get("workspace_roots") is not None:
        raise PolicyError("Direct permission profile may not inherit additional roots")
    # Unset (null) entries are ignored; the rest must equal what launch_settings declared.
    filesystem = {key: value for key, value in (profile.get("filesystem") or {}).items() if value is not None}
    network = {key: value for key, value in (profile.get("network") or {}).items() if value is not None}
    if filesystem != wanted["permissions." + PERMISSIONS + ".filesystem"] or network != {"enabled": False}:
        raise PolicyError("Direct permission profile contains additional filesystem/network authority")
    _, enabled = inherited_mcp_names(config)  # every inherited MCP server must be disabled
    if enabled:
        raise PolicyError("inherited MCP servers must be explicitly disabled before Direct execution")
    shell = config.get("shell_environment_policy") or {}
    if shell.get("set") != wanted["shell_environment_policy.set"]:
        raise PolicyError("inherited shell environment is not allowed")
    # No instruction overrides from user config; the prompt comes through thread/start.
    if any(config.get(key) for key in ("model_instructions_file", "experimental_compact_prompt_file",
                                       "instructions", "compact_prompt")):
        raise PolicyError("inherited model/compact instructions are not allowed")
    # Saved as configuration_receipt in session.json; the raw config is not kept.
    return {"effective_configuration_checked": True, "enabled_mcp_servers": 0,
            "permission_roots_match": True, "shell_environment_match": True}


def inherited_mcp_names(config):
    """Sorted names of all inherited MCP servers, and of those not explicitly disabled."""
    if not isinstance(config, dict):
        raise PolicyError("invalid effective Codex configuration")
    servers = config.get("mcp_servers")
    if servers is None:
        servers = {}
    if not isinstance(servers, dict) or len(servers) > MAX_INHERITED_MCP_SERVERS:
        raise PolicyError("invalid inherited MCP configuration")
    names, enabled = [], []
    for name, server in servers.items():
        try:
            valid_name = (type(name) is str and bool(name)
                          and len(name.encode("utf-8")) <= MAX_MCP_NAME_BYTES
                          and not any(ord(character) < 32 or ord(character) == 127 for character in name))
        except UnicodeError:
            valid_name = False
        if (not valid_name or not isinstance(server, dict)
                or ("enabled" in server and type(server["enabled"]) is not bool)):
            raise PolicyError("invalid inherited MCP configuration")
        names.append(name)
        if server.get("enabled") is not False:  # a missing "enabled" counts as enabled
            enabled.append(name)
    return tuple(sorted(names)), tuple(sorted(enabled))
