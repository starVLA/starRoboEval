# Reviewed source-selection candidates

The September 10 read-only discovery inspected only 14 campaign roots explicitly
named in the migrated reports. It found 98 terminal runner directories: LIBERO 40,
SimplerEnv 17, SIMPLE 12, RoboCasa365 21, Tabletop 4 and RoboDojo 4. Pilot and coverage
identities remain separate. One original Dojo prelaunch claim has no terminal
runner status; its retained report remains authoritative and it is excluded
from automatic adoption. No active runner statuses were observed in these roots.

[Discovery evidence](2026-09-10-discovery.json) records every inspected campaign,
its hash, selected cases and exclusions. The six source lists live at
`../<benchmark>/adoptions/2026-09-10-source-list.json`; they contain explicit
absolute run paths and all 204 recorded MP4 artifact keys, with camera identities
and English descriptions. The original run manifests confirm null provider/model
identity for every selected run.

The [read-only inspection](2026-09-10-inspection.json) ran the reviewed
`result_index.inspect_run` against all 98 original runs: all passed record,
closure, identity, media-path and hash-stability checks. The longest destination
component is 200 bytes, below the 240-byte tool limit. This did not copy media or
create remote outputs. It did not inspect live mailboxes, native assets or source
snapshots, call providers or launch tasks. The adoption command must still use a
new destination, such as `../<benchmark>/adoptions/2026-09-10-historical`.
