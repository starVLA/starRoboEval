"""Typed failures used to distinguish protocol, policy, and infrastructure errors."""

from __future__ import annotations

import json
from typing import Mapping

from benchkit.contracts import JsonValue, Usage, ensure_jsonable
from benchkit.validation import ValidationIssue


class EvaluationError(RuntimeError):
    """Base class for evaluation failures."""


class CompatibilityError(EvaluationError):
    """The policy and benchmark contracts are incompatible before rollout."""


class ProtocolError(EvaluationError):
    """An adapter or policy violated the declared evaluation contract."""


class PolicyError(EvaluationError):
    """The evaluated policy failed to produce a valid decision."""


class PolicyPreflightError(EvaluationError):
    """A local-readiness failure, not a policy call or an evaluation attempt.

    Closed codes keep dependency/credential exceptions out of CLI diagnostics.
    This check does not validate credentials remotely or attest provider access.
    """

    CODES = frozenset({"credentials_missing", "dependency_unavailable",
                       "initialization_failed", "unsupported"})

    def __init__(self, code: str) -> None:
        if not isinstance(code, str) or code not in self.CODES:
            code = "initialization_failed"
        super().__init__("Policy runtime preflight: " + code)
        self.code = code


class PolicyCallError(EvaluationError):
    """Failed act with retained accounting, never a decision or a stop.

    Callers must supply a sanitized message and receipt metadata only: no raw
    response/error bodies, credentials, or hidden reasoning. The runner does not
    serialize this exception's traceback or chained provider exceptions. Receipt
    metadata is copied and limited to 16 KiB of finite JSON; this is a storage
    bound, not a provider-identity or accounting attestation.
    """

    MAX_METADATA_BYTES = 16 * 1024

    def __init__(self, message: str, *, usage: Usage,
                 metadata: Mapping[str, JsonValue] | None = None, category: str = "policy") -> None:
        if not isinstance(message, str) or not message.strip() or len(message) > 1024:
            raise ValueError("policy-call error needs a nonempty sanitized message of at most 1024 characters")
        if category not in ("policy", "infrastructure"):
            raise ValueError("policy-call error category must be policy or infrastructure")
        if not isinstance(usage, Usage):
            raise TypeError("policy-call error usage must be Usage")
        if metadata is not None and not isinstance(metadata, Mapping):
            raise TypeError("policy-call error metadata must be a JSON object")
        try:
            receipt = ensure_jsonable(metadata if metadata is not None else {})
            encoded = json.dumps(receipt, allow_nan=False, separators=(",", ":"))
        except (TypeError, ValueError, RecursionError) as exc:
            raise ValueError("policy-call error metadata must be finite JSON") from exc
        if len(encoded.encode("utf-8")) > self.MAX_METADATA_BYTES:
            raise ValueError("policy-call error metadata exceeds 16 KiB")
        super().__init__(message)
        self.usage = Usage(**usage.to_dict())
        self.metadata = json.loads(encoded)
        self.category = category


class InfrastructureError(EvaluationError):
    """The simulator, hardware, asset, or transport layer failed."""


class ActionRejected(PolicyCallError):
    """Deterministic invalid input, with no execution of the rejected control.

    Only ``issue`` crosses the actor feedback boundary. Sanitized receipt
    metadata is evaluator-private, and follows PolicyCallError's copy/size
    checks. Service-side validation uses zero Usage; model parsing must retain
    the one failed call's real or explicitly unavailable usage.
    """

    def __init__(self, issue: ValidationIssue, *, usage: Usage = Usage(),
                 metadata: Mapping[str, JsonValue] | None = None) -> None:
        if not isinstance(issue, ValidationIssue):
            raise TypeError("action rejection requires a ValidationIssue")
        self.issue = ValidationIssue.from_dict(issue.to_dict())
        super().__init__("Action rejected: " + self.issue.code, usage=usage,
                         metadata=metadata, category="policy")
