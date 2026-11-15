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
pinned asset tree.

Do not run the native installation script against an existing shared environment.
It edits SAPIEN/MPLib package code and clones CuRobo without a fixed revision.
A portable deployment needs its own environment, recorded native package/source
identities, explicit path-only configuration derivations and a verified controller
contract. The RoboTwin server's source pin is not a DOMINO source pin.

## Why assets alone do not complete the interface

The pinned native evaluator normally executes an expert to screen candidate
seeds and recover dynamic-motion information. Its optional fixed-episode manifest
avoids online screening but still contains expert-screened scene/trajectory
data. In either procedure, the selected scenes are expert-screened; a seed alone
does not replace the saved dynamic-motion payload.

A direct-control service must freeze and document its scene distribution before
evaluation, keep all dynamic-trajectory and metric-tracker data private, and never
offer expert action proposals to the model. Do not replace the dynamic task with
a static lookalike merely because its assets load. Preserving native SR/MS also
requires the native route-completion, contact-stop, lifting and out-of-bounds
logic, not only the task's cached success flag.

The service selects the bounded `click_bell` fixed-manifest SM120 runtime. Provision and verify its deployment and trusted manifest before native
initialization; matching source/asset files alone do not establish readiness.
See the [evaluation protocol](../EVALUATION_PROTOCOL.md).

## Prepare a fresh owned deployment

`deployment.py` verifies the public Git blob identities of DOMINO and CuRobo,
copies only those verified source paths, copies the selected aloha/bell assets,
and derives only the two native CuRobo asset-root substitutions. It captures
selected runtime package versions and SAPIEN/MPLib/TOPPRA file hashes,
excluding interpreter bytecode caches that other users of a shared environment
may add.
It never invokes an installer, expert, simulator or model. Existing destinations
are refused. Untracked compiled CuRobo extensions are not copied; new JIT builds
belong to an episode-owned cache, never source or a shared environment.

With the declared SM120 interpreter and verified owned SAPIEN/OIDN2.3.3
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

A separately authorized, bounded preparation walks native candidate seeds from
100000 in order until the manifest holds the first five accepted entries, which
the `fast` mode uses. It must retain every rejection, expert preparation and
dynamic-validation reset count, source/deployment identities and any failure,
then freeze a trusted manifest before policy use.

`max` needs the complete native record instead; this preparation has not yet
been performed. Run the native screener once, from a clean Git checkout of the
pinned revision with the verified assets and runtime, so that native
`git rev-parse HEAD` records `git_commit`:

```sh
python script/screen_episodes.py --task_name click_bell \
  --task_config demo_clean_dynamic --seed 0 --test_num 100 \
  --manifest_path /absolute/private/click_bell-demo_clean_dynamic-seed0.pkl
```

Upstream `screen_episodes` runs the expert (`setup_demo` + `play_once`) on
each candidate seed from `st_seed = 100000`. It re-initializes each accepted
dynamic candidate through `init_dynamic_motion_for_eval`, logs every rejected
seed with its reason and stops at the 100th acceptance. Keep the pickle and its
JSON summary. Record the pickle SHA256, the runtime used, the deployment
manifest SHA256 and any failure; never rerun it to improve a result. Whether
screening under the SM120 compatibility runtime accepts the same seeds as the
upstream runtime is UNVERIFIED.

The server's `max` startup gate checks the metadata, the 100 entries and the
contiguous accepted-plus-rejected seed walk; see the
[protocol](../EVALUATION_PROTOCOL.md). At reset, every mode also checks that
the manifest is pinned to the native revision and that the selected entry has
a unique seed and a dynamic-motion payload. The server never prepares, edits or
searches the manifest while a policy runs. A manifest is private native reset
data; pickle requires a trusted local origin and hash, not arbitrary policy
input.

The current native import path still initializes CuRobo planners even though
policy controls use qpos/TOPP. The SM120 environment needs a compatible
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
into the native source. Record compiler and Torch CUDA versions independently;
a reported Torch CUDA version does not identify the installed toolkit compiler.
Build/import readiness, synthetic rendering,
robot-only planner warmup and a task reset are separate checks. Native source
and assets must remain unchanged; isolate JIT, Warp and driver caches in owned
diagnostic storage. These setup checks are not policy trials or task scores.

Check the task reset through the service with the shared
[readiness probe](../../SERVER_PROTOCOL.md#readiness-probe) against a dedicated
`example` launch. It claims, resets and finishes one episode, with no model or
action, and records any failure as an infrastructure error.
