# SimplerEnv tasks and variants

Verified against SimplerEnv `c701ea271b16b80616d6fed9713c4a50a0adea3b` and its
ManiSkill2 submodule `ef7a4d4fdf4b69f2c2154db5b15b9ac8dfe10682`. Counts distinguish
aliases, semantic tasks, reset layouts, and evaluation sweeps. Use
[EVALUATION_PROTOCOL.md](../../EVALUATION_PROTOCOL.md) for the service's case
selectors and observation/action rules.

## How many tasks?

| Scope | Count | Meaning |
| --- | ---: | --- |
| Prepackaged Python aliases | 25 | 21 Google Robot + 4 WidowX names |
| Broad rows in upstream README | 10 | 6 Google categories + 4 WidowX tasks |
| Families in paper reproduction scripts | 9 | 5 Google families + 4 WidowX tasks; random-object picking is an extension |
| Current service selectors | 15 | Expand can directions and drawer levels; avoid generic aliases and duplicate move-near versions |

The [pinned README](https://github.com/allenai/SimplerEnv/blob/c701ea271b16b80616d6fed9713c4a50a0adea3b/README.md)
groups tasks; the [Python registry](https://github.com/allenai/SimplerEnv/blob/c701ea271b16b80616d6fed9713c4a50a0adea3b/simpler_env/__init__.py)
defines the 25 aliases.

## Complete prepackaged alias inventory

`Service` marks the 15 canonical subtasks accepted by this integration.
Generic aliases choose a native subcase at reset; they
are not additional independent paper tasks.

| Alias | Native environment | Selection / relation | Service |
| --- | --- | --- | --- |
| `google_robot_pick_coke_can` | `GraspSingleOpenedCokeCanInScene-v0` | Samples one of three orientations | |
| `google_robot_pick_horizontal_coke_can` | `GraspSingleOpenedCokeCanInScene-v0` | `lr_switch=True` | yes |
| `google_robot_pick_vertical_coke_can` | `GraspSingleOpenedCokeCanInScene-v0` | `laid_vertically=True` | yes |
| `google_robot_pick_standing_coke_can` | `GraspSingleOpenedCokeCanInScene-v0` | `upright=True` | yes |
| `google_robot_pick_object` | `GraspSingleRandomObjectInScene-v0` | Extension with 14 object identities | |
| `google_robot_move_near_v0` | `MoveNearGoogleBakedTexInScene-v0` | RT-1 VM reference uses this texture version | yes |
| `google_robot_move_near_v1` | `MoveNearGoogleBakedTexInScene-v1` | Different baked textures/materials | |
| `google_robot_move_near` | `MoveNearGoogleBakedTexInScene-v1` | Exact alias of `_v1` | |
| `google_robot_open_drawer` | `OpenDrawerCustomInScene-v0` | Samples top/middle/bottom | |
| `google_robot_open_top_drawer` | `OpenTopDrawerCustomInScene-v0` | Top | yes |
| `google_robot_open_middle_drawer` | `OpenMiddleDrawerCustomInScene-v0` | Middle | yes |
| `google_robot_open_bottom_drawer` | `OpenBottomDrawerCustomInScene-v0` | Bottom | yes |
| `google_robot_close_drawer` | `CloseDrawerCustomInScene-v0` | Samples top/middle/bottom | |
| `google_robot_close_top_drawer` | `CloseTopDrawerCustomInScene-v0` | Top | yes |
| `google_robot_close_middle_drawer` | `CloseMiddleDrawerCustomInScene-v0` | Middle | yes |
| `google_robot_close_bottom_drawer` | `CloseBottomDrawerCustomInScene-v0` | Bottom | yes |
| `google_robot_place_in_closed_drawer` | `PlaceIntoClosedDrawerCustomInScene-v0` | Samples drawer and object | |
| `google_robot_place_in_closed_top_drawer` | `PlaceIntoClosedTopDrawerCustomInScene-v0` | Top; object from native asset catalog | |
| `google_robot_place_in_closed_middle_drawer` | `PlaceIntoClosedMiddleDrawerCustomInScene-v0` | Middle; object from native asset catalog | |
| `google_robot_place_in_closed_bottom_drawer` | `PlaceIntoClosedBottomDrawerCustomInScene-v0` | Bottom; object from native asset catalog | |
| `google_robot_place_apple_in_closed_top_drawer` | `PlaceIntoClosedTopDrawerCustomInScene-v0` | `model_ids=baked_apple_v2` | yes |
| `widowx_spoon_on_towel` | `PutSpoonOnTableClothInScene-v0` | 24 native layouts | yes |
| `widowx_carrot_on_plate` | `PutCarrotOnPlateInScene-v0` | 24 native layouts | yes |
| `widowx_stack_cube` | `StackGreenCubeOnYellowCubeBakedTexInScene-v0` | 24 native layouts | yes |
| `widowx_put_eggplant_in_basket` | `PutEggplantInBasketScene-v0` | 24 native layouts; sink camera setup | yes |

The 14 random-pick objects are listed in the native
[grasp environment](https://github.com/simpler-env/ManiSkill2_real2sim/blob/ef7a4d4fdf4b69f2c2154db5b15b9ac8dfe10682/mani_skill2_real2sim/envs/custom_scenes/grasp_single_in_scene.py).
That count does not define an episode count: orientation, sampled position, and
visual conditions also vary. Generic drawer-placement aliases likewise do not
define the fixed apple-only paper task.

## Horizons and overrides

The upstream task registration supplies `native_horizon=H`. A launcher can
explicitly override the episode time limit; that resolved value is the actual
`evaluation_horizon`. Neither value counts model decisions: `max_policy_calls`
and the executed action prefix determine how many control steps a policy can
reach within that time limit.

| Task group | Upstream native H | Pinned official script horizon | Horizon-mode H | Explicit 2H override |
| --- | ---: | ---: | ---: | ---: |
| Pick coke can / move near | 80 | 80 | 80 | 160 |
| Open / close drawer | 113 | 113 | 113 | 226 |
| Apple in closed top drawer | 200 | 200 | 200 | 400 |
| Spoon / carrot / cube | 60 | 60 | 60 | 120 |
| Eggplant in basket | 120 | 120 | 120 | 240 |

An explicitly selected 120-step spoon, carrot or cube evaluation overrides its
60-step native registration. Eggplant already has native H=120, so a 2H override
gives 240. Applying one numerical limit to every task is not the same as doubling
each native horizon. Matching one horizon does not reproduce another policy's
action processing, seeds or evaluation matrix.

Sources: upstream [Bridge registrations](https://github.com/simpler-env/ManiSkill2_real2sim/blob/ef7a4d4fdf4b69f2c2154db5b15b9ac8dfe10682/mani_skill2_real2sim/envs/custom_scenes/put_on_in_scene.py)
and [official Bridge script](https://github.com/allenai/SimplerEnv/blob/c701ea271b16b80616d6fed9713c4a50a0adea3b/scripts/rt1x_bridge.sh);
the Google script sources appear in the following VM table.

The catalog's `native_horizon` remains unchanged. In horizon mode, multiplier
one preserves H; multiplier two is an explicitly configured extended track with separate
identity and reporting. A predeclared 2H trajectory can record native success
at H and 2H without resetting or calling the scorer again. Those checkpoints
must not become a best-of score or a failure-triggered retry; an unreached
checkpoint is unobserved, not inferred. See the
[budget and checkpoint rules](../../EVALUATION_PROTOCOL.md#budgets-and-instruction-transitions).

## Visual Matching reference matrix

Visual Matching (VM) aligns simulated foregrounds with real background images.
These counts expand pinned `rt1_*_visual_matching.sh` and `rt1x_bridge.sh` scripts
**for one checkpoint**, excluding repeated policies or policy random seeds.
The four URDF appearances are default plus three recolors. A paired robot
pose/overlay is one matched condition, not independently cross-multiplied axes.

| Family | Reset conditions per appearance | Appearance variants | Episodes per policy |
| --- | --- | ---: | ---: |
| Pick coke can | 3 orientations × 5 × 5 object XY grid | 4 URDF | 300 |
| Move near (`v0`) | 60 object/layout episodes | 4 URDF | 240 |
| Open drawer | 3 drawer levels × 9 paired pose/overlay conditions | 4 URDF | 108 |
| Close drawer | 3 drawer levels × 9 paired pose/overlay conditions | 4 URDF | 108 |
| Apple in closed top drawer | 3 paired pose/overlay conditions × 3 × 3 object XY | 4 URDF | 108 |
| Spoon on towel | 24 native layouts | 1 table/overlay setup | 24 |
| Carrot on plate | 24 native layouts | 1 table/overlay setup | 24 |
| Stack cube | 24 native layouts | 1 table/overlay setup | 24 |
| Eggplant in basket | 24 native layouts | 1 sink/overlay setup | 24 |

This reference expansion is **864 Google + 96 WidowX = 960 episodes** per policy.
It does not mean every alias has 960 episodes or that the RSI adapter runs this
reference matrix.

Sources: [pick VM](https://github.com/allenai/SimplerEnv/blob/c701ea271b16b80616d6fed9713c4a50a0adea3b/scripts/rt1_pick_coke_can_visual_matching.sh),
[move VM](https://github.com/allenai/SimplerEnv/blob/c701ea271b16b80616d6fed9713c4a50a0adea3b/scripts/rt1_move_near_visual_matching.sh),
[drawer VM](https://github.com/allenai/SimplerEnv/blob/c701ea271b16b80616d6fed9713c4a50a0adea3b/scripts/rt1_drawer_visual_matching.sh),
[apple VM](https://github.com/allenai/SimplerEnv/blob/c701ea271b16b80616d6fed9713c4a50a0adea3b/scripts/rt1_put_in_drawer_visual_matching.sh),
and [Bridge](https://github.com/allenai/SimplerEnv/blob/c701ea271b16b80616d6fed9713c4a50a0adea3b/scripts/rt1x_bridge.sh).

### Native layout counts

| Task | Layout construction | Native object episode IDs |
| --- | --- | --- |
| Move near | 5 triplets × 6 ordered source/target choices × 2 XY layouts = 60 | 0–59 |
| Spoon on towel | 4 × 3 ordered distinct grid positions × 2 orientations = 24 | 0–23 |
| Carrot on plate | 4 × 3 ordered distinct grid positions × 2 orientations = 24 | 0–23 |
| Stack cube | 2 grid scales × 4 × 3 ordered distinct positions = 24 | 0–23 |
| Eggplant in basket | 2 × 4 positions × 3 orientations = 24 | 0–23 |

The native [move-near definitions](https://github.com/simpler-env/ManiSkill2_real2sim/blob/ef7a4d4fdf4b69f2c2154db5b15b9ac8dfe10682/mani_skill2_real2sim/envs/custom_scenes/move_near_in_scene.py)
and [Bridge definitions](https://github.com/simpler-env/ManiSkill2_real2sim/blob/ef7a4d4fdf4b69f2c2154db5b15b9ac8dfe10682/mani_skill2_real2sim/envs/custom_scenes/put_on_in_scene.py)
are authoritative. These IDs configure the evaluator; the policy must not
receive them or consult this layout table during a rollout.

Prepackaged reset samples visual conditions and, where applicable, native
object episode IDs. A reset seed is not an object episode ID. Covering all
object IDs is not complete visual-condition coverage. Random resets do not
guarantee coverage of every reference condition.

## Variant Aggregation reference matrix

Variant Aggregation (VA) aggregates changes in simulated visual conditions.
These scripts use grouped **single-factor perturbations** around a base setup,
not a full Cartesian product. Do not also multiply by the four VM URDF recolors.

| Family | Visual settings, including base | Episodes per setting | Total per policy |
| --- | ---: | ---: | ---: |
| Pick coke can | 11 | 3 orientations × 25 object XY | 825 |
| Move near | 10 | 60 object/layout episodes | 600 |
| Open drawer | 7 | 3 drawer levels × 3 × 3 robot XY | 189 |
| Close drawer | 7 | 3 drawer levels × 3 × 3 robot XY | 189 |
| Apple in closed top drawer | 7 | 3 robot Y × 3 × 3 object XY | 189 |

This Google reference expansion has **1,992 episodes per policy**. The cited
Bridge script supplies VM configurations, not an equivalent published VA sweep.

- Pick: base + 2 table textures + 2 distractor configurations + 2 backgrounds +
  2 lighting settings + 2 camera configurations = 11.
- Move: base + 1 no-distractor condition + 2 backgrounds + 2 lighting settings +
  2 table textures + 2 camera configurations = 10.
- Drawer and apple: base + 2 backgrounds + 2 lighting settings + 2 cabinets = 7.

Sources: [pick VA](https://github.com/allenai/SimplerEnv/blob/c701ea271b16b80616d6fed9713c4a50a0adea3b/scripts/rt1_pick_coke_can_variant_agg.sh),
[move VA](https://github.com/allenai/SimplerEnv/blob/c701ea271b16b80616d6fed9713c4a50a0adea3b/scripts/rt1_move_near_variant_agg.sh),
[drawer VA](https://github.com/allenai/SimplerEnv/blob/c701ea271b16b80616d6fed9713c4a50a0adea3b/scripts/rt1_drawer_variant_agg.sh),
and [apple VA](https://github.com/allenai/SimplerEnv/blob/c701ea271b16b80616d6fed9713c4a50a0adea3b/scripts/rt1_put_in_drawer_variant_agg.sh).

## Service task and case selection

[bench_server/protocol/task_catalog.json](task_catalog.json) is an ordered JSON
array with `id`, `family`, `robot`, and `native_horizon` fields. It contains the
15 marked aliases. A service selects one alias and an episode count; episode
index `i` uses reset seed `seed + i`. The separate campaign plan selects one
seeded episode for each canonical task. Neither automatically enumerates the
960-episode VM or 1,992-episode Google VA matrix. State the chosen tasks, seeds,
number of attempts and reference-condition coverage separately. A layout ID,
an appearance variant and a reset seed are not interchangeable sample labels.
See [EVALUATION_PROTOCOL.md](../../EVALUATION_PROTOCOL.md) for budgets, final-step
success and configured horizon extensions.

Changing aliases, texture versions, sensor inputs, seeds, sweeps, or evaluation
horizons changes the evaluated conditions. Record those settings and keep their
scores separate from the default development sample.
