"""Geometry-only EGL lifecycle diagnostic: no benchmark reset/control/model call.

Creates two tiny MuJoCo render contexts without asset files. Retires the first
while the second is current, optionally inside the native Python rendering /
readback flow immediately before a C entrypoint (not during C execution). This
test deliberately injects Python GC; it is not a task or model capability run.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import sys
import weakref
from pathlib import Path

from benchkit.artifacts import atomic_write_json
from .render_lifecycle import TRACK, MATERIAL_TRACK, _address, install

XML = '''<mujoco><visual><global offwidth="256" offheight="256"/></visual>
<worldbody><light pos="0 0 3"/><geom type="plane" size="2 2 .1" rgba=".3 .3 .3 1"/>
<geom type="box" pos="-.3 0 .2" size=".15 .15 .2" rgba="1 .1 .1 1"/>
<geom type="sphere" pos=".4 .2 .2" size=".2" rgba=".1 1 .1 1"/>
<camera name="front" pos="0 -2 1.5" xyaxes="1 0 0 0 .6 .8"/>
<camera name="side" pos="2 0 1.5" xyaxes="0 1 0 -.6 0 .8"/>
<camera name="top" pos="0 0 3" xyaxes="1 0 0 0 1 0"/>
</worldbody></mujoco>'''


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gpu", type=int, required=True)
    parser.add_argument("--injection", choices=("between", "render", "readback"), required=True)
    parser.add_argument("--render-track", choices=(TRACK, MATERIAL_TRACK), default=TRACK)
    args = parser.parse_args(argv)
    if args.gpu < 0:
        parser.error("gpu must be nonnegative")
    args.output.mkdir(parents=True, exist_ok=False)
    report = {
        "schema_version": "robocasa365.render-lifecycle-geometry-diagnostic/v1",
        "render_track": args.render_track, "injection": args.injection,
        "kind": "geometry_only_infrastructure_diagnostic", "capability_evaluation": False,
        "benchmark_resets": 0, "physics_steps": 0, "controls": 0, "model_calls": 0,
        "gpu": args.gpu, "diagnostic_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "scene_xml_sha256": hashlib.sha256(XML.encode()).hexdigest(),
        "status": "running", "errors": [],
    }
    atomic_write_json(args.output / "report.json", report)
    guard = active = active_ctx = retired = retired_ctx = None
    old_function = injection_name = None
    was_gc_enabled = gc.isenabled()
    try:
        from ..bench_server.adapter import verify_sources
        provenance = verify_sources()
        report["native_sources"] = provenance
        guard = install(args.output / "render_lifecycle.json", Path(provenance["sources"]["robosuite"]["root"]),
                        track=args.render_track)
        import mujoco
        import numpy as np
        from PIL import Image
        from robosuite.utils.binding_utils import MjSim, MjRenderContextOffscreen
        gc.disable()
        retired = MjSim.from_xml_string(XML)
        retired_ctx = MjRenderContextOffscreen(retired, device_id=args.gpu, max_width=256, max_height=256)
        retired.render(256, 256, camera_name="front")
        retired_weak = weakref.ref(retired_ctx)
        active = MjSim.from_xml_string(XML)
        active_ctx = MjRenderContextOffscreen(active, device_id=args.gpu, max_width=256, max_height=256)

        def binding():
            snapshot = guard._snapshot()
            return dict(zip(("display", "context", "draw_surface", "read_surface", "api"),
                            [*map(_address, snapshot[:4]), int(snapshot[4])]))

        def capture(label):
            pixels_by_camera, rows = {}, []
            for camera in ("front", "side", "top"):
                pixels = active.render(256, 256, camera_name=camera)
                guard.check("geometry_capture", persist=True)
                path = args.output / f"{label}-{camera}.png"
                Image.fromarray(pixels).save(path)
                pixels_by_camera[camera] = pixels.copy()
                rows.append({"camera": camera, "rgb_sha256": hashlib.sha256(pixels.tobytes()).hexdigest(),
                             "png": path.name, "png_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                             "binding": binding()})
            return pixels_by_camera, rows

        before, report["before"] = capture("before")
        retired = retired_ctx = None  # Only the native sim/render cycle remains.
        injection = {"calls": 0}

        def collect():
            if injection["calls"]:
                return
            injection["calls"] += 1
            injection["before_binding"] = binding()
            injection["fbo_before"] = bool(guard.gl.glIsFramebuffer(int(active_ctx.con.offFBO)))
            injection["objects_collected"] = gc.collect()
            # Do not make the active context current here: that would conceal
            # failed restoration by the finalizer under test.
            injection["after_binding"] = binding()
            injection["fbo_after"] = bool(guard.gl.glIsFramebuffer(int(active_ctx.con.offFBO)))
            injection["retired_context_collected"] = retired_weak() is None
            injection["gl_error_after_collection"] = int(guard.gl.glGetError())
            guard.check("after_injected_gc", persist=True)
            if (injection["before_binding"] != injection["after_binding"]
                    or not injection["fbo_before"] or not injection["fbo_after"]
                    or not injection["retired_context_collected"] or injection["gl_error_after_collection"]):
                raise RuntimeError("injected cleanup changed live EGL state/framebuffer or failed collection")

        report["injected_collection"] = injection
        if args.injection == "between":
            collect()
        else:
            after_scene_update = args.injection == "render" and args.render_track == MATERIAL_TRACK
            injection_name = ("mjv_updateScene" if after_scene_update else
                              "mjr_render" if args.injection == "render" else "mjr_readPixels")
            report["injection_entrypoint"] = injection_name
            report["injection_position"] = "after_native_scene_update" if after_scene_update else "before_native_entrypoint"
            old_function = getattr(mujoco, injection_name)
            def injected(*native_args, **native_kwargs):
                if after_scene_update:
                    result = old_function(*native_args, **native_kwargs)
                    collect()
                    return result
                collect()
                return old_function(*native_args, **native_kwargs)
            setattr(mujoco, injection_name, injected)
        after, report["after"] = capture("after")
        report["rgb_byte_equal"] = {name: bool(np.array_equal(before[name], after[name])) for name in before}
        report["distinct_camera_count"] = len({hashlib.sha256(p.tobytes()).hexdigest() for p in before.values()})
        if (injection["calls"] != 1 or not all(report["rgb_byte_equal"].values())
                or report["distinct_camera_count"] != 3):
            raise RuntimeError("geometry RGB invariance or distinct-camera diagnostic failed")
        report["status"] = "passed"
    except Exception as exc:
        report["status"] = "failed"
        report["errors"].append({"phase": "diagnostic", "type": type(exc).__name__, "message": str(exc)})
    finally:
        if old_function is not None:
            setattr(sys.modules["mujoco"], injection_name, old_function)
        # No benchmark environment exists. Release only these synthetic owners.
        active_ctx = retired_ctx = None
        for sim in (active, retired):
            if sim is not None:
                try:
                    sim.free()
                except Exception as exc:
                    report["status"] = "failed"
                    report["errors"].append({"phase": "geometry_cleanup", "type": type(exc).__name__, "message": str(exc)})
        active = retired = None
        gc.collect()
        if guard is not None:
            try:
                guard.finish()
            except Exception as exc:
                report["status"] = "failed"
                report["errors"].append({"phase": "guard_cleanup", "type": type(exc).__name__, "message": str(exc)})
            report["guard_final"] = guard.receipt()
        if was_gc_enabled:
            gc.enable()
        atomic_write_json(args.output / "report.json", report)
    print(json.dumps({"status": report["status"], "output": str(args.output), "benchmark_resets": 0,
                      "controls": 0, "model_calls": 0}), flush=True)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
