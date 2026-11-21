# Implementation milestones and release decisions

This is the order of work after the owner reviews the specification. Each row targets one five-hour usage window and ends with a verifiable outcome. If a row grows, split it by the first unresolved dependency or by a user flow and finish a coherent subset. Use the measured five-hour balance to judge whether to start another increment. Complete each session's closeout while at least 30% remains. At every increment, record what passed, relevant commits, unknowns, remaining usage, and the exact next step in the root `passdown.md` and a numbered implementation note. Commit the verified increment before starting the next.

## Build in this order

| Milestone | Depends on | Deliver and verify |
| --- | --- | --- |
| I01. Android Studio and Kotlin starting project | Owner approval to start implementation | Run a minimal Compose project on a supported emulator or the physical phone. Pin the project Gradle wrapper, Android Gradle Plugin, SDK levels and JDK. Document the app ID decision and the actual build/test commands. [Setup](developer-setup-and-testing.md) |
| I02. Bridge packaging experiment | I01 | Build the smallest Python library call on ARM64 and the development emulator. Verify offline startup, native packaging, size and timings, and a dated balance with the desktop fixture. Confirm or revisit Chaquopy and the API floor. [Core experiment](core-and-compatibility.md#proof-of-concept-exit-conditions) |
| I03. Read-only core boundary | I02 | Extract the cohesive Calendar, period and balance operations behind the desktop adapters. Characterize extraction with fixed dates and golden outputs. Compare desktop CLI interfaces and run the existing tests. |
| I04. Private JSON store | I02–I03 | Implement app-private storage, canonical schema reads, one writer and complete candidate recovery. Import fixture input through a developer test entry. Verify no mutation from a read, resume after interruption, and check update and process-restart behavior. [Storage](device-storage.md) |
| I05. Calendar navigation and dated balances | I03–I04 | Implement Calendar, bottom navigation, balance picker, today and period close, calendar day selection, and unavailable feedback. Pass `T-CAL-BAL-01` through `07` and `T-CAL-NAV-01`. |
| I06. First use and manual year setup | I04–I05 | Implement welcome, manual date, period and opening review, and prompt from a missing current or future date. An empty store starts with manual schedule confirmation or restore. Require cancellation and exactly-once setup cases. |
| I07. Carryover creation | I06 | Implement adjacent predecessor review, policy caps, fingerprint and validation for applying a new year. Verify time boundaries, stale previews, lots carried once and unchanged source ledgers. |
| I08. Edits and individual entries | I04–I06 | Implement edit day and single entry including status, quarter-hour entry, confirmation, comment preservation, system-row protection, and draft recovery. Pass the day editing cases. |
| I09. History and transaction corrections | I08 | Add inclusive date range, sorting, source and ID detail, and separate correction and deletion reviews. Verify unchanged unrelated IDs and generated records. |
| I10. Maintenance and reconciliation | I07–I09 | Start with a linked-chain preview and recovery. In a separate checkpoint add opening repair, force balance and annual and sick accrual rates if the work needs a split. Verify reviewed generations and source updates with the ledger cases. |
| I11. Expirations and lot extensions | I07–I10 | Implement expiration list and thresholds, lot history, and eligible extensions. Verify inclusive deadlines, warning and disposition, and repeat reads. Link reminders to lot detail. |
| I12. PPL, FMLA, and accounting preferences | I09–I11 | Implement grant/use and overlapping-window behavior, review additional FMLA, history and tour settings, and unknown capacity. Run the parental fixture cases with legacy compatibility. Split settings from parental flows if needed. |
| I13. Report list, summary, Seasonality and Heatmap | I05, I09 | Implement report navigation, year selection and coherent data, then the date and category filters with accessible source details. Verify all three report families and late/cancelled results. |
| I14. Lifecycle, cumulative and balance charts | I11–I13 | Implement lifecycle in one checkpoint if needed and cumulative and balance report families in the next. Cross-check charts and tables with golden fixtures. |
| I15. Yearly comparison, month view, Share and Print | I13–I14 | Implement leap-date mapping, month document and image rendering, a shared report intent and platform print. Verify chart and PDF views and handoff with the signed app on a handset. |
| I16. Compatible backup sharing | I04, I15 | Serialize canonical data into the desktop archive envelope under **Share backup**. Verify MIME, contents and the Android-to-desktop GUI directions with synthetic data. |
| I17. Restore and recovery | I04, I06, I16 | Use file picker, merge/replace, reviewed candidate publication and recovery. Run all four desktop GUI directions and fault cases. An independent checkpoint may cover the Windows GUI fixture once a runner or tester is available. |
| I18. WMS, validation and remaining settings | I09–I12, I17 | In separately verifiable pieces complete WMS and targeted payroll edits, data check and health, Calendar and holiday preferences, and offline help. Verify settings with synthetic data and review the [full parity matrix](../parity.md). |
| I19. Release rehearsal | I01–I18 | Test dark mode, font scaling, compact and larger layouts, TalkBack, physical phone installation, offline and signed app update. Record Android and both desktop builds and the release gate outcomes. Finish real screenshots and app declarations. |
| I20. Play testing and production | I19 and verified publisher account | Install the signed candidate from the internal track. Run eligible closed testing, resolve feedback and apply for production access. The owner approves production rollout after release gates pass. [Google Play sequence](google-play.md#test-tracks-and-first-production-release) |

For grouped rows, commit the first verified subset before extending it. Keep the desktop reference and published interfaces stable during extraction. Any connected source push remains subject to the repository's existing Distribution rules. [Repository working rules](../../../AGENTS.md)

## Draft decisions for owner review

| Decision | Spec default and review point | Owner |
| --- | --- | --- |
| Scope and phone navigation | Include the in-scope parity workflows, including a targeted payroll correction when there are multiple possible matches. Defer the What-if Planner and desktop integrations. Use Calendar, Reports and Settings and the fixed blue Material 3 direction as the starting design. | Project owner at specification review |
| First use and schedules | Require the first actual pay-period date for a new manual setup. Suggest a 26-period schedule that the user can change and confirm. For a known valid adjacent year, offer its calculated successor and carryover review. | Project owner when reviewing setup screens |
| Accounting controls | Keep annual and sick rate editing in a shared advanced form. First release configuration edits target the work tour, time increment, supported defaults and FMLA history. Show agency policy used and preserve compatible imported policy fields. Evaluate direct policy editing during I12 using real rule coverage. | Project owner and accounting implementer |
| Bridge and minimum Android level | Pilot in-process Python from Kotlin and provisionally support API 26 and higher. Decide after verified native packaging and parity. | Android implementer and project owner after I02 |
| Backup and OS testing | Keep canonical records private and use explicit share and restore. Verify Windows and Linux using actual GUI entry points. Identify the Windows test environment before release rehearsal. | Project owner and desktop test owner |
| Release identity and approval | Confirm the permanent app ID, account type, publisher identity, key custody, tester group and rollout. Recheck Play requirements before every upload. | Play account owner |

## Specification review checklist

- [x] The pinned reference identifies source and published desktop build. Every inventoried workflow has a disposition, a rule or source, and an acceptance case.
- [x] All in-scope parity rows link to editable-sourced annotated screen images. Report and maintenance flows cover shared states for empty, error, cancellation and recovery.
- [x] Kotlin and Compose UI, the CLI/library boundary, compatible private JSON, Share and restore are specified with verification gates.
- [x] Android Studio, virtual or physical phones, testing and Play account and release steps have beginner walkthroughs.
- [x] Implementation is divided into bounded, reviewable checkpoints with commits and passdowns.
- [ ] The owner reviews draft choices and approves implementation.
- [ ] Run the bridge proof of concept, all Android acceptance cases, and the Linux and Windows GUI round trips on the real builds before release.
