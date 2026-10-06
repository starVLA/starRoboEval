# Source and artifact cleanup

The 2026-09-20 cleanup removes duplicate result files and redirects from
SimplerEnv, SIMPLE and LIBERO source directories. It does not change scores,
attempt counts or model/provider identity. Historical results here remain
anonymous / unverified.

- [Source cleanup](source_cleanup.json) maps deleted duplicate reports to their
  retained, hash-checked copies and maps moved documentation/tools to new paths.
- [Artifact cleanup](artifact_cleanup.json) maps the three former benchmark
  `rollouts/` directories to `barks/evaluation/anonymous_code_agent/`, with a
  relative path, size and SHA-256 for every archived file. These local artifact
  directories are ignored by Git; they are not included in a fresh clone.

Historical README text, original index files and the earlier
`document_relocation.json` are unchanged. Their old paths describe storage at
the time of that record; resolve those paths through these follow-up indexes.
Archived files retain their original names. New evaluations still use the
current model's `results/<benchmark>/` namespace and descriptive task names.

The source cleanup is recoverable through Git history. The archived videos
and indexes remain in persistent storage; no rollout bytes were deleted.
