# Passdown 11 — Specification review and implementation handoff

November 20, 2026. The Android specification draft is complete. The source reference remains `7041ce9e9921dd4c407595ed3269de1aca43e699`, published as `0.2.2.dev0+g7041ce9e`. The desktop source, tests and published installer mirror were unchanged by the specification commits.

The session began at 91% remaining in the five-hour window and closed at 62% remaining. Work ended because the specification was complete.

## Deliverables and decisions

- The [specification index](../specification.md) leads to functional requirements, phone mockups, the library boundary, locally stored desktop JSON, Android backup and report sharing, testing and the Play release steps.
- The [implementation milestones](../sections/implementation-milestones.md) define 20 ordered, five-hour-sized work increments with acceptance conditions, commits and passdowns. Start with I01 after owner review, then verify the shared Python bridge in I02 before implementation depends on it.
- Reviewed the year-setup default, native navigation, sick accrual edit and payroll reconciliation. The draft asks for a genuine first pay-period date, suggests 26 periods for manual setup, and provides annual and sick rate choices and a reviewed **Reconcile entry** action.
- The M1 and M2 drafts were captured together in the initial local checkpoint. Each milestone completed after that has its own local commit. Review the final scope, advanced accounting controls, Play publisher identity, app ID and device availability before starting the corresponding work.

## Verification and release gates

- Matched all 48 parity rows to acceptance cases and all 45 in-scope workflows to rendered images and visible annotations. Rebuilt 19 image boards from editable sources with identical bytes. The boards contain 72 screen IDs and 95 numbered callouts. Validated local paths and anchors.
- Confirmed the sick accrual fixture in a disposable desktop ledger. A change from 4 to 3 h effective July 12 updates 13 sick rows and yields 111 h sick and 114 h annual at close.
- The full Linux desktop suite in the sandbox recorded 1,009 passes, 3 skips, and 4 MCP subprocess timeouts. All four timed-out tests passed on a focused rerun with ordinary subprocess permissions. The mockup renderer passed Ruff.
- The handset, signed Android candidate, and four actual Linux/Windows GUI backup round trips require implementation. Arrange a Windows runner, VM or tester before production release. The native mockups are design references.

## Resume point

Review the [scope and draft owner decisions](../sections/implementation-milestones.md#draft-decisions-for-owner-review). If approved, begin **I01** by opening Android Studio on the development computer, setting up its SDK and target, and running a minimal Kotlin Compose template on a phone or emulator. Record actual versions and results in the next passdown before starting I02. Keep the Play account, closed-testing and release tasks on their own schedule.
