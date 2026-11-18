# Browser privacy, data minimization and retention

The optimizer is a stateless local API plus a browser client. Browser state is **not** protected by a login or backed up by the API.

## Data kept on this browser

- The active session is saved to `localStorage` under `seating-optimizer:session:v2`: imported guest names/attributes, effective mapping, rule references, venue geometry, plans, scores, print/review preferences and selected state.
- Reusable venue/rule templates are saved under `seating-optimizer:templates:v2`. **Templates may contain identifying party references and free-form names in rule definitions.** Do not assume a template is personal-data-free.
- Legacy sessions/templates from v1 keys are read for compatibility but removed by the explicit erase action.
- After a successful guest import, only the source filename is retained in the active session; the base64 source spreadsheet is immediately discarded. On restoration from an older session, source bytes are also removed from the next saved snapshot. To re-import a sheet, select it again.

## Retention policy

The active `v2` session expires after **7 days without saving changes**. Expired snapshots are removed on the next load; no background scheduler or server sweep is used. Existing pre-policy sessions that lack a timestamp are migrated to the 7-day policy when loaded. Browser storage is best-effort and may disappear earlier due to quotas, private browsing or browser clearing.

Reusable templates have no automatic expiry because they represent intentional saved configuration, but may include guest-identifying references. Operators should export any guest-free templates to separately controlled files and regularly remove obsolete ones. This is an **on-device** policy, not a guarantee of deletion from downloads, backups, screenshots, synchronized browser profiles or OS caches.

## Manual erase (recommended on shared computers)

Open **Guest import → Clear saved guest data**, read the warning and choose **Erase saved data** to delete both versions of this application's saved session and template keys and reset current in-memory state. There is a separate **Cancel** option. The action deliberately deletes saved templates too, because their rule descriptions/targets may contain guest identities. Export truly reusable, guest-free configurations before erasing.

Starting a new empty session is **not** the same as erasing saved personal data. Erasing local data never deletes original spreadsheets or previously exported plans from other locations.

## Threat model and limits

The browser origin may read its own localStorage. Any user with access to that browser profile, or any script executing in that same origin, may be able to access stored content. Do not run the unauthenticated API on a public interface; issue #86 addresses network controls. Secure disposal outside localStorage, browser sync and multi-user account retention are outside the application's current capabilities.

## Verification and exclusions

`tests/ui/retention.test.mjs` covers the seven-day expiry, removal of restored base64 spreadsheet content and two-step deletion of all four application keys. It does **not** verify deletion from file downloads, browser backups, OS caches, browser sync or storage used by unrelated domains. Browser manual acceptance and accessibility review are required before using the clear action with real guest data.
