# Passdown 12 — Android data scope revision

November 21, 2026. Android accepts compatible FedLeave backups through **Restore backup**. Holiday dates come from on-device generation or a restored backup cache. Manual **Reconcile entry** works with transactions already in the ledger.

- Updated the requirements, parity matrix, acceptance cases, implementation roadmap, and data and settings boards to reflect the approved scope.
- Start a visual review with [Reports](../sections/report-screens.md) or [Data and preferences](../sections/data-settings-screens.md). The backup picker, Sharesheet and restore review are in the Data and preferences section.
- Verified 47 parity and test pairs and all 44 phone workflows. All 19 image boards rebuilt byte-for-byte, and the backup picker was the sole inbound picker. The focused desktop suite passed 13 tests on backups, holiday calculations and manual reconciliation.
- The five-hour window showed 95% remaining at the start and 89% at the revision checkpoint.
- Resume at [implementation milestone I01](../sections/implementation-milestones.md#build-in-this-order) after specification approval.
