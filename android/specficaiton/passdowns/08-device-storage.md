# Passdown 08 — Device storage and interchange

November 20, 2026. Desktop reference `7041ce9e9921dd4c407595ed3269de1aca43e699`. The five-hour window had 74% remaining at the checkpoint.

- Specified the same canonical JSON working layout and schema-v1 archive as the existing CLI. Android keeps the working store private, uses a system file picker for restore and Android's Sharesheet for backups, charts and report images or documents. [Storage specification](../sections/device-storage.md)
- Chose a complete private candidate generation and atomic active pointer as the draft storage design. Specified merge and replace precedence, complete prevalidation, compatibility with older single-year backups, crash recovery, local reinstall recovery and timed cleanup of temporary shares.
- Added four GUI round-trip directions as a release gate, with a common fixture including IDs, settings, holiday data, carryover and PPL/FMLA. Added storage failure, reinstall, offline and URI checks. [Storage acceptance](../testPlan.md#storage-and-interchange-acceptance)
- Passed 127 focused desktop tests covering file interchange, data and maintenance, WMS and holidays, failure cases and parental rules. The Android generation mechanism, real phone sharing, and Windows and Linux GUI round trips remain implementation release checks.

Start milestone 9 at the [beginner tools and testing plan](../specificationPlan.md#plan-beginner-setup-and-testing). Explain Studio, SDKs, the emulator and a physical phone, where the shared core may require a host Python install and what checks run at each level. Keep the minimum supported OS separate from the Play target API and document a release rehearsal.
