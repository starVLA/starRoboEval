"""Bounded, correlated private worker. No credentials, decisions, or action retry."""
from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path
import sys
import traceback

MAX_LINE_BYTES = 16 * 1024 * 1024


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_field")
        result[key] = value
    return result


def _constant(value):
    raise ValueError("nonfinite_json")


def dispatch(runtime, operation, params):
    if type(params) is not dict:
        raise ValueError("invalid_worker_parameters")
    if operation == "step":
        if set(params) != {"action"}:
            raise ValueError("invalid_worker_parameters")
        return runtime.step(params["action"])
    if params or operation not in ("reset", "metrics", "finish", "close"):
        raise ValueError("invalid_worker_operation")
    if operation == "close":
        return runtime.finish()
    return getattr(runtime, operation)()


def serve(runtime, input_stream, output_stream):
    expected = 1
    while True:
        raw = input_stream.readline(MAX_LINE_BYTES + 1)
        if not raw:
            return 0
        if len(raw) > MAX_LINE_BYTES or not raw.endswith(b"\n"):
            return 2
        try:
            request = json.loads(raw, object_pairs_hook=_object, parse_constant=_constant)
            if (type(request) is not dict or set(request) != {"id", "op", "params"}
                    or type(request["id"]) is not int or request["id"] != expected
                    or not isinstance(request["op"], str)):
                return 2
        except (ValueError, UnicodeError):
            return 2
        expected += 1
        try:
            result = dispatch(runtime, request["op"], request["params"])
            response = {"id": request["id"], "ok": True, "result": result}
        except Exception as exc:
            # Full diagnostics remain evaluator-private stderr, never actor input.
            traceback.print_exc(file=sys.stderr)
            response = {"id": request["id"], "ok": False,
                        "error": {"type": type(exc).__name__, "code": "native_operation_failed"}}
        encoded = json.dumps(response, allow_nan=False, separators=(",", ":")).encode() + b"\n"
        if len(encoded) > MAX_LINE_BYTES:
            return 2
        output_stream.write(encoded)
        output_stream.flush()
        if request["op"] == "close":
            return 0 if response["ok"] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args(argv)
    # Duplicate the protocol channel before importing any native package.
    protocol = os.fdopen(os.dup(sys.stdout.fileno()), "wb", buffering=0)
    sys.stdout.flush()
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    module = importlib.import_module("benchmarks.simBenchmarks.VLN-CE.environment.native_runtime")
    runtime = module.NativeRuntime(json.loads(args.config.read_text()))
    try:
        return serve(runtime, sys.stdin.buffer, protocol)
    finally:
        try:
            runtime.finish()
        except Exception:
            traceback.print_exc(file=sys.stderr)
        protocol.close()


if __name__ == "__main__":
    raise SystemExit(main())
