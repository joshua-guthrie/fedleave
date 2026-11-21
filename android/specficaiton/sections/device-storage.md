# Device storage, backups, and sharing

## Canonical private storage

Use the desktop working datastore's UTF-8 JSON layout. Each complete private store contains `config.json`, `leave_years/<leave-year>.json`, and `holiday_cache/<cache-name>.json` when those files exist. The desktop accounting library interprets the same schema on both platforms. Stored leave-year dates remain inclusive calendar dates and all identifiers keep their desktop meaning. Keep local journals, staging, presentation settings and temporary artifacts outside the canonical store. [Desktop datastore model](../../../src/fedleave/config.py#L142) · [Desktop paths](../../../src/fedleave/storage.py)

Keep the store and local recovery data in internal app-private storage under the platform's no-backup directory. Exclude sensitive content from automatic cloud backups and supported device-to-device and cross-platform transfers, with the rules appropriate to the device version. Test these on the supported device matrix because Android backup behavior varies by version and manufacturer. Open and use all core workflows in airplane mode. For the initial release, use stored holidays, offline federal holiday generation and explicit local ICS selection. The user can opt to send a share copy through a receiving app of their choice. [App-specific internal storage](https://developer.android.com/training/data-storage/app-specific) · [Backup and device transfer controls](https://developer.android.com/identity/data/autobackup)

Uninstalling FedLeave or clearing its app data removes its private working data, local settings, recovery data, and app-scoped temporary files. An update retains the private store. On a replacement or reinstalled phone, select an existing Android or desktop FedLeave backup from the picker. Show this path in first launch and explain it in **Data and backups**. Shared copies already saved by the user or a receiving app remain subject to that destination's behavior. [Backup and restore screens](data-settings-screens.md#backups-and-system-file-picker)

### Write and recovery model

