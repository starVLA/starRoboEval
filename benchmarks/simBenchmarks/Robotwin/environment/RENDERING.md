# Native rendering acceptance

The selected native setup uses the SAPIEN `rt` shader, 32 samples per pixel,
path depth 8 and the `oidn` denoiser. The pinned SAPIEN package bundles Open Image
Denoise **2.0.1**, including its CUDA device plugin. Preserve those settings and
the package inventory when comparing this track; a successful reset/control or
pixel-exact server transfer does not prove that denoising worked.

## Check the denoiser before a participant attempt

Use the same allocated GPU, driver and native environment as the service. Record
the actual device properties, not just the advertised product name:

```sh
nvidia-smi --query-gpu=index,name,compute_cap,driver_version --format=csv
python -B -m benchmarks.simBenchmarks.Robotwin.environment.renderer_readiness \
  --library-directory /absolute/native-env/lib/python3.11/site-packages/sapien/oidn_library \
  --output /absolute/private/new-oidn-device-readiness.json
```

The tool checks the SHA-256 identity of `runtime_snapshot.json` and verifies all three bundled libraries against it
before loading the core/main libraries, then requests an OIDN **CUDA** device.
It does not import SAPIEN, construct a scene, reset or control a task, invoke a
model, denoise an image, or select a CPU fallback. Exit 0 means device creation
and commit succeeded; exit 1 retains the initialization/validation error. Use a
new report filename, in a separate process; a native loader crash is not covered
by Python exception handling. Keep this evaluator-only report out of policy input.
The receipt records the device-selection environment allowlist. This checks the
process's default CUDA device, not every GPU in the reported enumeration; it does
not attest that a later renderer chose the same physical device. Allocate/select
the intended GPU consistently and inspect the subsequent native renderer logs.

