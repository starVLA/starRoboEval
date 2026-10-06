"""Fixed zero-action mailbox v2 client; infrastructure check, never a model score.

This process reads only its current mailbox request and referenced RGB images.
It does not import the harness, native simulator, task catalog or scorer.
"""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import time


def public_path(root, relative):
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("v2 path must be mailbox-root relative")
    resolved = (root / path).resolve()
    if root not in resolved.parents:
        raise ValueError("path escapes mailbox root")
    return resolved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--decisions", type=int, default=2)
    parser.add_argument("--chunk-size", type=int, default=1)
    parser.add_argument("--timeout-s", type=float, default=300)
    args = parser.parse_args()
    if args.decisions < 1 or not 1 <= args.chunk_size <= 5 or not 0 < args.timeout_s <= 3600:
        parser.error("positive decisions, chunk-size 1..5 and timeout 0..3600 required")
    from PIL import Image

    root = args.directory.resolve()
    deadline = time.monotonic() + args.timeout_s
    seen = set()
    images_checked = 0
    while time.monotonic() < deadline:
        ready_path = root / "ready.json"
        if not ready_path.exists():
            time.sleep(0.05)
            continue
        ready = json.loads(ready_path.read_text())
        if ready["schema_version"] != "starvla-rsi.mailbox/v2":
            raise ValueError("this diagnostic only supports mailbox v2")
        if ready["status"] == "failed":
            raise RuntimeError("evaluator reported failed decision")
        if ready["status"] == "episode_closed":
            print(json.dumps({"kind": "fixed_zero_action_diagnostic_not_model_score",
                              "submitted_decisions": len(seen), "images_checked": images_checked,
                              "provider_calls": 0, "native_success": None}))
            return
        if ready["status"] != "pending" or ready["request_id"] in seen:
            time.sleep(0.05)
            continue
        if len(seen) >= args.decisions:
            raise RuntimeError("evaluator requested more than declared diagnostic decisions")
        observation = json.loads(public_path(root, ready["observation_path"]).read_text())
        if observation["request_id"] != ready["request_id"]:
            raise ValueError("request/observation mismatch")
        budgets = observation["budgets"]
        if (budgets["max_policy_calls"] != args.decisions
                or budgets["replan_interval"] != args.chunk_size
                or budgets["primary_budget"] != "policy_decisions"):
            raise ValueError("diagnostic requires matching decision-primary budgets")
        for frame in observation["images"].values():
            data = public_path(root, frame["path"]).read_bytes()
            if hashlib.sha256(data).hexdigest() != frame["sha256"]:
                raise ValueError("RGB hash mismatch")
            with Image.open(io.BytesIO(data)) as image:
                image.load()
                if image.mode != "RGB":
                    raise ValueError("diagnostic expects RGB PNG")
            images_checked += 1
        response = public_path(root, ready["response_path"])
        temporary = response.with_suffix(".diagnostic-tmp")
        with temporary.open("x") as stream:
            json.dump({"request_id": ready["request_id"],
                       "actions": [[0.0] * 7 for _ in range(args.chunk_size)],
                       "usage": {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                                 "cached_input_tokens": 0, "estimated_cost_usd": 0},
                       "note": "Fixed zero-action infrastructure diagnostic, no model."}, stream)
        os.replace(temporary, response)
        seen.add(ready["request_id"])
    raise TimeoutError("diagnostic deadline exceeded")


if __name__ == "__main__":
    main()
