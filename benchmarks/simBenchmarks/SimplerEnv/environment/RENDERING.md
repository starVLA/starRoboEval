# Rendering preflight and troubleshooting

Validate graphics before freezing an evaluation configuration. CUDA visibility,
a nonflat final RGB image or a decodable video does not establish usable native
rendering: SimplerEnv composites a photographic background. The robot and task
objects can be black while the background looks detailed.

Diagnostics are evaluator-side infrastructure checks, never model observations
or scored attempts. Do not pass their private buffers, segmentation, asset
identities, native scores or findings to an active policy.

## Check both rendering paths

### First verify the actual GPU, without starting a task

SAPIEN 2.2.2 can alias CUDA devices when several GPUs share a PCI bus number
(their full PCI addresses may still differ). Its renderer log may map several
Vulkan devices to the same CUDA ordinal. Then `cuda:3` can be unavailable even
though CUDA itself enumerates device 3. `CUDA_VISIBLE_DEVICES` alone does not
isolate Vulkan or prove that the intended physical GPU was selected. See the
[upstream report](https://github.com/haosulab/SAPIEN/issues/170).

Choose an available device explicitly; there is no automatic fallback. Obtain
its full UUID with `nvidia-smi --query-gpu=index,uuid,pci.bus_id --format=csv`.
Use the same native Python and environment as the service:

```bash
python -B -m benchmarks.simBenchmarks.SimplerEnv.environment.render_device \
  --device cuda:0 --expected-gpu-uuid GPU-REPLACE-WITH-FULL-DEVICE-UUID \
  --output /absolute/new-render-device-preflight.json
```

This creates only a renderer in a bounded child process, never a scene, task
reset, action or model request. It checks the renderer process's actual NVIDIA
graphics/compute inventory against the exact UUID and retains logs. Missing PID
visibility, multiple observed GPUs or a mismatch fail closed. A passing probe
does not reserve the GPU, validate cameras/assets, or repair arbitrary nonzero
GPU routing in the old renderer. If a requested device fails, explicitly choose
and verify another available device before declaring the task run; never hide a
fallback inside an active attempt. Do not replace the pinned simulator to work
around a deployment issue.

Set the same `device` and optional `expected_gpu_uuid` in the server parameter
JSON. When supplied, the adapter rechecks actual process identity after native
construction and before returning the first public observation; it records the
identity in private native provenance. Native construction itself can initialize
the scene, so this check does **not** replace the pre-claim renderer-only probe.
Neither this deployment assertion nor its private diagnostics expands policy
observations.

Pinned Google drawer tasks use RT shaders with denoising enabled, 32 samples per
pixel and path depth 8. Can-picking and move-near configurations use IBL; passing
an IBL check does not validate drawer rendering. Use the same interpreter,
NVIDIA Vulkan ICD, graphics device and environment for preflight and evaluation.

```bash
python benchmarks/simBenchmarks/SimplerEnv/environment/verify_environment.py \
  --task google_robot_open_top_drawer --seed 0 --steps 0
```

The verifier checks scheduled RGB and the already-acquired camera Color buffer,
using `get_images(take_picture=False)` rather than requesting an extra render
or scorer evaluation. Nonfinite or entirely zero native RGB fails even when a
photographic overlay looks detailed.

The guard is deliberately narrow: it does not certify texture completeness,
foreground correctness or camera parity. Keep stderr and visually inspect the
robot and objects. Image appearance does not determine task success.

## Check NVIDIA graphics components, not only CUDA

A functioning CUDA installation and Vulkan ICD can coexist with incomplete
container graphics data. In particular, `/usr/share/nvidia/nvoptix.bin` supplies
OptiX denoiser data. Missing matching data can accompany
`OPTIX_ERROR_INTERNAL_ERROR`, `OPTIX_ERROR_INVALID_VALUE` or denoise failures.

Confirm the exact installed driver version and its vendor component list before
diagnosing a missing file. Consult the matching NVIDIA driver documentation and
the container runtime's graphics exposure. Relevant primary references include
the [580.105.08 installed-component list](https://download.nvidia.com/XFree86/Linux-x86_64/580.105.08/README/installedcomponents.html)
and NVIDIA's [container graphics discovery implementation](https://github.com/NVIDIA/nvidia-container-toolkit/blob/main/internal/discover/graphics.go).
These symptoms are diagnostic clues, not proof that every rendering failure
has the same cause.

Do not switch RT to IBL, disable native denoising, replace assets or change
controller/environment settings merely to obtain a score. Such changes require
a separately declared configuration. A diagnostic setting must not silently
become the evaluated setting.

## Use matching vendor data

Obtain any missing data for the installed driver version and verify the vendor
archive before extraction. The following previously verified vendor package is
a concrete example, **not** a recommended driver version or universal file hash:

| Artifact for NVIDIA 580.105.08 | Bytes | SHA-256 |
| --- | ---: | --- |
| [Linux x86-64 no-compat32 archive](https://download.nvidia.com/XFree86/Linux-x86_64/580.105.08/NVIDIA-Linux-x86_64-580.105.08-no-compat32.run) | 325,237,600 | `80b6a015c6eefdf24f81f76cddb0eb6ce4bcf09b43331130892588c9713300ec` |
| Extracted `nvoptix.bin` | 60,858,204 | `d5eacd24c18bda32f0b40d82c6fb2597c6b8fc72294b16a71c22ce164b9c26a2` |

The archive's [vendor checksum](https://download.nvidia.com/XFree86/Linux-x86_64/580.105.08/NVIDIA-Linux-x86_64-580.105.08-no-compat32.run.sha256sum)
is the reference for that exact download. Use extraction-only mode in a fresh
private directory; do not execute the driver installer as part of a data-only
repair. Keep partial downloads separate. Do not redistribute driver binaries
inside this repository.

## Container exposure and reproducibility

Prefer administrator-managed exposure of the complete matching driver data.
Where explicitly supported by the host's permissions, an administrator can use
a private mount namespace and a read-only mirror of the NVIDIA data directory
for a diagnostic or evaluation process. Preserve all existing directory entries,
add only verified matching data and check the effective file identity inside
the namespace. Never perform the bind mount in the global mount namespace.

This repository does not provide a universal driver-data installer or a
portable privileged wrapper. If private mounts are unavailable, coordinate
proper container graphics exposure with the administrator rather than replacing
system components. Hash receipts identify inspected data, not loaded-memory
attestation or protection against a hostile operator.

After repair, rerun a separate rendering diagnostic with the original shader,
denoising, controller and observation settings. Record interpreter, driver,
effective graphics-data hashes, container/mount configuration and the diagnostic
outcome before any newly declared evaluation. Keep existing attempts unchanged;
a rendering defect discovered after closure is retained with its caveat, not
removed, relabeled as successful or automatically retried. Results from changed
environment conditions must remain distinguishable.
