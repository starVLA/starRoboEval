#!/usr/bin/env python3
"""Verify a minimal SimplerEnv installation without invoking a policy."""

from __future__ import annotations

import argparse
import copy
import json
from typing import Any


def _shape(value: Any) -> list[int] | None:
    shape = getattr(value, "shape", None)
    return None if shape is None else [int(item) for item in shape]


def check_cached_render(env: Any, image: Any) -> dict[str, Any]:
    """Infrastructure-only check of the scheduled image and cached raw Color.

    The photographic overlay can conceal an entirely black native render.
    Never acquire another picture or query the scorer to perform this check.
    This helper is not a policy observation or a capability/parity certificate.
    """
    import numpy as np

    rgb = np.asarray(image)
    if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[-1] != 3 or not rgb.size:
        raise ValueError("scheduled RGB must be a nonempty H x W x 3 uint8 array")
    native = env.unwrapped
    if "google_robot" in native.robot_uid:
        camera = "overhead_camera"
    elif "widowx" in native.robot_uid:
        camera = "3rd_view_camera"
    else:
        raise ValueError("unknown native robot camera mapping")
    buffers = native._cameras[camera].get_images(take_picture=False)
    color = np.asarray(buffers["Color"])
    if color.ndim != 3 or color.shape[:2] != rgb.shape[:2] or color.shape[-1] != 4:
        raise ValueError("cached native Color must match scheduled RGB dimensions")
    raw_rgb = color[..., :3]
    if not np.issubdtype(raw_rgb.dtype, np.number) or not np.isfinite(raw_rgb).all():
        raise ValueError("cached native Color contains nonnumeric or nonfinite values")
    if not np.any(raw_rgb != 0):
        raise ValueError(
            "cached native Color is entirely zero: a photographic overlay can hide "
            "this rendering failure; inspect native OptiX logs and matching driver "
            "denoiser data before any model trial"
        )
    return {
        "camera": camera,
        "cached_raw_color_shape": _shape(color),
        "cached_raw_color_finite": True,
        "cached_raw_rgb_nonzero_values": int(np.count_nonzero(raw_rgb)),
        "cached_raw_rgb_min": float(raw_rgb.min()),
        "cached_raw_rgb_max": float(raw_rgb.max()),
        "extra_picture_acquisitions": 0,
        "extra_scorer_requests": 0,
        "limitation": "Detects missing/nonfinite/all-zero cached RGB only; not task foreground quality or native parity certification.",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", default="widowx_spoon_on_towel")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--steps", type=int, default=1, help="diagnostic constant-action steps, not model evaluation")
    parser.add_argument("--list", action="store_true", help="list installed task names and exit")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not 0 <= args.steps <= 5:
        raise SystemExit("diagnostic --steps must be between 0 and 5")
    try:
        import gymnasium as gym
        import numpy as np
        import simpler_env
        from simpler_env.utils.env.observation_utils import (
            get_image_from_maniskill2_obs_dict,
        )
    except Exception as exc:
        raise SystemExit(
            "SimplerEnv import failed. Activate starvla-rsi-simpler and follow "
            f"benchmarks/simBenchmarks/SimplerEnv/README.md. Root cause: {type(exc).__name__}: {exc}"
        ) from exc

    available = tuple(sorted(str(name) for name in simpler_env.ENVIRONMENTS))
    if args.list:
        print("\n".join(available))
        return 0
    if args.task not in available:
        raise SystemExit(
            f"unknown task {args.task!r}; run with --list to inspect this installation"
        )

    env = None
    try:
        env_id, options = simpler_env.ENVIRONMENT_MAP[args.task]
        options = copy.deepcopy(options)
        options.update(obs_mode="rgbd", prepackaged_config=True)
        env = gym.make(env_id, **options)
        observation, _ = env.reset(seed=args.seed)
        image = get_image_from_maniskill2_obs_dict(env, observation)
        render_checks = [check_cached_render(env, image)]
        for _ in range(args.steps):
            observation, _, _, _, _ = env.step(np.zeros(env.action_space.shape, dtype=np.float32))
            image = get_image_from_maniskill2_obs_dict(env, observation)
            render_checks.append(check_cached_render(env, image))
        report = {
            "status": "ok",
            "task": args.task,
            "instruction": env.unwrapped.get_language_instruction(),
            "image_shape": _shape(image),
            "action_shape": _shape(env.action_space),
            "diagnostic_steps": args.steps,
            "available_task_count": len(available),
            "render_checks": render_checks,
        }
        print(json.dumps(report, indent=2, sort_keys=True))
    except Exception as exc:
        raise SystemExit(
            "SimplerEnv reset/render check failed. Verify recursive submodules, GPU "
            f"visibility, Vulkan/SAPIEN, and assets. Root cause: {type(exc).__name__}: {exc}"
        ) from exc
    finally:
        if env is not None:
            env.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
