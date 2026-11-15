# Native RGB reliability

The pinned RoboCasa 1.0.1 / Robosuite 1.5.2 / MuJoCo 3.3.1 EGL runtime has a
reproduced render-context lifetime defect. A successful PNG decode, a changing
timestamp or a pixel-exact HTTP transfer does not prove that a native image is
fresh or valid. This is an infrastructure qualification, not a task outcome.

## Source mechanism

RoboCasa's kitchen environment defaults to `renderer="mjviewer"` and hard reset.
Its Gym wrapper resets during construction, before the adapter's explicit reset.
In the pinned Robosuite `environments/base.py`, the `mjviewer` hard-reset branch
does not explicitly destroy the old simulator before assigning the new one.
The old simulator and offscreen renderer hold a reference cycle and can therefore
be collected later while the replacement's OpenGL context is current.

`MjRenderContext.__del__` in `utils/binding_utils.py` frees MuJoCo rendering
resources without first making their owning OpenGL context current. The EGL
cleanup also releases the calling thread's context. Resource identifiers can
overlap across contexts: freeing the retired renderer in the replacement context
can delete the replacement's framebuffer. Simply making the replacement context
current again does not restore the deleted framebuffer.

The same binding allocates RGB output with `np.empty` and does not check GL errors
after pixel readback. A failed read can consequently expose stale or uninitialized
buffer contents. This explains why an invalid frame can still be a correctly
shaped, decodable RGB array. See the [pinned binding source](https://github.com/ARISE-Initiative/robosuite/blob/85abee228d1c43ab1939bce33028099945d453b4/robosuite/utils/binding_utils.py)
and [MuJoCo's context requirements](https://mujoco.readthedocs.io/en/3.3.1/programming/visualization.html).

## Renderer lifetime failure

A separate synthetic scene used two native offscreen contexts, three cameras,
and forced collection of the retired context. It loaded no benchmark assets and
performed **zero benchmark resets, physics steps, controls or model calls**.

| Condition | Replacement framebuffer after collection | RGB evidence |
| --- | --- | --- |
| Native destructor, replacement context current | Deleted | GL errors; a prefilled readback buffer remained unchanged |
| Keep retired context alive | Preserved | All three before/after image hashes identical |
| Make retired context current before collection, then restore replacement | Preserved | All three before/after image hashes identical |

The broken path produced error 1286 after native `render()` (which includes its
first readback), then error 1282 in a separate sentinel readback. The latter left
100% of the sentinel unchanged. These checks establish the pinned lifecycle bug;
they are not proof that collection happened at a specific recorded control.

Closed-run RGB forensics also found alternating near-exact vertical copies and
cross-camera collapse, with tiny differences confined to edge-row bytes. That is
consistent with failed reads reusing buffer memory. The native wrapper creates
fresh observation dictionaries; a controlled wrapper check did not reproduce
the issue as a repeated image-transform operation. Raw allocator-looking bytes
are not an observation modality and should not be published as model inputs.

## Operational boundary

The separately versioned `egl-owner-restore-v1` rendering track is implemented
in [render_lifecycle.py](render_lifecycle.py). Select it explicitly; `native-v1` does not enable the repair. The repair operates only in a fresh Linux/EGL
process, verifies the exact native files and loaded Python method code structure, and does
not edit the native checkouts or installed packages. It is installed before the
first environment construction and remains installed for the process lifetime so
later cyclic garbage collection cannot regain the unsafe destructor.

The repaired finalizer makes the resource owner current, frees MuJoCo resources,
and performs checked EGL release. It restores the previous display, GL context,
read/draw surfaces and bound client API unless that previous context is the owner
just destroyed. Partial initialization and nested finalizers are handled without
acquiring Robosuite's non-reentrant render lock. Failed resources are quarantined
and the process becomes unusable for further observations or episodes. EGL
release resets thread API state too; see the [EGL specification](https://registry.khronos.org/EGL/sdk/docs/man/html/eglReleaseThread.xhtml).

Render/readback wrappers leave native camera and pixel operations unchanged,
but check owner binding, offscreen framebuffer liveness and GL errors. They do
not issue additional renders/readbacks or inspect task state. A detected failure
prevents RGB delivery. These checks are not general pixel-freshness attestation;
unrelated driver, asset or rendering defects can still require diagnosis.

`render_lifecycle.json` is evaluator-private. It records the implementation hash,
native source pins, process-lifetime cumulative counters and sticky errors.
Cleanup failures caught by Python destructors still reach this receipt and the
next observation/control/metrics/finalization boundary. An error during receipt
serialization triggers a bounded pending flush; persistent I/O failure also
faults the process. A successful close drains the session's native render cycles
and requires zero tracked live renderers. No failed cleanup is reported as clean.

`native_render_attempts` and `native_readback_attempts` count entry into the native
Python operations; `render_calls` and `readback_calls` count only returns that
passed their post-operation checks. Zero validated renders does not prove that
the native renderer was never called. Error phases distinguish pre-operation,
native-operation and post-operation failure.

Do not relabel old images, switch renderer tracks silently, rerun failed tasks,
or erase recorded results. A deployment must pass both the synthetic checks
below and separately declared native reset/control/media validation before new
capability trials. Native benchmark validation and model scoring remain distinct.

## Material-clamping rendering track

The lifecycle guard also revealed a different failure on the first native kitchen
draw: scene material shininess outside `[0,1]`. The actual observed scene contained
negative values `-1` before the guard's native draw call. The same material entries
also occur in a preserved compiled task XML; the diagnostic did not export a new
XML or modify those values. A separate asset-free control with shininess `2` reproduced the positive
out-of-range case. Both produced native OpenGL debug messages identifying an
invalid shininess value; the legal `0.5` control did not.

Pinned [MuJoCo rendering](https://github.com/google-deepmind/mujoco/blob/3.3.1/src/render/render_gl3.c)
multiplies scene shininess by 128; [OpenGL](https://github.com/KhronosGroup/OpenGL-Refpages/blob/main/gl2.1/glMaterial.xml)
accepts an exponent from 0 to 128. This is distinct from the retired-context/FBO
bug, and is not grounds to ignore error 1281 or reinterpret recorded pixels.

`egl-owner-material-clamp-v1` (`rgb-egl-owner-material-clamp`) explicitly adds a visual conversion: during
one managed native draw, finite expanded-scene shininess is clamped to `[0,1]`,
then restored even when native rendering raises. All active geometries are
validated before any assignment, legal values are never rewritten, and a scene
or render context that is not the current managed one is rejected. Non-finite
values, any GL errors, or restoration failures remain fatal. The native model,
XML, physics and cameras are untouched. The earlier `native-v1` and
`egl-owner-restore-v1` tracks do not install the material hook.

This conversion **can change visual appearance**, so this track is not a claim of native
pixel parity. Its private receipt records material-transform attempts, draw calls
and clamped geometry counts, in addition to lifecycle/GL errors. Validation must
compare mixed negative/legal/positive materials against a separately authored
legal-material XML, verify restoration of scene and original model values, and
check lifecycle GC behavior. Geometry checks alone still do not qualify a native
task deployment.

The public [material_diagnose.py](material_diagnose.py) reproduces this independent
reference check. It renders only asset-free geometry, with **zero benchmark
resets, physics steps, controls or model calls**. Use the same pinned runtime/GPU
and two fresh processes, with new output directories:

```sh
MUJOCO_GL=egl PYOPENGL_PLATFORM=egl python -B -m \
  benchmarks.simBenchmarks.Robocasa_365.environment.material_diagnose \
  --gpu 0 --condition legal-reference --output /path/to/new-material-reference
MUJOCO_GL=egl PYOPENGL_PLATFORM=egl python -B -m \
  benchmarks.simBenchmarks.Robocasa_365.environment.material_diagnose \
  --gpu 0 --condition candidate --output /path/to/new-material-candidate
```

The legal reference uses independently written XML values `(0, 0.5, 1)` and v2's
native material entrypoint. The candidate uses `(-1, 0.5, 2)` and v3's explicit
conversion. Each report verifies source model/XML and expanded-scene restoration
after all three cameras, then requires clean cleanup. To qualify the pair, both
reports must pass and **all three matching-camera `rgb_sha256` values must be
equal**; two individually passing reports are insufficient. For example:

```sh
python - /path/to/new-material-reference /path/to/new-material-candidate <<'PY'
import json, sys
from pathlib import Path
reports = [json.loads((Path(p) / "report.json").read_text()) for p in sys.argv[1:]]
assert [r["condition"] for r in reports] == ["legal-reference", "candidate"]
for r in reports:
    assert r["status"] == "passed" and not r["errors"]
    assert r["guard_final"]["status"] == "closed" and r["guard_final"]["error_count"] == 0
    assert r["model_and_xml_unchanged"] and r["scene_restored_after_every_draw"]
frames = [{f["camera"]: f["rgb_sha256"] for f in r["frames"]} for r in reports]
assert set(frames[0]) == set(frames[1]) == {"front", "side", "top"}
assert frames[0] == frames[1]
print("All three reference/candidate raw RGB hashes match.")
PY
```

Keep both reports, lifecycle receipts, XML inputs and PNGs. These tiny scenes
qualify only the declared material/lifecycle operations, not native task success,
all asset types, or parity with images rendered from invalid materials.

## Geometry-only validation

The benchmark-owned [render_diagnose.py](render_diagnose.py) creates two tiny
asset-free MuJoCo render contexts. It performs zero benchmark resets, physics
steps, controls and model calls. In a separate fresh process for each condition,
it forces retired-context collection between native calls or inside the pinned
Python render/readback flow immediately before the `mjr_render` / `mjr_readPixels`
C entrypoint while the replacement context is current. The latter two conditions
use a Python shim solely to inject GC; they do not interrupt execution inside
the C function and are not installed in evaluation services.
For v3, the render-flow test instead collects immediately after native
`mjv_updateScene`, before the guarded material draw. It never replaces or weakens
the material hook or its tamper checks.

For each condition, the tool requires exact previous EGL binding restoration,
a still-live replacement framebuffer, no GL error and byte-identical before/after
RGB from three distinct cameras. It does not manually rebind the replacement
context before checking restoration. Use new output paths, for example:

```sh
MUJOCO_GL=egl PYOPENGL_PLATFORM=egl python -B -m \
  benchmarks.simBenchmarks.Robocasa_365.environment.render_diagnose \
  --gpu 0 --injection readback --output /path/to/new-readback-geometry-check
```

Run the same command with `--injection between` and `--injection render`, using
new paths and separate processes. Preserve failed reports. This synthetic
diagnostic intentionally contains no success criterion from a robotics task.
Select v3 explicitly with `--render-track egl-owner-material-clamp-v1` when
qualifying that track; the tool's default remains the original lifecycle-only v2.

Keep runtime/pin receipts, diagnostic code hashes and reports separate from
immutable episode artifacts. The [offline RGB audit](audit_rgb.py) remains a
warning tool: passing its heuristics does not establish correct rendering.
