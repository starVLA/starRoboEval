> Historical anonymous code-agent evidence. Model/provider identity remains unverified.
> Original document: `examples/simBenchmarks/LIBERO/TASK_CHECKLIST.md` at source revision `29cb55d`;
> original SHA256: `1af3c780e6026e14b7ef18be7c2a22726f2011f4e9dff09b2cd25024fc665af7`. Only documentation links were rebased.

# LIBERO task checklist and pause checkpoint

User requested on 2026-09-07: let case037 finish, then pause LIBERO.
Case037 has now closed successfully and all four offline postprocessors passed.
LIBERO is paused:38/130 closed,25 native successes and13 failures,92 unattempted.
Do not launch case038 or any later entry until the user resumes. SIMPLE and
RoboCasa coverage are not paused by this request.

Frozen campaign: `runs/libero-task-coverage-20260907-001`.
Campaign SHA256: `2c956736a8d883278df16e8cf70fc9ddc150b0f4d27b86f76c2f01e041b00d12`.
All130 suite-task identities remain in the denominator. Each has one selected
initial state and one allowed attempt; no failure/error/claim authorizes a retry.
This is a checkpoint, not a live dashboard or a homogeneous model score.
Null first-success fields mean no recorded native success, not an estimate.
See [detailed evidence](reports/2026-09-07-task-coverage.md)
and [rollout index](rollouts/README.md) for caveats and original videos.

