# FedLeave Android specification

## Product and reference build

FedLeave for Android brings the desktop leave-accounting workflows in scope for the first release to a phone. The user can check a balance, inspect the calendar, and manage leave locally. The phone interface uses Android's Sharesheet for user-initiated sharing of reports, images, and compatible backups.

The approved [specification plan](specificationPlan.md) sets the scope and review milestones. Each parity row identifies the desktop behavior, the Android surface, and the acceptance case that will prove it.

| Desktop reference | Pinned identity |
| --- | --- |
| GitHub stable release | `beta`, build `0.2.2.dev0+g7041ce9e` |
| Source revision | `7041ce9e9921dd4c407595ed3269de1aca43e699` |
| Installer mirror revision | `80313ff` |
| Baseline check | Verified November 20, 2026 against the release record, tag, and installer build metadata. |

Use the pinned source to resolve differences between the older documentation and shipped behavior. Record a baseline change before updating results or parity expectations. [Stable release](https://github.com/joshua-guthrie/fedleave/releases/tag/beta) · [Pinned source](https://github.com/joshua-guthrie/fedleave/tree/7041ce9e9921dd4c407595ed3269de1aca43e699) · [Installer build identity](../../installers/BUILD.txt)

## Specification index

| Topic | Draft coverage |
| --- | --- |
| [Feature parity matrix](parity.md) | Calendar, ledger, reports, data maintenance, preferences, and scope exceptions. |
| [Calendar balances](sections/calendar-balances.md) | One date-driven balance panel, its screen states, and the rules for today, historical dates, and pay-period ends. |
| [Phone navigation and Calendar screens](sections/calendar-screens.md) | Annotated first use, balance states, Calendar navigation, day editing, history and corrections. |
| [Ledger and leave years](sections/ledger-and-leave-years.md) | Missing-year setup, editing and history, accrual, carryover, expiration, and PPL/FMLA. |
| [Acceptance plan](testPlan.md) | Synthetic fixtures and reference results for Calendar, ledger, and leave-year cases. |
| [Reports, data, and preferences](sections/reports-data-and-preferences.md) | Report calculations and display, compatible sharing and restore, imports, preferences, help, and platform equivalents. |
| Architecture, release, and implementation milestones | Later milestones record core decisions, testing setup, Google Play steps, and bounded implementation work. |

## Decisions carried into the first release

- Use Kotlin and Compose with Material 3 as the starting stack. Scope the first release using the [GitHub issue decisions](specificationPlan.md#github-issues-reflected-in-this-draft). The What-if Planner is deferred. Android's interface and help use app language, and MCP and AI are outside the Android scope.
- Keep the phone's working datastore in private, desktop-compatible JSON. Portable backups use the existing FedLeave archive format. A user opens the system file picker for restore and the Sharesheet for outbound sharing.
- Use one Calendar balance panel for today, any selected date, and a pay-period closing date. Show future balances as projections. The [Calendar section](sections/calendar-balances.md) defines the first slice and the decisions that still need review.
