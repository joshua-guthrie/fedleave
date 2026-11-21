# Passdown 01 — Desktop baseline and Calendar balances

November 20, 2026. Milestone 1 of the approved Android specification plan is complete.

## Completed

- Pinned published desktop build `0.2.2.dev0+g7041ce9e` to source commit `7041ce9e9921dd4c407595ed3269de1aca43e699` and generated installer commit `80313ff`.
- Created the [specification index](../specification.md), [parity matrix](../parity.md), [Calendar balance requirements](../sections/calendar-balances.md), and [acceptance plan](../testPlan.md). Calendar requirements `CAL-BAL-01` through `CAL-BAL-07` and `CAL-NAV-01` have matching acceptance cases.
- Used the [front-window concept](../mockups/calendar-front-window.png) to identify the single balance panel, the separate editing date, and the pay-period markers. The Calendar screen milestone will annotate the picker and remaining states.
- Reviewed the five open Android-related issues and the historical balance and pay-period tickets. Kept the approved requirements for Android sharing, desktop-compatible private JSON, the initial release scope, and app-only interface labels.

## Verification

- A disposable synthetic ledger verified all expected dated balances, the fixed Today snapshot, matching pay-period closing amounts and activity totals, and separate date markers for payday and period end.
- A second lookup confirmed January 4, 2027 belongs to leave year 2026. The focused desktop regression suite passed all 25 tests.
- The five-hour window showed 90% remaining at the start and 82% at closeout. This session stops at the completed milestone.

## Where to resume

Start milestone 2 in [parity.md](../parity.md). Begin with `CAL-YEAR-01` and [issue #149](https://github.com/joshua-guthrie/fedleave/issues/149). Trace desktop year creation and preview, then specify when the Android app creates a missing year, which defaults and carryover choices the user reviews, and what cancellation preserves. Continue with `CAL-DAY-01` and `CAL-HISTORY-01` in bounded sections.