| Case | Suite/task identity | State | Native success | Controls | Decisions | First control / decision |
| --- | --- | --- | --- | ---: | ---: | --- |
| 000 | libero_spatial/task-0 | completed | true | 130 | 26 | 130 / 26 |
| 001 | libero_spatial/task-1 | completed | true | 160 | 33 | 160 / 33 |
| 002 | libero_spatial/task-2 | completed | true | 187 | 38 | 187 / 38 |
| 003 | libero_spatial/task-3 | completed | true | 183 | 37 | 183 / 37 |
| 004 | libero_spatial/task-4 | completed | false | 389 | 82 | null |
| 005 | libero_spatial/task-5 | completed | true | 84 | 18 | 84 / 18 |
| 006 | libero_spatial/task-6 | completed | false | 213 | 44 | null |
| 007 | libero_spatial/task-7 | completed | true | 392 | 79 | 392 / 79 |
| 008 | libero_spatial/task-8 | completed | true | 247 | 52 | 247 / 52 |
| 009 | libero_spatial/task-9 | completed | true | 196 | 41 | 196 / 41 |
| 010 | libero_object/task-0 | completed | false | 224 | 48 | null |
| 011 | libero_object/task-1 | completed | true | 228 | 47 | 228 / 47 |
| 012 | libero_object/task-2 | completed | true | 362 | 74 | 362 / 74 |
| 013 | libero_object/task-3 | completed | true | 197 | 41 | 197 / 41 |
| 014 | libero_object/task-4 | completed | true | 167 | 35 | 167 / 35 |
| 015 | libero_object/task-5 | completed | true | 85 | 18 | 85 / 18 |
| 016 | libero_object/task-6 | completed | true | 113 | 24 | 113 / 24 |
| 017 | libero_object/task-7 | completed | true | 117 | 24 | 117 / 24 |
| 018 | libero_object/task-8 | completed | true | 103 | 22 | 103 / 22 |
| 019 | libero_object/task-9 | completed | false | 103 | 22 | null |
| 020 | libero_goal/task-0 | completed | true | 83 | 17 | 83 / 17 |
| 021 | libero_goal/task-1 | completed | true | 112 | 25 | 112 / 25 |
| 022 | libero_goal/task-2 | completed | false | 436 | 89 | null |
| 023 | libero_goal/task-3 | completed | false | 436 | 89 | null |
| 024 | libero_goal/task-4 | completed | true | 179 | 37 | 179 / 37 |
| 025 | libero_goal/task-5 | completed | false | 370 | 75 | null |
| 026 | libero_goal/task-6 | completed | true | 76 | 16 | 76 / 16 |
| 027 | libero_goal/task-7 | completed | true | 105 | 22 | 105 / 22 |
| 028 | libero_goal/task-8 | completed | true | 198 | 40 | 198 / 40 |
| 029 | libero_goal/task-9 | completed | false | 220 | 45 | null |
| 030 | libero_90/task-0 | completed | false | 196 | 41 | null |
| 031 | libero_90/task-1 | completed | false | 237 | 51 | null |
| 032 | libero_90/task-2 | completed | false | 286 | 59 | null |
| 033 | libero_90/task-3 | completed | true | 157 | 34 | 157 / 34 |
| 034 | libero_90/task-4 | completed | true | 381 | 78 | 381 / 78 |
| 035 | libero_90/task-5 | completed | false | 263 | 55 | null |
| 036 | libero_90/task-6 | completed | false | 332 | 69 | null |
| 037 | libero_90/task-7 | completed | true | 76 | 16 | 76 / 16 |
| 038 | libero_90/task-8 | unattempted | null | — | — | null |
| 039 | libero_90/task-9 | unattempted | null | — | — | null |
| 040 | libero_90/task-10 | unattempted | null | — | — | null |
| 041 | libero_90/task-11 | unattempted | null | — | — | null |
| 042 | libero_90/task-12 | unattempted | null | — | — | null |
| 043 | libero_90/task-13 | unattempted | null | — | — | null |
| 044 | libero_90/task-14 | unattempted | null | — | — | null |
| 045 | libero_90/task-15 | unattempted | null | — | — | null |
| 046 | libero_90/task-16 | unattempted | null | — | — | null |
| 047 | libero_90/task-17 | unattempted | null | — | — | null |
| 048 | libero_90/task-18 | unattempted | null | — | — | null |
| 049 | libero_90/task-19 | unattempted | null | — | — | null |
| 050 | libero_90/task-20 | unattempted | null | — | — | null |
| 051 | libero_90/task-21 | unattempted | null | — | — | null |
| 052 | libero_90/task-22 | unattempted | null | — | — | null |
| 053 | libero_90/task-23 | unattempted | null | — | — | null |
| 054 | libero_90/task-24 | unattempted | null | — | — | null |
| 055 | libero_90/task-25 | unattempted | null | — | — | null |
| 056 | libero_90/task-26 | unattempted | null | — | — | null |
| 057 | libero_90/task-27 | unattempted | null | — | — | null |
| 058 | libero_90/task-28 | unattempted | null | — | — | null |
| 059 | libero_90/task-29 | unattempted | null | — | — | null |
| 060 | libero_90/task-30 | unattempted | null | — | — | null |
| 061 | libero_90/task-31 | unattempted | null | — | — | null |
| 062 | libero_90/task-32 | unattempted | null | — | — | null |
| 063 | libero_90/task-33 | unattempted | null | — | — | null |
| 064 | libero_90/task-34 | unattempted | null | — | — | null |
| 065 | libero_90/task-35 | unattempted | null | — | — | null |
| 066 | libero_90/task-36 | unattempted | null | — | — | null |
| 067 | libero_90/task-37 | unattempted | null | — | — | null |
| 068 | libero_90/task-38 | unattempted | null | — | — | null |
| 069 | libero_90/task-39 | unattempted | null | — | — | null |
| 070 | libero_90/task-40 | unattempted | null | — | — | null |
| 071 | libero_90/task-41 | unattempted | null | — | — | null |
| 072 | libero_90/task-42 | unattempted | null | — | — | null |
| 073 | libero_90/task-43 | unattempted | null | — | — | null |
| 074 | libero_90/task-44 | unattempted | null | — | — | null |
| 075 | libero_90/task-45 | unattempted | null | — | — | null |
| 076 | libero_90/task-46 | unattempted | null | — | — | null |
| 077 | libero_90/task-47 | unattempted | null | — | — | null |
| 078 | libero_90/task-48 | unattempted | null | — | — | null |
| 079 | libero_90/task-49 | unattempted | null | — | — | null |
| 080 | libero_90/task-50 | unattempted | null | — | — | null |
| 081 | libero_90/task-51 | unattempted | null | — | — | null |
| 082 | libero_90/task-52 | unattempted | null | — | — | null |
| 083 | libero_90/task-53 | unattempted | null | — | — | null |
| 084 | libero_90/task-54 | unattempted | null | — | — | null |
| 085 | libero_90/task-55 | unattempted | null | — | — | null |
| 086 | libero_90/task-56 | unattempted | null | — | — | null |
| 087 | libero_90/task-57 | unattempted | null | — | — | null |
| 088 | libero_90/task-58 | unattempted | null | — | — | null |
| 089 | libero_90/task-59 | unattempted | null | — | — | null |
| 090 | libero_90/task-60 | unattempted | null | — | — | null |
| 091 | libero_90/task-61 | unattempted | null | — | — | null |
| 092 | libero_90/task-62 | unattempted | null | — | — | null |
| 093 | libero_90/task-63 | unattempted | null | — | — | null |
| 094 | libero_90/task-64 | unattempted | null | — | — | null |
| 095 | libero_90/task-65 | unattempted | null | — | — | null |
| 096 | libero_90/task-66 | unattempted | null | — | — | null |
| 097 | libero_90/task-67 | unattempted | null | — | — | null |
| 098 | libero_90/task-68 | unattempted | null | — | — | null |
| 099 | libero_90/task-69 | unattempted | null | — | — | null |
| 100 | libero_90/task-70 | unattempted | null | — | — | null |
| 101 | libero_90/task-71 | unattempted | null | — | — | null |
| 102 | libero_90/task-72 | unattempted | null | — | — | null |
| 103 | libero_90/task-73 | unattempted | null | — | — | null |
| 104 | libero_90/task-74 | unattempted | null | — | — | null |
| 105 | libero_90/task-75 | unattempted | null | — | — | null |
| 106 | libero_90/task-76 | unattempted | null | — | — | null |
| 107 | libero_90/task-77 | unattempted | null | — | — | null |
| 108 | libero_90/task-78 | unattempted | null | — | — | null |
| 109 | libero_90/task-79 | unattempted | null | — | — | null |
| 110 | libero_90/task-80 | unattempted | null | — | — | null |
| 111 | libero_90/task-81 | unattempted | null | — | — | null |
| 112 | libero_90/task-82 | unattempted | null | — | — | null |
| 113 | libero_90/task-83 | unattempted | null | — | — | null |
| 114 | libero_90/task-84 | unattempted | null | — | — | null |
| 115 | libero_90/task-85 | unattempted | null | — | — | null |
| 116 | libero_90/task-86 | unattempted | null | — | — | null |
| 117 | libero_90/task-87 | unattempted | null | — | — | null |
| 118 | libero_90/task-88 | unattempted | null | — | — | null |
| 119 | libero_90/task-89 | unattempted | null | — | — | null |
| 120 | libero_10/task-0 | unattempted | null | — | — | null |
| 121 | libero_10/task-1 | unattempted | null | — | — | null |
| 122 | libero_10/task-2 | unattempted | null | — | — | null |
| 123 | libero_10/task-3 | unattempted | null | — | — | null |
| 124 | libero_10/task-4 | unattempted | null | — | — | null |
| 125 | libero_10/task-5 | unattempted | null | — | — | null |
| 126 | libero_10/task-6 | unattempted | null | — | — | null |
| 127 | libero_10/task-7 | unattempted | null | — | — | null |
| 128 | libero_10/task-8 | unattempted | null | — | — | null |
| 129 | libero_10/task-9 | unattempted | null | — | — | null |

Before resuming, re-read the frozen coordinator state and retainedcase037's
terminal result and closed-only postprocessors. The next planned
unclaimed case is038, but this is not authorization to launch it. Preserve
permanent claims and failed/error attempts, create a fresh isolated policy actor
for each newly authorized task, and never edit the frozen manifest to skip tasks.
