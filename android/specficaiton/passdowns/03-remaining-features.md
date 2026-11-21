# Passdown 03 — Reports, data, and preferences

November 20, 2026. Milestone 3 is complete against desktop source `7041ce9e9921dd4c407595ed3269de1aca43e699`. The session started with 91% of the five-hour usage window remaining. At this checkpoint 87% remained.

- Added reports, data and preferences, and scope dispositions to the [parity matrix](../parity.md#reports). The additional 24 rows have matching [acceptance cases](../testPlan.md#reports-acceptance). Checked the Calendar and Analytics GUI entry points, CLI and companion tools, and relevant reference tests.
- Traced the distinct reports for yearly balance comparison and cumulative usage. Carried six within-year balance series, seven date-mapped year-to-year comparison categories, five Analytics reports, and month preview, share and print into the phone scope. [Requirements and evidence](../sections/reports-data-and-preferences.md)
- Recorded restore, WMS import, validation, legacy repair, advanced payroll reconciliation for review, holiday configuration, accounting preferences, and offline help. Remaining owner decisions include the separate manual payroll action, direct editing of agency-specific rules, and whether to include an opt-in network holiday source.
- The focused desktop suite passed 204 tests on reports, chart and print rendering, data exchange, holidays, WMS HTML and settings.

Start milestone 4 with the [Calendar requirements](../sections/calendar-balances.md#screen-states-to-annotate), the [front-window concept](../mockups/calendar-front-window.png), and the Calendar and ledger rows in the [parity matrix](../parity.md). Draft first launch and missing-year states, one dated balances panel and its picker, then edit and transaction history. Assign every relevant state a visible image callout and link the Calendar requirements to those images. Reports and the maintenance, Data and Settings visuals follow in milestones 5 and 6.
