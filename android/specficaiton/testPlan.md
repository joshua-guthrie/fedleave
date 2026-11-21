# FedLeave Android acceptance plan

These cases define the pass conditions for Calendar, ledger, and leave-year workflows. Use synthetic data, a fixed local date, and the [pinned desktop source](specification.md#product-and-reference-build) to compute the reference results. Run the phone cases on an emulator first and repeat the picker and accessibility checks on a physical phone when a build is available.

## Calendar balance fixture

Set the app's local Today to **January 16, 2026**. Initialize a manual 2026 leave year starting January 11 with 26 pay periods, 100 h annual and 20 h sick opening balances, and 6 h annual accrual per period. The reference store's sick accrual is 4 h. Use the generated schedule without a payday offset override.

| Effective date | Annual leave used | Status |
| --- | --- | --- |
| January 13 | 8 h | Approved |
| January 16 | 2 h | Approved |
| January 22 | 4 h | Planned |
| January 25 | 3 h | Planned |

The first period runs **January 11–24**, accrues on January 24, and pays on January 30. Expected results from the reference build's date and month logic are recorded here.

| Look-up date | Annual | Sick | Case |
| --- | ---: | ---: | --- |
| January 13 | 92 h | 20 h | A historical date includes the 8 h entry that lands on it. |
| January 16 | 90 h | 20 h | Today includes the additional 2 h entry. |
| January 22 | 86 h | 20 h | Future planned use applies. The first accrual has yet to post. |
| January 24 | 92 h | 24 h | The period closes after adding 6 h annual and 4 h sick. The period used 14 h annual and 0 h sick. |
| January 25 | 89 h | 24 h | The next period's scheduled 3 h use applies after the first close. |
| January 4, 2027 | 233 h | 120 h | The date belongs to the 2026 leave year. Accrual for its last pay period falls later. |

### Reproduce the desktop reference

Use these examples on Linux with the desktop CLI on your path. The environment variable must point to a disposable directory. Reference tool names are for developers writing tests. The Android UI uses the app's own labels.

```bash
fixture_dir="$(mktemp -d)"
fedleave init --year 2026 --leave-year-start 2026-01-11 --pay-periods 26 \
  --annual-accrual 6 --annual-start 100 --sick-start 20 --data-dir "$fixture_dir"
fedleave add --year 2026 --date 2026-01-13 --category annual --used 8 --status approved --data-dir "$fixture_dir"
fedleave add --year 2026 --date 2026-01-16 --category annual --used 2 --status approved --data-dir "$fixture_dir"
fedleave add --year 2026 --date 2026-01-22 --category annual --used 4 --status planned --data-dir "$fixture_dir"
fedleave add --year 2026 --date 2026-01-25 --category annual --used 3 --status planned --data-dir "$fixture_dir"
fedleave balance --year 2026 --as-of 2026-01-24 --json --data-dir "$fixture_dir"
fedleave pay-period --year 2026 --date 2026-01-24 --json --data-dir "$fixture_dir"
fedleave month --year 2026 --month 1 --json --data-dir "$fixture_dir"
fedleave balance --as-of 2027-01-04 --json --data-dir "$fixture_dir"
```

Substitute each date in the expected-results table for the balance command. The month output provides period totals and date markers on any day the commands are run. Its Today field uses the runner's real date. Freeze the calculation clock to January 16 to compare that field directly. The desktop reference checks verified the dated values, inferred leave year, frozen Today snapshot, matching period close, and distinct payday and period-end markers. JSON store hashes matched before and after the dated and period reads.

## Calendar acceptance cases

| Test ID | Procedure | Pass condition |
| --- | --- | --- |
| `T-CAL-BAL-01` | Open Calendar on a fresh launch with the fixture and fixed date. Advance the local clock to January 17 while Today is active. | The only Balances panel shows **As of today**, January 16, annual 90 h, and sick 20 h. The date updates to January 17 and the balances remain 90 h and 20 h. |
| `T-CAL-BAL-02` | Open **Change date**, choose January 13, and confirm. Open it again and dismiss with Back. | The same panel shows January 13 with annual 92 h and sick 20 h. Dismissal leaves the selection and figures in place. |
| `T-CAL-BAL-03` | Inspect the picker and select January 24 using its marked cell or quick choice. Open pay-period details. | January 24 is marked and announced as period end. January 30 is distinct as payday. The panel shows January 24, annual 92 h, and sick 24 h. Details show period 1, its date range, payday, annual 6 h earned and 14 h used, and sick 4 h earned and 0 h used. |
| `T-CAL-BAL-04` | Select January 22, then January 24, then January 25. | The panel labels each **Projected balance** with its date and matches the three dated results. January 22 excludes the January 24 accrual. January 24 excludes January 25's use. |
| `T-CAL-BAL-05` | Choose a future balance date and browse another month, then tap **Today**. Reopen Calendar from a fresh launch after choosing an ordinary date. | Both paths show January and the January 16 Today values. The Today action restores the selected calendar day to January 16. |
| `T-CAL-BAL-06` | With January 13 showing, simulate a failed retrieval for January 22. Also deliver a successful older response after a newer date is chosen. | The requested date displays an unavailable state and retry or date-change action. January 13's values never appear under January 22. A late response leaves the new selection intact. |
| `T-CAL-BAL-07` | Request January 4, 2027 using this fixture and identify the leave year used by the calculation. | Use the 2026 leave year because the date falls in its stored range. Show annual 233 h and sick 120 h through January 4. |
| `T-CAL-NAV-01` | Select January 13 in the balance picker, navigate to February in the main calendar, and choose an editing day. | The calendar follows the navigation. The panel continues showing January 13 and its figures until the user uses **Change date** or **Today**. |

After the existing-year review and navigation cases, compare a snapshot of the canonical datastore before and after. The date picker and balance calculations leave its contents intact. [Calendar requirements](sections/calendar-balances.md#requirements)

## Ledger and leave-year acceptance

Use a fresh copy of the relevant fixture for each case. Inspect both the UI and the canonical JSON. Compare before and after ledger hashes for previews, cancelled actions, and read-only requests. Compare transaction IDs and stored fields for mutations. At the Android implementation stage, test application restart between reviews and saves, as well as the simulated write interruptions below. The desktop tests supply reference accounting fixtures and expected values. The Android workflows remain acceptance targets.

### Desktop fixture variants

Create variants using the reproduction instructions in the Calendar section. Keep the 26-period 2026 schedule starting January 11 unless the test explicitly gives another schedule. For tests that start with a linked store, create the successor from the desktop carryover preview. Keep each fixture in its own disposable directory.

| Fixture | Initial values and transactions |
| --- | --- |
| Calendar | Use the original four scheduled or approved entries from the Calendar balance fixture. January 9, 2027 is its last day. The adjacent next year starts January 10. |
| Editable day | Keep January 13 annual use of 8 h. Enter two approved January 16 annual use rows of 2 h and 1 h and one approved sick use row of 1 h on January 16. Start with annual 100 h, sick 20 h and annual accrual 6 h. Record the three January 16 IDs before editing. |
| Carryover | Start 2026 with annual 280 h and zero annual accrual, sick 496 h with accrual of 4 h, and credit 30 h. There is no usage. The source closes at 280, 600, and 30 h. Use the default carryover policy. |
| Accrual | Start 2026 with annual 10 h and accrual of 4 h, sick 20 h with accrual of 4 h, and no usage. |
| Reconciliation | Adapt the reference test's 2026 source with a 100 h annual closing balance at zero annual accrual, linked 2027 and 2028 successors, and a genuine 4 h annual use row in 2027. Give the genuine row an additive JSON field. |

| Test ID | Procedure | Pass condition |
| --- | --- | --- |
| `T-CAL-YEAR-01` | With only the Calendar year, open on Jan 9, 2027. On Jan 10 try launch and **Today** after the local date advances. In a separate run set Today to Jan 9, browse February, then choose Feb 1 in the balance picker or start a Feb 1 edit. Cancel one proposal and confirm another. Repeat with an empty store, a target beyond two missing years, and an invalid existing ledger for the proposed year. | Jan 9 resolves to 2026. Passive browsing creates nothing. The current or deliberately selected future date proposes 2027 with start Jan 10 and keeps the original action context. Cancel preserves the existing ledger and draft or previous balance selection. Uncovered Today reports an unavailable balance for today. Confirm creates the containing year once and resumes the chosen action. An edit still needs Save. On an empty store offer restore or setup. For consecutive gaps, preview yearly in order and retain only confirmed years if cancelled. Warn about invalid existing data and preserve its file. |
| `T-YEAR-MAN-01` | In a disposable store, choose 2027 starting Jan 10 with 26 periods, 1.25 h annual and 40 h undated travel comp. Test cancellation, 1.10 h at quarter-hour increment, creation after confirmation, and repeated creation. | Preview and cancel preserve the store. Reject the incompatible increment. The confirmed manual year has one authoritative opening for each amount, zero unspecified balances and no predecessor. No expiry date is invented for 40 h travel comp, and missing provenance is visible. Repeated creation preserves the first ledger. |
| `T-YEAR-CARRY-01` | Preview the Carryover fixture into 2027. Change the source after one preview, attempt confirmation, then reload the source fixture and complete a fresh reviewed creation. Repeat schedule review for a 2023 source starting Jan 1 with 27 periods. | The 2027 preview has annual 240 h, sick 600 h, and credit 24 h, with reductions of annual 40 h and credit 6 h. Reject stale confirmation without a destination write. Success makes the new ledger and preserves the source bytes. The 2023 source ends Jan 13, 2024 and the successor starts Jan 14. A source with an inconsistent schedule or a duplicate destination cannot be applied. |
| `T-YEAR-REC-01` | Add 8 h of late 2026 annual use to the Reconciliation fixture and read 2027. Preview and confirm from the 2027 warning. Try again unchanged. In a separate copy interrupt the write between two successors. Also test a missing linked source and linked lot usage exceeding revised entitlement. | Read reports stale carryover and a recomputed opening of 92 h, without changing the stored 100 h. Review shows affected successors. Apply updates the generated state, keeps the genuine 4 h row and its additive field, and yields 88 h as of that row in 2027. The source is unchanged and repeat apply is a no-op. Interruption yields recovery, which restores the original bytes before a fresh review. Missing source and conflicting usage block apply. |
| `T-YEAR-OPEN-01` | Change a manual 20 h annual opening to 25 h with a reason, then try the same on a linked destination. | The independent ledger's one opening is 25 h, without a duplicate opening transaction. The linked year instead opens the carryover guidance and retains its opening and lineage. |
| `T-CAL-DAY-01` | Load the Editable day fixture. On Jan 16 open the two annual rows totalling 3 h. Enter 3.5 h annual use and a comment with quotes and punctuation. Back out of review, then confirm. Clear that category in a subsequent save. Separately edit a day with an automatic accrual. Simulate a write failure in another copy. | Review shows 3 h to 3.5 h and the rows replaced. Back preserves the 3.5 h draft and the saved annual balance of 89 h. Confirm yields annual 88.5 h and sick 19 h, keeping the sick ID and exact valid comment. Clearing annual yields 92 h annual. Generated accrual retains its ID and effect. A failed save preserves the prior ledger and leaves the draft editable. |
| `T-CAL-DAY-02` | From the Calendar fixture, add an individual 1 h planned annual entry on Jan 22 and a separate 2 h denied entry on the same date. Check Jan 21 and Jan 22 and inspect history. | Jan 21 remains 90 h annual. Jan 22 projects 85 h. All three Jan 22 rows are identifiable by status and ID. The denied row does not affect the balance. Cancelled and legacy voided rows are also ineffective. |
| `T-CAL-HISTORY-01` | Add genuine rows on Jan 9 and Jan 10, 2027 in the adjacent Calendar ledgers. Open history for exactly those dates. Inspect row details and sorting, then choose an empty range and an inverted range. | Both boundary dates appear once with their transactions in initial date/ID order. Details retain source, status, comment and ID. System activity is labeled. Empty results are explicit and an invalid range is rejected. History writes nothing. |
| `T-CAL-TX-01` | In the Editable day fixture correct the 1 h annual row to 2 h by its ID and reason. Try a date outside its leave year. Cancel deletion, then confirm deleting the corrected record. | The selected ID survives correction and annual changes from 89 h to 88 h. The other annual ID remains at 2 h. An out-of-year correction or cancelled deletion preserves the files. Confirmed deletion removes only the chosen row and gives 90 h annual. Generated carryover rows lead to their source. |
| `T-CAL-FORCE-01` | Start with 20 h annual and zero annual accrual or use. Adjust Feb 1 to 5 h with a reason, then repeat for 8 h and 20 h. Try a PPL target. | The first adjustment records a 15 h decrease. The second leaves one 12 h decrease and 8 h as of Feb 1. The third yields 20 h with no forced row. PPL requires its own dated workflow. |
| `T-YEAR-ACC-01` | In the Accrual fixture set annual accrual to 6 h effective Jul 12, 2026. Verify Jul 11, Jul 25, and Jan 9, 2027. Apply the same rate change again and query a copy with missing automatic rows. | Jul 11 earns 4 h while Jul 25 and Jan 9 earn 6 h. The change updates 13 annual accrual rows. The year closes at annual 140 h and sick 124 h. Repeat leaves one effective change for that category and date. Dated reads synthesize missing accruals without writing JSON. |
| `T-YEAR-CAP-01` | With the Carryover fixture and Today Jan 16, add an Oct 1 planned 8 h annual use. Check Today and open the year-end forecast. Compare with desktop `use-or-lose --year 2026`. | Today shows 280 h annual. Forecast through Jan 9, 2027 shows 272 h annual, 240 h cap and projected carryover, and 32 h potentially lost. Both date labels remain visible in their respective views. The forecast writes nothing. |
| `T-EXP-01` | Use an 8 h expiring comp lot with July 1 last eligible date. Query July 1 and 2 under a forfeiture rule, then under a warning rule. In a separate fixture allocate 6 h use among same-dated lots of 4 and 5 h with the same deadline and IDs in that order. Use a nonexpiring award in another copy and trigger an urgent reminder twice on the same day. | On July 1 the lot has 8 h and can be used. Forfeiture removes the 8 h on July 2. Warning-only still reports the left-over quantity without a forfeiture entry, and none of the expired hours are available. Allocation consumes 4 h then 2 h, leaving 3 h. Nonexpiring awards yield no upcoming deadline. Repeated reads preserve the ledger. The urgent reminder appears once on the same local date. |
| `T-EXP-02` | Review an extension from May 1 to June 1, 2027 on an extension-enabled travel-comp lot with a reason. Try an earlier date and an extension of a PPL window. | The extension retains the original date, approved new deadline and reason. An earlier deadline, missing reason or PPL extension is rejected. A compatible carryover preserves the approved extension. |
| `T-PARENT-01` | On a 40-hour tour with the 2026 and 2027 linked schedules, record two 480 h grants dated Jun 1 and Sep 1, 2026. Use 8 h PPL on Oct 1. Read the successor and test editing use on the same date as a grant using a separate fixture. | Each active window has 472 h, with 472 h available instead of their sum. Both windows retain their original identities and deadlines. For the June grant May 31, 2027 is last eligible and Jun 1 is first ineligible. A same-day use edit retains the grant. Duplicate dated grants are rejected. |
| `T-PARENT-02` | On a 40-hour tour add 8 h PPL use and 4 h additional manual FMLA on Jul 1, 2026. Decline, then confirm the overlap in separate attempts. Compare confirmed and provisional first-use dates and repeat with incomplete historical coverage. | Decline saves nothing. Confirm records 12 h total FMLA use, of which 8 h is derived, and 8 h physical paid absence. Manual FMLA adds no absence. The period is anchored by first use, with provisional activity distinguished. Unknown coverage or tour yields unavailable capacity and a clear explanation. |

For reference arithmetic and failure cases, use the desktop tests linked from each workflow in the [ledger requirements](sections/ledger-and-leave-years.md). To verify the three primary CLI examples manually, look up the edited day after each `set-day --authoritative`, compare the opening and adjustment fields from `init --from-year 2026 --year 2027 --preview --json` with the saved result, and look up the year close after `accrual-change --year 2026 --category annual --as-of 2026-07-12 --hours 6`. Point each command at its fixture with `--data-dir`.
