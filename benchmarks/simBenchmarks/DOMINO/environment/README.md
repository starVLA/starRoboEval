# Native preparation and direct-control boundary

The inspected public source is [h-embodvis/DOMINO](https://github.com/h-embodvis/DOMINO)
at `9c94f2d3a700fff3b65f041df4038d497139ed1f`.

```sh
git clone https://github.com/h-embodvis/DOMINO.git /absolute/new-domino
git -C /absolute/new-domino checkout --detach 9c94f2d3a700fff3b65f041df4038d497139ed1f
git -C /absolute/new-domino diff --exit-code HEAD
```

Native `assets/_download.py` requests `background_texture.zip`,
`embodiments.zip` and `objects.zip` from the public
[TianxingChen/RoboTwin2.0 dataset](https://huggingface.co/datasets/TianxingChen/RoboTwin2.0).
Training demonstrations and PUMA/model weights are not simulator assets.
Matching existing assets can be verified and reused read-only. Otherwise pin
the dataset revision, download the required archives, record their hashes and
extract into a fresh asset root after checking archive paths and links. Never
merge blindly over an existing deployment or assume a current dataset equals a
historical local asset tree.

Do not run the native installation script against an existing shared environment.
It edits SAPIEN/MPLib package code and clones CuRobo without a fixed revision.
A portable deployment needs its own environment, recorded native package/source
identities, explicit path-only configuration derivations and a verified controller
contract. The RoboTwin server's source pin is not a DOMINO source pin.

## Why assets alone do not complete the interface

The pinned native evaluator normally executes an expert to screen candidate
seeds and recover dynamic-motion information. Its optional fixed-episode manifest
avoids online screening but still contains expert-screened scene/trajectory
data. Neither mode is an unscreened once-per-selected-seed fast protocol.

A direct-control service must freeze and document its scene distribution before
evaluation, keep all dynamic-trajectory and metric-tracker data private, and never
offer expert action proposals to the model. Do not replace the dynamic task with
a static lookalike merely because its assets load. Preserving native SR/MS also
requires the native route-completion, contact-stop, lifting and out-of-bounds
logic, not only the task's cached success flag.

The implemented service now selects the bounded `click_bell` fixed-manifest
SM120 compatibility track. Native preparation and service validation remain
unfinished; this is not a passed native-run claim. See the
[evaluation protocol](../EVALUATION_PROTOCOL.md).

## Prepare a fresh owned deployment

`deployment.py` verifies the public Git blob identities of DOMINO and CuRobo,
copies only those verified source paths, copies the selected aloha/bell assets,
and derives only the two native CuRobo asset-root substitutions. It captures
selected compatibility package versions and SAPIEN/MPLib/TOPPRA file hashes.
It never invokes an installer, expert, simulator or model. Existing destinations
are refused. Untracked compiled CuRobo extensions are not copied; new JIT builds
belong to an episode-owned cache, never source or a colleague's environment.

With the declared compatibility interpreter and verified owned SAPIEN/OIDN2.3.3
overlay already selected on `PYTHONPATH`:

```sh
python -B -m benchmarks.simBenchmarks.DOMINO.environment.deployment \
  --source /absolute/pinned-domino-source \
  --source-git /absolute/public-domino-git-reference \
  --assets /absolute/verified-robotwin-assets \
  --curobo /absolute/pinned-curobo-source \
  --curobo-git /absolute/public-curobo-git-reference \
  --destination /absolute/new-owned-domino-deployment
```

The Git references must contain DOMINO revision
`9c94f2d3a700fff3b65f041df4038d497139ed1f` and CuRobo v0.7.8 revision
`d64c4b005459db10c5dd867d8b30a87d5bda9bdb`. No global Git setting is modified.
Retain the returned manifest SHA256 and do not change the captured deployment.
Source verification includes unknown executable/bytecode detection at runtime;
launch with `-B` and never add caches to source trees.

The minimal asset closure is aloha-agilex plus bell variants0/1, including
collision/visual geometry, robot meshes, SRDF and native configs. Native clean
mode uses no randomized background/clutter textures. File closure does not prove
release identity or successful rendering. More tasks require separately verified
assets and declarations, not copying task names from the horizon file.

## Private fixed-episode preparation gate

No ready-made DOMINO fixed manifests are shipped in the inspected source.
Upstream `screen_episodes.py` can search many candidates and run multiple resets;
do not execute it under permission for one diagnostic task attempt.

A separately authorized, bounded preparation may inspect exactly one declared
candidate and preserve rejection without scanning for a replacement. It must
retain expert preparation and dynamic-validation reset counts, source/deployment
identities and any failure, then freeze a trusted manifest before policy use.
The server accepts only a manifest pinned to the native revision and checks the
chosen seed and dynamic-motion payload. It never prepares, edits or searches
the manifest while a policy runs. A manifest is private native reset data;
pickle requires a trusted local origin and hash, not arbitrary policy input.

The current native import path still initializes CuRobo planners even though
policy controls use qpos/TOPP. The compatibility environment needs a compatible
CUDA compiler for fresh JIT builds. GPU names alone do not establish architecture;
verify compute capability and actual renderer device on the assigned node.
The inspected SM120 track requires Torch2.7.1+CUDA12.8; substituting native
Torch2.4.1 on that hardware is not a validated fix.

For a Conda-layout CUDA toolkit, `nvcc` may find its own headers while the host
C++ compiler cannot find `cuda_runtime_api.h`. Before claiming a task, verify
the compiler and header locations, then select the existing toolkit only in
the launch environment, for example:

```sh
export CUDA_HOME=/absolute/verified-cuda-toolkit
export PATH="$CUDA_HOME/bin:$PATH"
export CPATH="$CUDA_HOME/targets/x86_64-linux/include${CPATH:+:$CPATH}"
export TORCH_CUDA_ARCH_LIST=12.0
```

Use the actual selected GPU architecture, not `12.0` on a different device.
Do not patch a shared environment or copy unverified compiled CuRobo extensions
into the native source. Record compiler and Torch CUDA versions independently:
the inspected compatibility preflight used nvcc12.9.86 with Torch CUDA12.8,
not an exact toolkit-version match. Build/import readiness, synthetic rendering,
robot-only planner warmup and a task reset are separate checks. Native source
and assets must remain unchanged; isolate JIT, Warp and driver caches in owned
diagnostic storage. These setup checks are not policy trials or task scores.
