# Passdown 02 — Ledger and leave-year parity

November 20, 2026. Milestone 2 of the [Android specification plan](../specificationPlan.md#write-the-specification-in-five-hour-usage-windows) is complete. Desktop source remains `7041ce9e9921dd4c407595ed3269de1aca43e699`, published as `0.2.2.dev0+g7041ce9e`. The tracked source and test files at this checkout match that revision.

## Completed

- Wrote the [ledger and leave-year requirements](../sections/ledger-and-leave-years.md) and linked them from the [specification index](../specification.md) and [Calendar flow](../sections/calendar-balances.md). The requirements cover first use and missing years, manual and carryover openings, reconciliation and recovery, edits and history, balance adjustments, accrual, caps, expiration, and PPL/FMLA.
- Added 16 reviewed [parity rows](../parity.md#ledger-and-leave-year-workflows), from `CAL-YEAR-01` through `PARENT-02`, with screen or flow IDs and corresponding [acceptance cases](../testPlan.md#ledger-and-leave-year-acceptance). The existing 8 Calendar cases remain part of the baseline.
- Rechecked [issue #149](https://github.com/joshua-guthrie/fedleave/issues/149). The draft proposes a contextual setup prompt, confirmation with a carryover suggestion when appropriate, and return to the original action. Month browsing remains read-only. A fresh or manually reset balance still opens at Today.
- The draft distinguishes editing a day total from adding, correcting, or deleting one record. It protects generated activity during phone edits and retains a separate form for balance adjustments. Individual corrections and approved lot extensions are proposed phone equivalents for existing CLI capabilities. The visual milestone still owns their annotated layouts.

## Verification

- The focused desktop suite passed 332 tests, including GUI day edit and history, manual and carryover creation, accrual changes, transaction corrections and deletion, expiration, interrupted reconciliation, and PPL/FMLA.
- Disposable CLI fixtures confirmed annual day balances of 89 h, 88.5 h after replacing two entries, and 92 h after clearing the category. Sick remained 19 h and retained its transaction ID. The carryover fixture produced openings of 240 h annual, 600 h sick, and 24 h credit without changing the source. The accrual fixture updated 13 annual rows and ended at 140 h annual and 124 h sick.
- Additional disposable fixtures confirmed individual correction and deletion by ID, a future balance with planned and denied entries, and the 32 h year-end use-or-lose result that includes scheduled leave. The dedicated Calendar calculation and the month accrual forecast differ by 8 h in that fixture. A linked successor retained two original PPL windows with 472 h each and 472 h available.
- The cross-reference check matched all 24 parity IDs to acceptance cases and all 16 new rows to written requirements.
- Five-hour usage was 98% remaining at the start, 97% before drafting, and 91% at closeout. This session stops at the completed milestone.

## Where to resume

Start milestone 3 in [parity.md](../parity.md). Add the desktop UI entry points for **Reports**, **Data and restore**, and **Settings and help**, beginning with the Calendar menu inventory and the analytics companion. Inventory chart types, comparison filters, Analytics tabs and drill-downs, and month print or image formats. Then inspect backup restore, leave-year selection and data validation, holidays and preferences, and desktop-only backend selection and update tools. Give each an Android disposition or name the decision needed. Record Planner deferral and the desktop-only integrations from the approved plan. [Calendar menus](../../../src/fedleave_gui/main_window.py#L1511) · [Analytics companion](../../../src/fedleave_analytics) · [Data commands](../../../src/fedleave/commands/data.py)

Review whether payroll reconciliation and legacy opening repair need direct Android entry points while reviewing data maintenance. Carry over unresolved questions about the empty-store schedule suggestion, sick accrual editing, and placement of maintenance actions for the phone flows. Screen annotations, handset tests, the core implementation choice, and desktop backup round trips are assigned to later milestones. No Android or desktop application implementation is part of this draft.
