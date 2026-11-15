"""Connect-level readiness probe for one running benchmark service.

describe -> claim one episode -> reset -> finish. No policy runs and no action
is sent: the wire protocol declares no neutral action, so the probe stops after
reset. The claim is permanent, so probe a dedicated service launch (for example
`evaluation_mode: example` or `--episodes 1`), never a scored schedule.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import secrets
import time
from typing import Any

from benchkit.errors import CompatibilityError, InfrastructureError, PolicyError, ProtocolError

_SIM_PREFIX = "SIM server: "  # client failures carry closed codes after this prefix


def _error(exc: BaseException, phase: str) -> dict[str, Any]:
    """Classify a failure without echoing remote text or the credential."""
    if isinstance(exc, InfrastructureError):
        kind = "infrastructure"
    elif isinstance(exc, ProtocolError):
        kind = "protocol"
    elif isinstance(exc, CompatibilityError):
        kind = "compatibility"
    elif isinstance(exc, PolicyError):
        kind = "policy"  # unreachable: the probe runs no policy
    else:
        kind = "infrastructure"  # local/unexpected failures are never policy outcomes
    message = str(exc)
    code = message[len(_SIM_PREFIX):] if message.startswith(_SIM_PREFIX) else type(exc).__name__
    return {"class": kind, "code": code, "phase": phase}


def _source_identity(source: Any, expected: str | None) -> dict[str, Any]:
    """Compare against a pin when one is given; otherwise record the hash as unpinned."""
    digest = hashlib.sha256(json.dumps(source, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if expected is None:
        return {"sha256": digest, "pin": "unpinned"}
    return {"sha256": digest, "pin": "match" if digest == expected.lower() else "mismatch"}


def probe(endpoint: str, token: str, benchmark: str, *, output_dir: Path, timeout: float,
          episode_id: str | None = None, expect_source_sha256: str | None = None) -> dict[str, Any]:
    """Run the probe and return its JSON-ready summary; never raises for service faults."""
    from benchkit.sim_server.client import SimServerBenchmarkAdapter

    summary: dict[str, Any] = {"status": "failed", "benchmark": benchmark, "error": None,
                               "steps": 0, "step_skipped": "no declared neutral action"}
    timings: dict[str, float] = {}
    summary["timings_s"] = timings
    phase, episode = "describe", None
    try:
        started = time.monotonic()
        adapter = SimServerBenchmarkAdapter(endpoint, token=token, timeout=timeout)
        timings["describe"] = round(time.monotonic() - started, 3)
        data = adapter.describe_data
        summary["identity"] = {"server_id": data["server_id"], **data["descriptor"],
                               "source": _source_identity(data["source"], expect_source_sha256)}
        summary["evaluation_mode"] = data["parameters"].get("evaluation_mode")  # null: not declared
        summary["episodes"] = len(data["episodes"])
        summary["schedule_size"] = data.get("selection", {}).get("schedule_size", len(data["episodes"]))
        summary["budget"] = dict(data["budget"])
        phase = "identity"
        if adapter.descriptor.name != benchmark:
            raise CompatibilityError("--benchmark differs from the service's descriptor.name")
        if summary["identity"]["source"]["pin"] == "mismatch":
            raise CompatibilityError("service source differs from --expect-source-sha256")

        phase = "claim"
        schedule = adapter.episodes(data["seed"])
        chosen = [e for e in schedule if episode_id in (None, e.id)][:1]
        if not chosen:
            raise CompatibilityError("--episode-id is not in the served schedule")
        spec = chosen[0]
        summary["episode"] = {"id": spec.id, "task": spec.task,
                              "environment_step_cap": spec.metadata.get("environment_step_cap")}
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        artifact_dir = output_dir.absolute() / f"probe-{stamp}-{secrets.token_hex(3)}"
        artifact_dir.mkdir(parents=True)
        summary["artifact_dir"] = str(artifact_dir)
        started = time.monotonic()
        episode = adapter.open_episode(spec)
        episode.bind_artifact_dir(artifact_dir)
        timings["claim"] = round(time.monotonic() - started, 3)

        phase = "reset"
        started = time.monotonic()
        observation = episode.reset()
        timings["reset"] = round(time.monotonic() - started, 3)
        summary["observation"] = {
            "cameras": {name: list(getattr(image, "shape", ())) for name, image in observation.images.items()},
            "state_size": None if observation.state is None else len(observation.state),
            "control_feedback": observation.control_feedback is not None}

        phase = "close"
        started = time.monotonic()
        episode.close()  # finish: closed artifacts plus sim_server_receipt.json
        timings["close"] = round(time.monotonic() - started, 3)
        summary["status"] = "passed"
    except Exception as exc:
        summary["error"] = _error(exc, phase)
        if episode is not None and phase != "close":
            try:  # one cleanup attempt; the client forbids a second finish
                episode.close()
            except Exception as cleanup:
                summary["cleanup_error"] = _error(cleanup, "close")
    return summary
