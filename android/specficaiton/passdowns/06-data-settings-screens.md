# Passdown 06 — Data, maintenance, and settings screens

November 20, 2026. Desktop reference `7041ce9e9921dd4c407595ed3269de1aca43e699`. The five-hour window had 78% remaining at this checkpoint.

- Added nine annotated boards. They show how to find data settings, share or restore a compatible backup, reconcile payroll entries manually, set local preferences, get help, and review or repair ledger data. They include restore and carryover recovery and parental or expiration details. [Screen annotations](../sections/data-settings-screens.md)
- Linked every one of the 45 in-scope parity rows to its rendered screen IDs. Across milestones 4–6, the sources generate 19 boards, 72 screen IDs and 95 numbered callouts. Validated the images and inspected each board. [Parity matrix](../parity.md) · [Editable settings mockups](../mockups/settings.json)
- The chosen navigation and light palette are design drafts. The system surfaces are illustrative and the proposed manual payroll action and agency-specific rule editing still need owner review.

Start milestone 7 with the [Android stack and CLI plan](../specificationPlan.md#recommend-an-android-stack-and-keep-the-desktop-cli) and the [desktop architecture](../../../docs/ARCHITECTURE.md). Decide what code the CLI and phone should share, how the Android app invokes it, what remains in the desktop adapters, and what testable packaging conditions could overturn the choice. Use the existing case IDs to specify a cross-platform fixture contract. Continue into the storage and compatibility milestone once that boundary is written.
