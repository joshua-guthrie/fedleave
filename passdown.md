# FedLeave Android planning passdown

## Where to resume

The Android specification draft is complete through milestone 11, with the November 21 [data scope revision](android/specficaiton/passdowns/12-data-scope.md). Start with the [specification index](android/specficaiton/specification.md) and [draft decisions for owner review](android/specficaiton/sections/implementation-milestones.md#draft-decisions-for-owner-review). The first implementation checkpoint after review is **I01**, a minimal Compose project opened and run from Android Studio.

Specification work finished with 62% of the five-hour window remaining. Milestones 3–11 each have their own local commit.

## Decisions to carry forward

- The version-controlled project root is `android/`. The planning folder uses the requested spelling `specficaiton/`.
- The phone spec will account for each desktop capability and link every phone workflow to annotated mockups and acceptance tests. Kotlin, Compose, and Android Studio are the recommended starting point. The existing desktop CLI stays available through its callable core.
- Android Calendar should have one **Balances** panel. It opens at **As of today**. A date picker marks pay-period ends, and selecting a date updates the same panel. Show future dates as projections and explore expandable earned and used details for pay periods.
- Prompt from the task when Today or a deliberate future request needs a missing leave year. Preview before creating, resolve by stored dates, and suggest carryover from an eligible adjacent source. [Draft ledger requirements](android/specficaiton/sections/ledger-and-leave-years.md)
- Keep the desktop-compatible JSON store on the phone. **Restore backup** is the sole inbound file workflow. Use the Android Sharesheet for supported reports, images, and existing-format backups.
- Treat 30% remaining in the five-hour window as the cutoff. Record a passdown and make a local commit at each specification milestone. Split large milestones by screen or behavior, and record a final checkpoint if the window ends mid-milestone.

## Previous plan publication

- Commit `79d782e` added the initial plan and established `untracked/security/` as the ignored local location for the consolidated report, findings, evidence, and review working files. The formerly tracked report remains in older Git history.
- The initial commit passed CI and Distribution and produced installer commit `12c2812`. GitHub served it from the latest stable release. [Initial Distribution](https://github.com/joshua-guthrie/fedleave/actions/runs/44658705158)
- Commit `7041ce9` added the balance-panel workflow. CI and Distribution passed. The latest stable release points to that source commit, identifies the build as `0.2.2.dev0+g7041ce9e`, and has five verified assets matching installer commit `80313ff`. Local `master` is synced. [Follow-up CI](https://github.com/joshua-guthrie/fedleave/actions/runs/44660654466) · [Follow-up Distribution](https://github.com/joshua-guthrie/fedleave/actions/runs/44660654707) · [Stable release](https://github.com/joshua-guthrie/fedleave/releases/latest)
- The usage check before final release verification showed 23% remaining in the five-hour window. The plan and its publication are complete.
