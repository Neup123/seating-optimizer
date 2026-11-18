# Stable identities for imported registrations

Guest and party identity is used by pair rules, pins, staged preferences, manual placement instructions and saved configurations. An identity based on a **spreadsheet row number** can silently reassign a rule after someone inserts, removes or sorts rows; that is unsafe.

## Current import contract

- When a stable **Group ID** source field is mapped, it remains the authoritative group identity and can span individually named rows.
- Otherwise each registration receives `registration:stable:<20-hex-id>`, derived deterministically from the Unicode-normalized registration name. Each member receives `member:<20-hex-id>:<index>`. Reordering rows, inserting another registration, or changing unrelated attributes does not change identifiers.
- A changed/corrected registration name is treated as a **different identity** rather than silently targeting another registration. Existing rules/manual directions referring to the prior identity must be reviewed and rebound.
- An edited party size can introduce/delete member indices; references to removed members fail instead of targeting a different party. A stable source Group ID does not make member IDs magically persistent across a renamed individual registration — use consistent source names or define new mapping logic deliberately.

## Migration from old row-based IDs

Older imports used identifiers such as `registration:2` and `r2-m1`. They are intentionally **not** silently mapped onto new name-derived identifiers. Export saved configuration before re-import; inspect pinned pair rules and manual placements. The UI warns when a rule target or manual direction is missing from the new guest list. Remove/rebind those records explicitly before solving. The backend rejects stale targets instead of accidentally seating the wrong person.

The hash is an **identity discriminator, not encryption**. Original names and other identifying data may remain in planning storage and exports. See browser-privacy documentation for retention.

## Verification

`tests/test_stable_identity.py` exercises sorting, added/removed registrations, attribute edits, changed names and explicit Group IDs. The existing imported split-family/print and real browser tests are updated to avoid assuming an arbitrary row number.

**Coverage/exclusions:** stable IDs cover the importer's name-derived default IDs and its generated member IDs. They do not supply universal IDs across legal name changes, duplicate names, two differently spelled records for one person, independent export systems or identities shared across organizations. Explicit persistent source identifiers are preferred for those use cases.