OIDN 2.0.1's CUDA device implementation accepts compute capabilities **7.0–9.9**
and filters other devices out. This is visible in the pinned public
[device limits](https://github.com/RenderKit/oidn/blob/v2.0.1/devices/cuda/cuda_device.h)
and [enumeration code](https://github.com/RenderKit/oidn/blob/v2.0.1/devices/cuda/cuda_device.cpp).
A node reporting compute capability 12.0 therefore needs a separately reviewed
compatible runtime or another compatible, allocated device. An importable plugin
file alone cannot resolve an unsupported architecture.

For loader errors, inspect dependencies with `ldd` and compare their resolved
paths with the intended environment. `OIDN_VERBOSE=3` can distinguish a plugin
loading failure from a loaded plugin with no supported physical devices. Do not
assume that adding a library search path fixes an architecture mismatch. The
probe uses the pinned [OIDN C API](https://github.com/RenderKit/oidn/blob/v2.0.1/include/OpenImageDenoise/oidn.h).

## Opt-in OIDN 2.3.3 CUDA compatibility track

The explicit `renderer_runtime: oidn_2_3_3_cuda_v1` track uses the
[official OIDN 2.3.3 release](https://github.com/RenderKit/oidn/releases/tag/v2.3.3),
whose CUDA implementation adds Blackwell support. Its Linux binary archive is
64,809,031 bytes, SHA-256
`3c385230d9e6f63527ba72f2229594dbac5051674219d72e0044b5d0b841796f`.
The archive's `doc/LICENSE.txt` is Apache-2.0; the helper retains all bundled
third-party notices. This repository distributes no native binaries.

Prepare an owned SAPIEN package overlay using the original pinned Python
environment. Do not prepend an existing overlay while preparing a new one.
Download the exact public archive, then run from the RSI checkout:

```sh
curl -fL -o /absolute/private/oidn-2.3.3.x86_64.linux.tar.gz \
  https://github.com/RenderKit/oidn/releases/download/v2.3.3/oidn-2.3.3.x86_64.linux.tar.gz
python -B -m benchmarks.simBenchmarks.Robotwin.environment.oidn_compat \
  --archive /absolute/private/oidn-2.3.3.x86_64.linux.tar.gz \
  --output-dir /absolute/new-owned/sapien-oidn233-overlay
```

The helper refuses an existing output or mismatched archive/base environment.
It copies verified SAPIEN package files, three unchanged `sapien.libs` binaries
and distribution metadata. Only the OIDN core/main/CUDA libraries and the two
literal loader version paths are replaced; the loader carries a change notice.
It regenerates `RECORD` with exact file hashes, records a separate compatibility
receipt, and leaves the base Python environment and RoboTwin deployment alone.
There is no CPU/SYCL/HIP denoiser plugin in this selected closure. All other
Python dependencies continue to come from the original environment. The overlay
is not a general-purpose site-packages directory: do not install extra files
or generate bytecode in it. A preparation error retains partial files for
inspection and requires a new output directory, not an in-place repair.

Use a fresh process and prepend the new overlay **and the RSI checkout** to
`PYTHONPATH` for every new-track readiness/server process:

```sh
export PYTHONPATH=/absolute/new-owned/sapien-oidn233-overlay:/absolute/path/to/starVLA-RSI
export CUDA_VISIBLE_DEVICES=0
python -B -m benchmarks.simBenchmarks.Robotwin.environment.runtime \
  --root /absolute/path/to/new-owned-robotwin-deployment \
  --manifest-sha256 YOUR_DEPLOYMENT_MANIFEST_SHA256 \
  --renderer-runtime oidn_2_3_3_cuda_v1
python -B -m benchmarks.simBenchmarks.Robotwin.environment.renderer_readiness \
  --library-directory /absolute/new-owned/sapien-oidn233-overlay/sapien/oidn_library \
  --renderer-runtime oidn_2_3_3_cuda_v1 \
  --output /absolute/private/new-oidn233-device-readiness.json
```

The original protocol remains the default. Select the new track explicitly in
the [compatibility server configuration](../server-oidn233.example.json); no
runtime is inferred from the GPU name. Supplying the new libraries under the
old track, or selecting the new track without its complete overlay, fails.
Runtime checks reject a shadowed SAPIEN import, a mismatched `RECORD`, extra
overlay files, symlinks and already loaded SAPIEN/OIDN libraries. The server
checks its actual library paths after import and its first native observation.
This is file/path verification, not loaded-memory attestation or proof that
every future frame was correctly denoised.

This track uses the new library's native defaults, including any different RT
filter quality. It is **not RGB-parity-compatible with 2.0.1** and must not be
merged into the same score. Preserve shader `rt`, 32 samples, path depth 8,
`oidn`, native cameras and all control/scoring settings. Before participant
use, separately validate a zero-scene CUDA RT filter (including a native CUDA
stream and shared buffers), then a predeclared no-model server diagnostic.
Check all raw views and native logs; a mapped CUDA plugin alone is insufficient.

The public synthetic fixture is separate from device creation. Run it in a new
process using the same explicitly allocated GPU; it exercises a 64 × 64 HDR
color/albedo/normal `RT` filter with a CUDA stream and shared device buffers:

```sh
python -B -m benchmarks.simBenchmarks.Robotwin.environment.oidn_filter_probe \
  --library-directory /absolute/new-owned/sapien-oidn233-overlay/sapien/oidn_library \
  --output /absolute/private/new-oidn233-cuda-filter-readiness.json
```

The tool verifies the exact three library hashes before loading them, records
the CUDA ordinal/properties and actual mapped OIDN paths, requires finite output
changed from the deterministic noisy fixture, and releases its buffers, stream
and device. No SAPIEN import, scene, benchmark reset/control or model request is
performed. The report is create-only, with a nonzero exit on validation, filter
or cleanup errors. Synthetic input/output hashes are setup evidence, not model
observations or a measure of task success. This fixture does not exercise Vulkan
buffer sharing or prove that native cameras are correct; the separate native
server check remains necessary.

## Interpret image checks separately

After device readiness, validate a predeclared no-model reset/control diagnostic
through the server/client interface. Check all three raw RGB cameras, raw-frame
hashes, file transfer, complete video decoding and native logs. Wrist cameras
at the fixed home posture can point away from the table; do not silently replace
that posture or reposition a camera to obtain a more useful image.

Observed grainy native frames accompanied by `unsupported device type "CUDA"`
or `invalid device handle` are an unresolved renderer gate, even when every PNG
and video transfers correctly. Do not disable the denoiser, substitute a new
OIDN/SAPIEN library, change samples or shader, or alter pixels under the same
runtime pin. Such a change requires a new reviewed runtime/protocol declaration
and its own diagnostic evidence. Preserve the original failed or degraded
diagnostic; it is not a model capability score and does not authorize a scored retry.
