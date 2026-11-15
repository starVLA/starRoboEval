# RoboCasa365 environment setup

Prepare a dedicated native environment before starting the
[benchmark service](../README.md#start-the-benchmark-service). The service uses
the simulator and its task assets; it does not require a learned checkpoint or
training demonstrations.

## Sources, runtime and assets

| Component | Required version / revision |
| --- | --- |
| [RoboCasa](https://github.com/robocasa/robocasa) | 1.0.1; `b4684e6ee37d377cc392e98302a6b916d588b415` |
| Robosuite | 1.5.2; `85abee228d1c43ab1939bce33028099945d453b4` |
| MuJoCo | 3.3.1 |
| NumPy | 2.2.5 |

Install the pinned native sources and their dependencies in an isolated
environment, provision the required kitchen/object assets under their licenses,
then install RSI with `python -m pip install --no-deps -e .` from its checkout.
H.264 recording requires PyAV and working graphics/EGL libraries. Imported
native packages must resolve to their own clean Git roots at the exact pins.
An enclosing unrelated repository is not a native source identity.

A portable all-assets installer is not provided. Check import paths and source
and asset availability on the intended node. The adapter records the assets
actually referenced by the compiled scene, including dependency closure; this
does not certify the entire upstream asset universe.

## Choose a rendering track

| `render_track` | Behavior |
| --- | --- |
| `native-v1` | Original native rendering; retains the known EGL lifecycle defect |
| `egl-owner-restore-v1` | Process-local EGL ownership/cleanup repair; no material conversion |
| `egl-owner-material-clamp-v1` | Ownership repair plus temporary bounding of invalid scene shininess; pixels can differ |

See [RENDERING.md](RENDERING.md) for the defect, exact repair scope and
geometry-only checks. The supplied server configuration selects the third
track. Its distinct protocol identity must remain in reports; it is not
native-pixel-equivalent. Set `MUJOCO_GL=egl` and `PYOPENGL_PLATFORM=egl` before
launch. Use a fresh single-thread native process, with an explicitly allocated
GPU; do not mix rendering tracks in one process.

## Native readiness

Run the [geometry-only lifecycle checks](RENDERING.md#geometry-only-validation)
first. Then check native reset and three-camera RGB through the service with the
shared [readiness probe](../../SERVER_PROTOCOL.md#readiness-probe), using a
dedicated `example` launch with the intended `render_track`. It claims and
resets one episode, with no model calls or actions, and reports each camera's
reset image shape.

These are infrastructure checks, not participant capability attempts. Keep
their outputs separate from scored evaluations.

## Inspect retained RGB records

When a closed episode retains `frames.jsonl` and three-camera PNGs, a read-only
diagnostic can check file integrity and frame coverage:

```sh
python -B -m benchmarks.simBenchmarks.Robocasa_365.environment.audit_rgb \
  /absolute/closed-episode-artifacts \
  --output /absolute/new-rgb-audit.json
```

It needs NumPy and Pillow, not a simulator or model. Use a new output outside
the source records. A clean matching service receipt can bind coverage to
reset-plus-control counts; absent or faulted receipts leave completeness
unknown. Pixel-similarity/orientation warnings are diagnostic indicators, not
a rendering diagnosis or task score. For temporal warnings, `first_step` names
the destination frame; its comparison starts at `first_step - 1`. Native videos
are retained by default, but standalone PNGs may have been cleaned at close;
this PNG-based tool is only applicable when those frames were retained.
