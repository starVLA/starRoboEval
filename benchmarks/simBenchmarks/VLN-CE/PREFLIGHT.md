# VLN-CE environment and asset prerequisites

This is a reusable integration checklist, not a machine inspection log or a
runnable installer. The repository does not yet provide a unified VLN-CE adapter.
Existing pinned source evidence is separated from work that must be validated
in each deployment. No model score or native compatibility is implied.

## Verified sources and compatible runtime

The retained StarVLA integration points to
[StarVLA-VLN-CE-Evaluation](https://github.com/LiuRicky/StarVLA-VLN-CE-Evaluation/tree/2e56d1c026b2945b90b4ff339bdec2cb1e42b800),
revision `2e56d1c026b2945b90b4ff339bdec2cb1e42b800` (2026-06-02).
The benchmark authors' implementation is
[jacobkrantz/VLN-CE](https://github.com/jacobkrantz/VLN-CE).

The [integration installation guide](https://github.com/LiuRicky/StarVLA-VLN-CE-Evaluation/blob/2e56d1c026b2945b90b4ff339bdec2cb1e42b800/README.md)
specifies Python at most 3.10 and uses 3.10, Habitat-Sim and Habitat-Lab
`v0.1.7`, a headless simulator build, NumPy `1.26.0` / `<2`, and
`webdataset==0.1.103`. Its example Torch stack is `2.6.0` with CUDA 12.4;
the [requirements file](https://github.com/LiuRicky/StarVLA-VLN-CE-Evaluation/blob/2e56d1c026b2945b90b4ff339bdec2cb1e42b800/requirements.txt)
also pins Gym `0.17.3`, OpenCV `4.8.0.74`, DTW `1.4.0` and FastDTW `0.3.4`.
These are upstream instructions; compatibility must be validated in the selected deployment.
The original VLN-CE README instead describes Python 3.6; do not conflate the two
runtime recipes or assume a current Habitat release is compatible.

Relevant native implementation evidence:

- [R2R task configuration](https://github.com/LiuRicky/StarVLA-VLN-CE-Evaluation/blob/2e56d1c026b2945b90b4ff339bdec2cb1e42b800/habitat_extensions/config/vlnce_task.yaml):
  500 steps, 0.25-metre forward, 15-degree turns, RGB 512x512, depth 256x256,
  sliding enabled, four actions, and oracle sensors in the inherited configuration.
- [QwenVL evaluator](https://github.com/LiuRicky/StarVLA-VLN-CE-Evaluation/blob/2e56d1c026b2945b90b4ff339bdec2cb1e42b800/vlnce_baselines/qwenvl_trainer.py):
  RGB/instruction wire payload, up to eight sampled history frames, text-to-action
  parsing and native-step queues. Its invalid-output fallback is forward, action
  repeats are not capped at five, and the queue is not cleared at episode reset.
  These behaviors must not be inherited silently by a new shared policy adapter.
- [Dataset loader](https://github.com/LiuRicky/StarVLA-VLN-CE-Evaluation/blob/2e56d1c026b2945b90b4ff339bdec2cb1e42b800/habitat_extensions/task.py):
  episode/trajectory identity, scene paths, role/language and allowed-episode
  filters. Use explicit episode IDs; chunk/shard arguments are not episode IDs.
- [Habitat navigation task and success](https://github.com/facebookresearch/habitat-lab/blob/v0.1.7/habitat/tasks/nav/nav.py),
  [environment step limits](https://github.com/facebookresearch/habitat-lab/blob/v0.1.7/habitat/core/env.py),
  [VLN-CE measures](https://github.com/LiuRicky/StarVLA-VLN-CE-Evaluation/blob/2e56d1c026b2945b90b4ff339bdec2cb1e42b800/habitat_extensions/measures.py):
  STOP is required for success; native step counting includes STOP; nDTW reads
  evaluator-private GT locations.

## Data, variants and access

The [official R2R data definition](https://jacobkrantz.github.io/vlnce/data)
lists `R2R_VLNCE_v1-3`: train 10,819 episodes, val_seen 778, val_unseen 1,839,
and test 3,408. The val_unseen split spans 11 scenes. The 3 MB minimal package
contains episodes; the 250 MB preprocessed package includes validation GT actions
and locations needed by the retained nDTW scorer. Its augmented training split
is outside this evaluation scope. Test goals/GT are withheld for server scoring;
do not substitute test data for locally scored validation episodes.

RxR is a separate dataset with train/val_seen/val_unseen/test_challenge splits,
guide/follower roles and English, Hindi and Telugu instructions. The pinned
[StarVLA RxR experiment](https://github.com/LiuRicky/StarVLA-VLN-CE-Evaluation/blob/2e56d1c026b2945b90b4ff339bdec2cb1e42b800/vlnce_baselines/config/rxr_baselines/qwenvl.yaml)
selects val_unseen/en-US and enables resize/crop transforms; evaluator setup
selects guide. The [transform defaults](https://github.com/LiuRicky/StarVLA-VLN-CE-Evaluation/blob/2e56d1c026b2945b90b4ff339bdec2cb1e42b800/vlnce_baselines/config/default.py)
set the RGB crop to 224x224. Its task uses 15-degree turns and sliding. In contrast, the
[authors' RxR task configuration](https://github.com/jacobkrantz/VLN-CE/blob/master/habitat_extensions/config/rxr_vlnce_english_task.yaml)
uses 30-degree turn/tilt actions, sliding disabled and 480x640 RGBD. This latter
link is a comparison source, not an additional pinned runtime. RxR needs its
own frozen variant and acceptance pass; the two configurations are not an
interchangeable challenge score.

MP3D scene meshes are a separate required asset. The
[Matterport3D project](https://niessner.github.io/Matterport/) requires a signed
Terms of Use agreement and a request to the dataset owners for access. Reuse
an authorized asset location if available; do not sign on a participant's behalf,
send an access request without authorization or bypass access through mirrors.
The [VLN-CE license notice](https://github.com/jacobkrantz/VLN-CE#license) states
that code is MIT, while MP3D-derived task datasets and trained models carry
Matterport3D Terms of Use and CC BY-NC-SA 3.0 US. Dataset rights do not follow
automatically from the code license.

## Deployment checklist

Check authorized existing assets and compatible environments before provisioning
new copies. Record the evaluator revision, Habitat build, selected split,
scene inventory and data hashes. Episode IDs and scene requirements must come
from the selected complete dataset, not from guesses or available-asset filtering.
Missing assets or an unavailable runtime are setup prerequisites, not model failures.

## Adapter implementation requirements

1. Resolve the execution node and authorized MP3D root. Obtain the complete
   selected episode split and scoring GT, then freeze the selection rule in
   [EVALUATION_PROTOCOL.md](EVALUATION_PROTOCOL.md) into an explicit episode
   manifest. Only then determine the required scenes; asset availability must
   not choose the episodes. Validate readability and checksums before simulation.
2. Create an isolated simulator environment, obtain the pinned evaluator and
   Habitat v0.1.7 sources, and record resolved revisions, build flags and package
   versions. Review the integration's
   [NumPy compatibility replacement](https://github.com/LiuRicky/StarVLA-VLN-CE-Evaluation/blob/2e56d1c026b2945b90b4ff339bdec2cb1e42b800/scripts/habitat_sim_autofix.py)
   before use: it overwrites an installed Habitat-Sim source file. Any applied
   patch is part of runtime provenance. Verify import and headless rendering;
   this old stack's compatibility must be demonstrated on the chosen node.
3. Resolve task `DATA_PATH`, `SCENES_DIR` and `NDTW.GT_PATH` explicitly. The pinned
   integration contains nonportable absolute GT defaults and differing scene
   path benchmarks. Check the
   final resolved mesh and GT files, not merely the presence of a directory.
4. Implement a lazy-loading `BenchmarkAdapter` and one-episode session around
   native `habitat.Env`, registered datasets/tasks and measures. Expose only
   the proposed RGB/instruction boundary, enforce integer navigation actions,
   execute native STOP, preserve the 500-step horizon, and record native metrics
   and RGB video in runner-owned artifacts. Keep provider/model code outside
   the evaluator, with no simulator or GT access from the policy process.
5. Add dependency-light contract/boundary checks and native direct-versus-session
   trajectory/metric verification. Define a fast subset or a native full split
   explicitly; retain every scheduled attempt, failure and typed error without
   automatic retries. Do not register or advertise a runnable adapter before one
   exists and passes its relevant checks. A successful task completion is not
   required to validate correct environment stepping and scoring.
