"""A small trusted driver example: one preselected case, one control per decision.

No Policy subclass, EvaluationRunner, profile registry or model backend is used.
The callback is reviewed trusted bridge code, not an OS-isolated untrusted actor.
Never pass the client or evaluator process capabilities to a model/tool process.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
import time

from benchkit.artifacts import append_jsonl, atomic_write_json, utc_now
from benchkit.contracts import Usage, ensure_jsonable
from benchkit.errors import ActionRejected, ProtocolError
from benchkit.methods import normalize_method, normalize_usage, normalize_component_usage, sum_component_usage
from benchkit.recording import InteractionRecorder, RecordingOptions
from benchkit.reports.run_summary import summarize_run


def _public_input(observation, client, calls, controls):
    """Project data, not objects carrying administrative capabilities."""
    return {"episode": "episode-000000", "instruction": observation.instruction,
            "images": deepcopy(dict(observation.images)),
            "state": None if observation.state is None else list(observation.state),
            "control_feedback": deepcopy(observation.control_feedback),
            "observation_spec": client.observation_spec.to_dict(),
            "action_spec": client.action_spec.to_dict(),
            "counters": {"policy_calls": calls, "action_decisions": controls,
                         "environment_steps": controls}}


def _reply(value):
    if (type(value) is not dict or set(value) - {"action", "stop", "reason", "usage", "component_usage", "note"}
            or (("action" in value) == ("stop" in value))):
        raise ProtocolError("callback must return one action or explicit stop")
    if "stop" in value and (value["stop"] is not True or not isinstance(value.get("reason"), str)
                              or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value["reason"])):
        raise ProtocolError("callback stop requires a bounded reason code")
    if "action" in value and "reason" in value:
        raise ProtocolError("reason is only used for a stop")
    if value.get("note") is not None and (not isinstance(value["note"], str) or len(value["note"]) > 4096):
        raise ProtocolError("callback note must be bounded text")
    return value


def run_one(client, decide, *, seed: int, method: dict, output_dir: Path,
            run_id: str, recording: RecordingOptions = RecordingOptions()) -> Path:
    """Own a narrow decision loop around an already connected trusted client.

    This is an educational single-case example, not a replacement scheduler.
    ``decide(public_input)`` returns a plain dict; it may implement its own model
    composition/IPC/planning. It is responsible for projecting to an isolated
    actor; a Python callback in this process is not a security boundary.
    """
    if not callable(decide) or not isinstance(recording, RecordingOptions):
        raise ValueError("a callable bridge and RecordingOptions are required")
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", run_id):
        raise ValueError("invalid run ID")
    method = normalize_method(method)
    episodes = tuple(client.episodes(seed))  # Fixed entire schedule, before a claim.
    cap, call_cap = client.environment_step_cap, client.max_policy_calls
    if (len(episodes) != 1 or type(cap) is not int or cap <= 0
            or call_cap is not None and (type(call_cap) is not int or call_cap <= 0)
            or getattr(client, "required_replan_interval", None) not in (None, 1)):
        raise ValueError("example requires one complete scheduled case and a finite horizon with prefix 1")
    if (client.observation_spec.privileged or
            set(client.observation_spec.modalities) - {"language", "rgb", "state"}):
        raise ValueError("example cannot represent this observation contract")
    root = Path(output_dir).absolute()
    if any(path.is_symlink() for path in (root, *root.parents)):
        raise ValueError("result directory must not contain symlinks")
    root.mkdir(parents=True, exist_ok=False)
    episode = episodes[0]
    task_slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", episode.task).strip(".-")[:100] or "task"
    episode_dir = root / "episodes" / (task_slug + "-single-case")
    episode_dir.mkdir(parents=True)
    artifacts_dir = episode_dir / "artifacts"
    artifacts_dir.mkdir()
    settings = {**recording.to_dict(), "source_capture": "not requested by this educational driver"}
    policy = {"name": method["id"], "kind": "external-method", "version": method["version"],
              "model": None, "provider": None}
    atomic_write_json(root / "manifest.json", {
        "schema_version": "starvla-rsi.eval/v1", "run_id": run_id, "created_at": utc_now(),
        "benchmark": client.descriptor.to_dict(), "policy": policy, "method": method,
        "method_origin": "participant_declaration", "recording": settings,
        "observation_spec": client.observation_spec.to_dict(), "action_spec": client.action_spec.to_dict(),
        "protocol": {"seed": seed, "episode_ids": [episode.id], "max_steps": cap,
                     "max_policy_calls": call_cap, "replan_interval": 1,
                     "invalid_action_handling": "terminate", "fail_fast": False,
                     "usage_accounting_version": "starvla-rsi.method-usage/v2"},
        "driver": {"kind": "educational_single_case", "actor_isolation": "not_enforced",
                   "interaction_format": "example_callback_events_not_reference_policy_ledger"}}, overwrite=False)
    atomic_write_json(root / "status.json", {"status": "running", "episodes_written": 0})
    sink = InteractionRecorder(episode_dir / "callback_events.jsonl", recording)
    calls = controls = rejected = 0
    usage = Usage()
    components = {row["id"]: Usage().to_dict() for row in method["models"]}
    session = None
    metrics, artifacts, error = {}, {}, None
    reason, phase, uncertain = "unknown", "infrastructure", False
    started = time.monotonic()
    try:
        session = client.open_episode(episode)
        session.configure_recording(recording)
        session.bind_artifact_dir(artifacts_dir)
        observation = session.reset()
        while controls < cap and (call_cap is None or calls < call_cap):
            actor_input = _public_input(observation, client, calls, controls)
            phase = "policy"
            calls += 1
            sink.record("model_io", {"kind": "callback_input_summary_not_provider_transcript",
                **{k: v for k, v in actor_input.items() if k != "images"},
                "camera_names": list(actor_input["images"])}, policy_call=calls)
            try:
                response = decide(actor_input)
            except Exception:
                usage = usage + Usage.unavailable()
                components = sum_component_usage(components, None, method)
                raise
            phase = "protocol"
            try:
                reported = normalize_usage(response.get("usage") if type(response) is dict else None)
                component = normalize_component_usage(
                    response.get("component_usage") if type(response) is dict else None, method)
            except (ValueError, TypeError, OverflowError):
                reported, component = normalize_usage(None), normalize_component_usage(None, method)
                sink.warn("invalid_usage_unavailable")
            usage = usage + Usage(**reported)
            components = sum_component_usage(components, component, method)
            response = _reply(response)
            sink.record("model_io", {"kind": "callback_output_not_provider_transcript",
                        "stop": response.get("stop", False), "action": response.get("action"),
                        "reason": response.get("reason"), "note": response.get("note")}, policy_call=calls)
            if response.get("stop"):
                reason = "policy:" + response["reason"]
                break
            phase = "infrastructure"
            uncertain = True
            try:
                transition = session.step(response["action"])
            except ActionRejected:
                rejected += 1
                uncertain, phase = False, "protocol"
                raise
            uncertain = False
            controls += 1
            observation = transition.observation
            sink.event(episode_dir / "robot_events.jsonl", {"event": "example_control_ack",
                "policy_call": calls, "environment_step": controls,
                "action": response["action"], "state": None if observation.state is None else list(observation.state),
                "control_feedback": observation.control_feedback})
            if transition.terminated or transition.truncated:
                reason = "environment:terminated" if transition.terminated else "environment:truncated"
                break
        else:
            reason = "driver:control_limit" if controls >= cap else "driver:declared_call_limit"
        phase = "infrastructure"
        metrics = ensure_jsonable(session.metrics())  # Evaluator-only, after the final decision.
        if not isinstance(metrics, dict) or type(metrics.get("success")) is not bool:
            raise ProtocolError("native outcome did not provide boolean success")
    except Exception as exc:
        error = {"category": phase, "type": type(exc).__name__, "execution_uncertain": uncertain}
        reason = "error:" + phase
    finally:
        if session is not None:
            for operation in ("artifacts", "close"):
                try:
                    value = getattr(session, operation)()
                    if operation == "artifacts":
                        artifacts = ensure_jsonable(value)
                except Exception as exc:
                    cleanup = {"category": "infrastructure", "type": type(exc).__name__, "operation": operation}
                    if error is None:
                        error, reason = cleanup, "error:infrastructure"
                    else:
                        error.setdefault("cleanup_errors", []).append(cleanup)
    result = {"schema_version": "starvla-rsi.eval/v1", "episode": episode.to_dict(),
        "status": "error" if error else "completed", "success": None if error else metrics["success"],
        "termination_reason": reason, "policy_calls": calls, "action_decisions": controls,
        "environment_steps": controls, "rejected_actions": rejected,
        "duration_s": time.monotonic() - started, "usage": usage.to_dict(), "component_usage": components,
        "usage_reported_complete": None, "usage_inconsistent_fields": None,  # no episode_usage hook here
        "metrics": metrics, "artifacts": artifacts, "error": error,
        "recording": {**settings, "agent_events_written": sink.events_written, "warnings": sink.warnings}}
    atomic_write_json(episode_dir / "result.json", result, overwrite=False)
    append_jsonl(root / "episodes.jsonl", result)
    summary = summarize_run(run_id, client.descriptor.name, policy["name"], [result])
    summary["component_usage"] = components
    atomic_write_json(root / "summary.json", summary, overwrite=False)
    atomic_write_json(root / "status.json", {"status": "completed_with_errors" if error else "completed",
                                           "episodes_written": 1})
    return root
