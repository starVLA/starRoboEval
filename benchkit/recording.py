"""Optional retention preferences and best-effort agent interaction records.

These switches never change model inputs, robot actions, lifecycle or scoring.
They apply to the client-owned record; a separately deployed benchmark service
may retain its own native artifacts. Provider integrations decide which visible
inputs/outputs they can record. No hidden reasoning is requested by this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from benchkit.artifacts import append_jsonl, utc_now
from benchkit.contracts import ensure_jsonable

SCHEMA = "starvla-rsi.recording/v2"
FIELDS = ("interactions", "model_io", "tool_traces", "images", "videos")


@dataclass(frozen=True)
class RecordingOptions:
    """Resolved retention settings; explicit switches override the preset."""

    mode: str = "standard"
    interactions: bool | None = None
    model_io: bool | None = None
    tool_traces: bool | None = None
    images: bool | None = None
    videos: bool | None = None
    copy_server_media: bool = False

    def __post_init__(self):
        if self.mode not in ("standard", "minimal"):
            raise ValueError("recording mode must be standard or minimal")
        for name in FIELDS:
            value = getattr(self, name)
            if value is not None and type(value) is not bool:
                raise ValueError(f"recording {name} must be a boolean or None")
            object.__setattr__(self, name, self.mode == "standard" and name != "images" if value is None else value)
        if type(self.copy_server_media) is not bool:
            raise ValueError("copy_server_media must be a boolean")

    @property
    def retain_all(self) -> bool:
        return all(getattr(self, name) for name in FIELDS)

    @property
    def retain_unknown_artifacts(self) -> bool:
        """Avoid discarding opaque provenance solely because frames are disabled."""
        return self.interactions and self.model_io and self.tool_traces

    def to_dict(self) -> dict:
        return {"schema_version": SCHEMA, "mode": self.mode,
                **{name: getattr(self, name) for name in FIELDS},
                "copy_server_media": self.copy_server_media,
                "scope": "server-owned media referenced by client; optional client copies; live inputs unchanged",
                "source_capture": "internal source/config snapshots retained independently of preset"}


class InteractionRecorder:
    """Opt-in SDK sink for visible model/tool events, never a model proxy.

The caller supplies actual visible data and must exclude credentials, hidden
reasoning and evaluator-private information. Bounded I/O failures are recorded
as warnings instead of changing robot execution. Missing records are not a
publication gate. Full contents should be reviewed before sharing.
"""

    def __init__(self, path: Path, options: RecordingOptions):
        self.path, self.options = Path(path), options
        self.warnings: list[str] = []
        self.events_written = 0

    def warn(self, code: str) -> None:
        if code not in self.warnings and len(self.warnings) < 16:
            self.warnings.append(code)

    def record(self, category: str, payload: Mapping, *, policy_call: int | None = None) -> bool:
        if category not in ("model_io", "tool_traces", "memory"):
            raise ValueError("interaction category must be model_io, tool_traces or memory")
        enabled = self.options.tool_traces if category == "tool_traces" else self.options.model_io
        if not enabled:
            return False
        try:
            value = ensure_jsonable(payload)
            if not isinstance(value, dict):
                raise ValueError("interaction payload must be an object")
            if policy_call is not None and (type(policy_call) is not int or policy_call <= 0):
                raise ValueError("policy_call must be a positive integer")
            import json
            if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > 1024 * 1024:
                self.warn("interaction_payload_too_large")
                return False
            append_jsonl(self.path, {"schema_version": "starvla-rsi.agent-interaction/v1",
                "timestamp": utc_now(), "category": category, "policy_call": policy_call,
                "payload": value})
            self.events_written += 1
            return True
        except (OSError, TypeError, ValueError, RecursionError, OverflowError):
            self.warn("interaction_recording_failed")
            return False

    def event(self, path: Path, payload: Mapping) -> None:
        """Retain generic robot trajectory events only when selected."""
        if not self.options.interactions:
            return
        try:
            event = dict(payload)
            if not self.options.model_io:
                if event.get("event") == "policy_decision":
                    event["note"] = ""
                    event["metadata"] = {}
                elif event.get("event") == "action_rejected":
                    event["metadata"] = {}
                elif event.get("event") in ("error", "artifact_error"):
                    event["error"] = public_error_record(event["error"], self.options)
            append_jsonl(path, event)
        except (OSError, TypeError, ValueError, RecursionError, OverflowError):
            self.warn("trajectory_recording_failed")


def public_error_record(error, options: RecordingOptions):
    """Remove optional metadata from required error accounting, not redaction.

    Error messages/tracebacks are still private diagnostics and may contain
    participant text. Public reports must project bounded fields, not publish
    this object wholesale. Recording switches are not secret sanitizers.
    """
    if error is None or options.model_io:
        return error
    return {key: (public_error_record(value, options) if isinstance(value, dict) else value)
            for key, value in error.items() if key != "metadata"}


def add_recording_arguments(parser) -> None:
    import argparse
    parser.add_argument("--recording-mode", choices=("standard", "minimal"), default="standard",
                        help="client retention preset; never changes model inputs or benchmark scoring")
    for name in FIELDS:
        parser.add_argument("--record-" + name.replace("_", "-"), dest="record_" + name,
                            action=argparse.BooleanOptionalAction, default=None,
                            help="override client retention of " + name.replace("_", " "))
    parser.add_argument("--copy-server-media", action=argparse.BooleanOptionalAction, default=False,
                        help="also download selected server images/videos; default keeps references, not duplicate media")


def recording_from_arguments(args) -> RecordingOptions:
    return RecordingOptions(mode=args.recording_mode,
                            **{name: getattr(args, "record_" + name) for name in FIELDS},
                            copy_server_media=getattr(args, "copy_server_media", False))