Use one Android storage coordinator for requests that can write. Each read uses a complete, immutable generation of the store. Ordinary edits and multi-file operations build a candidate with the canonical layout in the same private filesystem. Validation operates on that complete candidate. Flush the candidate and required metadata before publishing it. The draft storage design uses an atomic active-generation pointer, with the previous validated generation retained for immediate recovery. Keep the pointer and Android transaction metadata outside the canonical JSON payload. A file-level rename or `AtomicFile` can publish the pointer, with serialized writer access provided by the app. Validate the primitive on target devices. [Android AtomicFile](https://developer.android.com/reference/android/util/AtomicFile)

Use the same plan fingerprint or generation identity for preview and confirmation. If the store changes, ask the user to review again. Release readers only onto a verified complete generation. A crash before publication leaves the prior generation active. A crash after durable publication loads the new complete store and can recover its result without applying the same operation again. If pending metadata or a damaged active store requires recovery, show which complete version can be reopened and recover it before normal viewing or writes. Preserve both candidates while the recovery choice is unresolved. Keep the active generation plus one prior complete recovery generation by default, and clean up abandoned candidates once safe. On low space, an unsuccessful write leaves the current data usable. [Shared core write contract](core-and-compatibility.md#responsibilities-and-data-flow)

For app updates, handle any migration as a candidate write with its own validation and recovery. Keep schema-v1 compatibility while desktop still uses it. Support known additive fields and documented legacy reads. Preserve the previous generation if the update cannot interpret data. Remove only documented superseded legacy history as part of a reviewed normalization or import, and maintain the desktop interpretation of existing rows. Never rewrite the active store just to open a report.

## Portable FedLeave archive

**Share backup** prepares a point-in-time archive with the exact existing desktop envelope. **Restore backup** accepts that archive or the desktop-compatible single-year format. Screens and user help use these labels. [Desktop archive writer and import normalization](../../../src/fedleave/commands/data.py#L286)

| Archive component | Android handling |
| --- | --- |
| `schema_version` | Integer `1`, as in the desktop archive. Unsupported versions require a clear error before writes. |
| `exported_at` and `source_data_dir` | Include existing string fields. Use the compatible ISO timestamp form and a generic Android origin label in the path metadata field. The desktop import ignores that origin field. |
| `config` | Canonical JSON object or `null`. Includes user configuration, accrual, work tour and hour defaults, category policies, FMLA coverage and holiday configuration as applicable. |
| `leave_years` | Object keyed by leave-year identifier as a string. Preserve recorded dates, schedule, transactions with scoped IDs and comments, opening data, valid carryover linkage, lot provenance, approved extensions, captured tours and other canonical metadata. |
| `holiday_cache` | Map of compatible cache filenames without their extensions to canonical JSON payloads, with observed date data. |
| Single-year legacy backup | Recognize the current desktop signature of integer `leave_year`, `transactions` list and `pay_periods` list. Scope review to the supplied year and its dependencies. |

The compatible archive carries canonical configuration and supported ledger history. Desktop UI preferences, Android presentation settings, recent drafts, local recovery generations, raw import files, thumbnails, device paths, and transient report data stay outside that archive. Legacy rows and fields removed by the current desktop importer are legacy audit representations. Apply the same documented normalization to imported data, and preserve known ancestry, original IDs, provenance and understood additive metadata. [Desktop merge implementation](../../../src/fedleave/commands/data.py#L351) · [Legacy normalization](../../../src/fedleave/storage.py#L107)

### Restore review

1. Open the Android document picker for JSON, allow selection from a user-authorized provider, and read the selected content as a stream into private staging or directly through a bounded parser. App reads use the selected URI and transient access. The selected display name is for the review. Storage paths come from validated schema identifiers. [Android Storage Access Framework](https://developer.android.com/training/data-storage/shared/documents-files)
2. Parse UTF-8 JSON and validate the shape, versions, numeric values, unique year-scoped IDs, actual date and period bounds, cache identities and the resulting cross-year graph. Check parent and lot links and policy consistency across existing and supplied ledgers. Validate the complete proposed state, including affected linked years that were already on the phone. Keep the original store untouched on any error. Diagnostics show the problematic year, field or dependency and a recovery action.
3. In **Merge**, preserve current IDs and values on collision, copy distinct incoming records and missing additive fields, insert new years, and keep any existing config or cache file for the same key. In **Replace**, use the archive version of included years, config and cache files, leaving ledger and cache entries absent from the archive intact. A `null` config represents no included configuration to write. Report new years, changed years, kept or replaced IDs and included config/cache effects before confirmation.
4. Review collisions and derived warnings before apply. Retain the candidate when revisiting the review if it is still valid. Re-read the current generation or fingerprint under the writer at confirmation and revalidate the candidate when needed. If a permission is lost, an input changes or the copy is invalid, show the failed step, keep the active data, and allow the user to select a fresh file.
5. Apply one confirmed candidate and open the updated Calendar with a summary of the result. Fault-injection tests must cover a crash during staging, before publication and after publication but before success feedback, as well as out-of-space, interrupted read, stale review and recovery after restart.

## Artifact sharing and lifecycle

Use **Share** for graphs and reports, and **Share backup** for the archive. A format choice precedes the Android Sharesheet when several forms are available. Share the active visible report selection and create a fresh artifact or reuse a verified rendering for the same snapshot and filters.

| Payload | MIME type | Preparation and review |
| --- | --- | --- |
| Chart or month image | `image/png` | Include the title, date, units, plotted values and applicable legend. Select an export resolution that remains readable in the receiving app. |
| Chart or month document | `application/pdf` | Render the selected report with a readable printable layout and consistent chart context. |
| Compatible backup | `application/json` | Snapshot the complete canonical store and include the schema-v1 archive. Tell the user it contains leave records and comments before handoff. |

Write each prepared file under a dedicated app-private share cache and publish only that temporary artifact using a narrowly scoped `FileProvider` content URI. Grant the selected receiver temporary read access and invoke Android's chooser. The app does not need broad shared-storage permissions. Use safe filenames based on the report and dates. Keep a share copy long enough for delayed opening by the receiver. Cancelling the chooser returns to the report or backups screen. Purge old copies on a bounded retention schedule and revoke grants when removing them. Verify the timing with a receiver that opens the URI after the chooser has closed. Print uses a separate platform PDF handoff. [Android sharing](https://developer.android.com/develop/ui/compose/sharing/send) · [FileProvider](https://developer.android.com/reference/androidx/core/content/FileProvider)

## Compatibility and recovery checks

Release acceptance requires four paths using the pinned desktop GUI and a real Android build.

| Direction | Procedure |
| --- | --- |
| Linux GUI → Android | From **Export FedLeave Data** in the existing Linux GUI, prepare the synthetic archive. Select it with Android Restore. Compare the results below. |
| Android → Linux GUI | Use **Share backup**, capture the copy in a receiving app, and use **Import FedLeave Data** from the Linux GUI. Open Calendar and compare results. |
| Windows GUI → Android | Repeat the first direction using the stable Windows installer in a VM, CI Windows environment, or a willing tester's Windows computer. Use the GUI backup path. |
| Android → Windows GUI | Repeat the second direction with the installed Windows GUI and compare Calendar results. |

The same synthetic set must include a manual and a linked year, configurable increments and tour, Unicode and punctuation in comments, annual cap reductions, PPL/FMLA, one approved expiry extension, holidays, and legacy fields. Assert matching class, dates, finite hours, record IDs, canonical settings and report values, with only the permitted legacy normalization. Import a separate older single-year backup. For Merge and Replace, compare excluded and included years, same-ID behavior and retained details. Verify read-only and aborted actions by hash. Repeat on a physical Android handset and record desktop and Android build identities.

If Windows is unavailable during development, leave the Windows verification pending and use a Windows runner or arrange a GUI tester before release. Passing CLI JSON checks on Linux supplies arithmetic and serialization evidence. The GUI paths are a separate compatibility gate. [Storage acceptance cases](../testPlan.md#storage-and-interchange-acceptance)
