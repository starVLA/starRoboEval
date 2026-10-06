"""Explicit single-invocation, asset-free Codex transport diagnostic, never a score."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import time

from benchkit.artifacts import atomic_write_json
from benchkit.errors import PolicyCallError, PolicyPreflightError
from AgentPolicies.gpt6_astra.transports.codex_cli import preflight_runtime, send


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new, unused diagnostic directory")
    parser.add_argument("--request", action="store_true", help="explicitly permit one synthetic CLI invocation")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    record = {"schema_version": "starvla-rsi.codex-transport-check/v1", "benchmark_attempts": 0,
              "capability_score": None, "simulator_started": False,
              "request_enabled": args.request, "status": "started", "wrapper_retries": 0,
              "source_sha256": {name: hashlib.sha256((Path(__file__).parents[1] / name).read_bytes()).hexdigest()
                                for name in ("transports/codex_cli.py", "tools/check_transport.py")}}
    atomic_write_json(args.output / "started.json", record, overwrite=False)
    started = time.monotonic()
    try:
        record["preflight"] = preflight_runtime()
        if args.request:
            import numpy as np
            from PIL import Image
            images = []
            for channel in range(3):
                array = np.zeros((8, 8, 3), dtype=np.uint8)
                array[:, :, channel] = 255
                with io.BytesIO() as buffer:
                    Image.fromarray(array).save(buffer, format="PNG")
                    images.append(buffer.getvalue())
            schema = {"type": "object", "additionalProperties": False, "required": ["ready", "image_count"],
                      "properties": {"ready": {"type": "boolean"}, "image_count": {"type": "integer"}}}
            result = send("This is an asset-free transport check, not a robot task. "
                "There are three attached synthetic color images. Return only "
                "{\"ready\":true,\"image_count\":3}. Do not use any tools.",
                images, schema, timeout_s=180, max_response_bytes=65536,
                max_attempts=1, retry_backoff_s=0)
            record["receipt"], record["usage"] = result["receipt"], result["usage"]
            value = json.loads(result["text"])
            valid = (isinstance(value, dict) and set(value) == {"ready", "image_count"}
                     and value["ready"] is True and type(value["image_count"]) is int and value["image_count"] == 3)
            record["status"] = "passed" if valid else "unexpected_synthetic_response"
            # Never retain arbitrary model text, only the closed synthetic result.
            record["synthetic_response_verified"] = valid
        else:
            record["status"] = "preflight_passed_no_inference"
    except PolicyPreflightError as exc:
        record.update(status="preflight_failed", error_code=exc.code)
    except PolicyCallError as exc:
        record.update(status="request_failed", error=str(exc), category=exc.category,
                      usage=exc.usage.to_dict(), receipt=exc.metadata)
    except Exception:
        record.update(status="diagnostic_failed", error_code="local_diagnostic_error")
    record["seconds"] = time.monotonic() - started
    atomic_write_json(args.output / "result.json", record, overwrite=False)
    print(json.dumps(record, allow_nan=False))
    return 0 if record["status"] in {"passed", "preflight_passed_no_inference"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
