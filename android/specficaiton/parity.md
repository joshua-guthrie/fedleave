# FedLeave Android feature parity

This matrix compares Android with the [pinned desktop build](specification.md#product-and-reference-build). Screen IDs identify flows to annotate in the phone screen milestones.

## Calendar balances and navigation

| Function ID | Desktop entry point and observed behavior | Android disposition | Screen or flow ID | Acceptance test ID | Open decision |
| --- | --- | --- | --- | --- | --- |
| `CAL-BAL-01` | Calendar opens with **Leave Balances as of Today**. Month data includes the balance through today's date. | Single panel starts with today. | `BALANCES-TODAY` | [T-CAL-BAL-01](testPlan.md#calendar-acceptance-cases) | Final date typography in the screen milestone. |
| `CAL-BAL-02` | The balance heading opens a date dialog. Accepting an ordinary date retrieves balances through that date. Cancel preserves the active selection. | **Change date** opens the picker and populates the same panel. | `BALANCE-DATE-PICKER`, `BALANCES-DATED` | [T-CAL-BAL-02](testPlan.md#calendar-acceptance-cases) | Picker layout and shortcuts. |
| `CAL-BAL-03` | The month calendar distinguishes pay-period ends from paydays. The separate Pay Periods tables show the date range, pay date, activity, and period-ending balances. | Mark the end dates in the picker and calendar. Show the closing balance in the same panel, with period activity available beneath it. | `BALANCE-DATE-PICKER`, `BALANCES-PERIOD` | [T-CAL-BAL-03](testPlan.md#calendar-acceptance-cases) | Review the placement of earned and used details in the screen milestone. |
| `CAL-BAL-04` | The balance command accepts a future date. Its dated result includes applicable accrual and effective scheduled entries through that date. The desktop also has a separate year-end forecast. | Future selections use the dated result and show **Projected balance**. A confirmed date outside the known schedule follows `CAL-YEAR-01`. | `BALANCES-PROJECTED` | [T-CAL-BAL-04](testPlan.md#calendar-acceptance-cases) | — |
| `CAL-BAL-05` | Calendar's **Today** button returns both the month and the balance date to today. | **Today** restores today's dated panel and current month. | `BALANCES-TODAY` | [T-CAL-BAL-05](testPlan.md#calendar-acceptance-cases) | — |
| `CAL-BAL-06` | Desktop balance data carries warnings and can contain unavailable values. A failed date lookup can fall back to today's month snapshot. | Keep date and values paired. Show an explicit unavailable state when the requested result cannot be loaded. | `BALANCES-UNAVAILABLE` | [T-CAL-BAL-06](testPlan.md#calendar-acceptance-cases) | Warning placement and copy. |
| `CAL-BAL-07` | The desktop balance command can resolve a leave year from a date by checking the stored start and end dates. | Resolve the selected date against leave-year boundaries, including January days belonging to the preceding leave year. | `BALANCE-DATE-PICKER`, `BALANCES-DATED` | [T-CAL-BAL-07](testPlan.md#calendar-acceptance-cases) | — |
| `CAL-NAV-01` | **Previous**, **Next**, and month selection browse the calendar. Only the date selector and **Today** change the selected balance date. | Calendar navigation preserves the selected balance date. | `CALENDAR-MONTH`, `BALANCES-DATED` | [T-CAL-NAV-01](testPlan.md#calendar-acceptance-cases) | Review the phone month selector with the mockups. |

### Desktop evidence for these rows

- Calendar initialization, date selection, and Today reset. [Calendar window](../../src/fedleave_gui/main_window.py#L1352) · [Date selection](../../src/fedleave_gui/main_window.py#L1602) · [Today reset](../../src/fedleave_gui/main_window.py#L1853)
- Period totals and closing balances, accrual cutoffs, and separate pay date markers. [Desktop balance and month commands](../../src/fedleave/commands/balances.py) · [Month command tests](../../tests/test_month_command.py)
- Historical tickets describe the default and future dated balance rules and the desktop period layout. The pinned source defines the shipped result. [Balance dates and accruals #32](https://github.com/joshua-guthrie/fedleave/issues/32) · [Desktop pay-period tables #45](https://github.com/joshua-guthrie/fedleave/issues/45)

## Ledger and leave-year workflows

The [ledger requirements](sections/ledger-and-leave-years.md) describe the desktop evidence for each row and the draft Android review and save behavior.

| Function ID | Desktop entry point and observed behavior | Android disposition | Screen or flow ID | Acceptance test ID | Open decision |
| --- | --- | --- | --- | --- | --- |
| `CAL-YEAR-01` | Calendar offers first-use and manual year setup. Date resolution uses inclusive ledger bounds. | Prompt from the current task for missing current or intentional future dates. Resume the task after confirmation. | `LEAVE-YEAR-SETUP`, `LEAVE-YEAR-REVIEW` | [T-CAL-YEAR-01](testPlan.md#ledger-and-leave-year-acceptance) | Empty-store schedule suggestion. |
| `YEAR-MAN-01` | Manual creation makes an independent baseline with no linked source. | Phone setup with schedule review, opening values, and confirmation. | `LEAVE-YEAR-MANUAL`, `LEAVE-YEAR-REVIEW` | [T-YEAR-MAN-01](testPlan.md#ledger-and-leave-year-acceptance) | — |
| `YEAR-CARRY-01` | Carryover previews from an adjacent year, enforcing limits, lot provenance, and a reviewed fingerprint in Calendar. | Suggest eligible carryover and show amounts, reductions, and inherited lots before confirmation. | `LEAVE-YEAR-CARRYOVER`, `LEAVE-YEAR-REVIEW` | [T-YEAR-CARRY-01](testPlan.md#ledger-and-leave-year-acceptance) | — |
| `YEAR-REC-01` | **Reconcile Carryover** previews dependent years and explicitly applies generated opening and lot changes. Desktop CLI supports recovery and legacy opening repair. | Maintenance review and recovery with conflict and stale-data states. Inventory the legacy repair entry point in milestone 3. | `CARRYOVER-REVIEW`, `CARRYOVER-RECOVERY` | [T-YEAR-REC-01](testPlan.md#ledger-and-leave-year-acceptance) | Placement of recovery and repair actions. |
| `YEAR-OPEN-01` | The desktop CLI replaces an independent starting balance and blocks edits to linked openings. | Opening-balance correction in maintenance. | `STARTING-BALANCE-EDIT` | [T-YEAR-OPEN-01](testPlan.md#ledger-and-leave-year-acceptance) | — |
| `CAL-DAY-01` | **Edit Day** reviews and replaces values by category, accepting hours and comments. | Edit changed totals and review entries affected by the save. | `DAY-EDIT`, `DAY-SAVE-REVIEW` | [T-CAL-DAY-01](testPlan.md#ledger-and-leave-year-acceptance) | Layout for details of multiple existing entries. |
| `CAL-DAY-02` | The desktop CLI can record individual transactions with direction and status. | Add or schedule a separate entry from a date. | `ENTRY-ADD` | [T-CAL-DAY-02](testPlan.md#ledger-and-leave-year-acceptance) | — |
| `CAL-HISTORY-01` | Calendar's **View Leave Transactions** filters a sortable listing by inclusive date range across years. | Phone-sized list with date-range controls and transaction details. | `TRANSACTIONS`, `TRANSACTION-DETAIL` | [T-CAL-HISTORY-01](testPlan.md#ledger-and-leave-year-acceptance) | Sorting control placement. |
| `CAL-TX-01` | The desktop CLI corrects one transaction in place or deletes it using the command named `void`. | Review and confirm correction or deletion of the selected record. | `TRANSACTION-DETAIL`, `TRANSACTION-CORRECT`, `TRANSACTION-DELETE` | [T-CAL-TX-01](testPlan.md#ledger-and-leave-year-acceptance) | — |
| `CAL-FORCE-01` | **Force Leave Balance** writes a dated adjustment with an explanation. | Maintenance action that previews and applies the required difference. | `BALANCE-ADJUST` | [T-CAL-FORCE-01](testPlan.md#ledger-and-leave-year-acceptance) | — |
| `YEAR-ACC-01` | **Change Accrual** changes annual rates by effective date. The core supports sick rates too. | Annual accrual editing and canonical application of both categories' rates. | `ACCRUAL-CHANGE` | [T-YEAR-ACC-01](testPlan.md#ledger-and-leave-year-acceptance) | Sick editing in the same screen. |
| `YEAR-CAP-01` | The desktop Calendar and CLI show projected annual excess above the carryover cap. | Dated year-end forecast with annual cap and excess. | `YEAR-END-FORECAST` | [T-YEAR-CAP-01](testPlan.md#ledger-and-leave-year-acceptance) | Forecast placement on phone. |
| `EXP-01` | **Expiring Leave Status** shows deadlines and lot usage guidance. Preferences set reminder thresholds. | Expiration list, lot details, and urgent in-app reminder. | `EXPIRATION-LIST`, `LOT-DETAIL`, `EXPIRATION-REMINDER` | [T-EXP-01](testPlan.md#ledger-and-leave-year-acceptance) | — |
| `EXP-02` | The desktop CLI records an extension on an eligible expiring lot. | Review and record an approved deadline extension from lot details. | `LOT-EXTENSION` | [T-EXP-02](testPlan.md#ledger-and-leave-year-acceptance) | — |
| `PARENT-01` | Day edit exposes PPL grant and use. Desktop balances and expirations show the applicable event windows. | Dated grant and use with separate window details. | `DAY-EDIT`, `PPL-WINDOWS` | [T-PARENT-01](testPlan.md#ledger-and-leave-year-acceptance) | Grant-entry layout. |
| `PARENT-02` | Desktop separately reports PPL-derived and manual FMLA. Day edit asks for overlap acknowledgement. | Track FMLA once per use and show capacity or the reason it is unavailable. | `FMLA-OVERLAP-REVIEW`, `FMLA-STATUS` | [T-PARENT-02](testPlan.md#ledger-and-leave-year-acceptance) | History coverage is reviewed under `PREF-RULE-01`. |

## Reports

| Function ID | Desktop entry point and observed behavior | Android disposition | Screen or flow ID | Acceptance test ID | Open decision |
| --- | --- | --- | --- | --- | --- |
| `REP-SUM-01` | Analytics **Summary** and global year, refresh and data-quality notices. | Reports home and year summary with recorded, scheduled and full-year context. | `REPORTS-HOME`, `REPORT-SUMMARY` | [T-REP-SUM-01](testPlan.md#reports-acceptance) | — |
| `REP-SEA-01` | **Seasonality** supports five analyses and category/activity choices for three groupings. | Analysis and leave type controls over a chart and exact table. | `REPORT-SEASONALITY`, `REPORT-FILTERS`, `REPORT-ENTRIES` | [T-REP-SEA-01](testPlan.md#reports-acceptance) | — |
| `REP-HEAT-01` | **Calendar Heatmap** has nonzero data selectors and year and month layouts. | Both layouts with date details, exact values and source entries. | `REPORT-HEATMAP`, `REPORT-ENTRIES` | [T-REP-HEAT-01](testPlan.md#reports-acceptance) | Compact layout for year view. |
| `REP-LIFE-01` | **Overtime, Comp, and Credit** has seven summary, lot, performance and monthly views. | Lifecycle report with an analysis selector, table and source details. | `REPORT-LIFECYCLE`, `REPORT-ENTRIES` | [T-REP-LIFE-01](testPlan.md#reports-acceptance) | — |
| `REP-CUM-01` | **Cumulative Usage** charts selected absence categories across one leave year. | Chart and table for one category or an explicit sum. | `REPORT-CUMULATIVE`, `REPORT-FILTERS`, `REPORT-ENTRIES` | [T-REP-CUM-01](testPlan.md#reports-acceptance) | — |
| `REP-CHART-01` | Calendar offers six category balance charts. | One report workflow for the six series at period-end cutoffs. | `REPORT-BALANCE-CHART`, `REPORT-FILTERS` | [T-REP-CHART-01](testPlan.md#reports-acceptance) | — |
| `REP-YOY-01` | Calendar and chart tools compare seven category values as of a chosen month/day across years. | Comparison chart and dated table with a category and date selector. | `REPORT-YEARLY`, `REPORT-FILTERS` | [T-REP-YOY-01](testPlan.md#reports-acceptance) | — |
| `REP-MONTH-01` | Calendar preview, print, PDF, and the month companion PNG. | An on-phone month preview, Share as PDF or PNG, and platform print. | `REPORT-MONTH`, `SHARE-REPORT`, `PRINT-REPORT` | [T-REP-MONTH-01](testPlan.md#reports-acceptance) | Exact print layout in Android. |
| `REP-SHARE-01` | Chart windows save graphics and PDF or print. | Share the active filtered report via the Android Sharesheet, with platform print as a secondary action. | `SHARE-REPORT`, `PRINT-REPORT` | [T-REP-SHARE-01](testPlan.md#reports-acceptance) | — |

## Data, settings, and help

| Function ID | Desktop entry point and observed behavior | Android disposition | Screen or flow ID | Acceptance test ID | Open decision |
| --- | --- | --- | --- | --- | --- |
| `DATA-SHARE-01` | **Export FedLeave Data** produces a schema-v1 JSON archive. | **Share backup** prepares the same compatible archive and opens Sharesheet. | `DATA-HOME`, `SHARE-BACKUP` | [T-DATA-SHARE-01](testPlan.md#data-and-preferences-acceptance) | — |
| `DATA-RESTORE-01` | **Import FedLeave Data** supports merge or replace and the CLI accepts a single leave year. | Open the system picker, validate and preview, confirm, and recover safely on failure. | `RESTORE-PICKER`, `RESTORE-REVIEW`, `RESTORE-RESULT` | [T-DATA-RESTORE-01](testPlan.md#data-and-preferences-acceptance) | Staging and recovery in the storage milestone. |
| `DATA-WMS-01` | **Import From External App** reads FRC-E WMS HTML and replaces matching ledger activity. | Local file selection, read-only review, confirmation and explicit result. | `WMS-PICKER`, `WMS-REVIEW`, `WMS-RESULT` | [T-DATA-WMS-01](testPlan.md#data-and-preferences-acceptance) | Verify fallback for a report with an unrecognized agency schedule. |
| `DATA-PAYROLL-01` | Desktop command updates or adds an entry by date/category/direction and can require an ID. | Draft advanced transaction action, with import covering supported WMS reports. | `PAYROLL-REVIEW` | [T-DATA-PAYROLL-01](testPlan.md#data-and-preferences-acceptance) | Confirm the separate phone entry point with the project owner. |
| `DATA-VALIDATE-01` | **Validate Data** checks the backend data, including parental validation. | On-demand data health with warnings and remedies. | `DATA-CHECK` | [T-DATA-VALIDATE-01](testPlan.md#data-and-preferences-acceptance) | — |
| `DATA-REPAIR-01` | CLI carryover reconciliation includes explicit legacy opening repair. | Offer repair for diagnosed duplicate opening records from data health or carryover review. | `CARRYOVER-REPAIR` | [T-DATA-REPAIR-01](testPlan.md#data-and-preferences-acceptance) | — |
| `PREF-YEAR-01` | Calendar **Change Leave Year** and Analytics year controls select an available year. | Calendar year chooser and independent report year filter. | `LEAVE-YEAR-CHOOSER`, `REPORTS-HOME` | [T-PREF-YEAR-01](testPlan.md#data-and-preferences-acceptance) | — |
| `PREF-CAL-01` | Calendar preferences and View toggles set first weekday, payday offset, marker visibility, font size. | Calendar preferences and Android text scaling. | `PREF-CALENDAR` | [T-PREF-CAL-01](testPlan.md#data-and-preferences-acceptance) | — |
| `PREF-HOL-01` | Holiday tooling reads, generates and imports observed dates and writes a cache. | Review cache, regenerate offline and import an ICS file. | `PREF-HOLIDAYS`, `HOLIDAY-PICKER` | [T-PREF-HOL-01](testPlan.md#data-and-preferences-acceptance) | Decide if a network source belongs in the initial release. |
| `PREF-RULE-01` | Desktop accounting reads the configured tour, increment, defaults, category policies and FMLA coverage. | Advanced accounting settings and a history review, with explicit confirmation for changes that affect balances. | `PREF-ACCOUNTING`, `FMLA-HISTORY-REVIEW` | [T-PREF-RULE-01](testPlan.md#data-and-preferences-acceptance) | Which agency-specific rules need direct editing in the first release. |
| `PREF-REM-01` | Expiration reminders support a configured set of pay-period thresholds. | Edit local thresholds and show useful in-app reminders. | `PREF-REMINDERS` | [T-PREF-REM-01](testPlan.md#data-and-preferences-acceptance) | — |
| `HELP-01` | Calendar and Analytics help, leave abbreviations, project link and About. | Offline in-app help, abbreviation list, version and external project link. | `HELP-HOME`, `HELP-ABOUT` | [T-HELP-01](testPlan.md#data-and-preferences-acceptance) | — |

## Scope exceptions and platform equivalents

| Function ID | Desktop capability | Android disposition | Acceptance test ID |
| --- | --- | --- | --- |
| `SCOPE-PLANNER-01` | Standalone What-if Planner. | Deferred beyond the first release. Ledger planning status and projections remain in scope. | [T-SCOPE-PLANNER-01](testPlan.md#scope-acceptance) |
| `SCOPE-TOOLS-01` | Executable path, arbitrary data directory, CLI flags and raw snapshots, MCP and AI integrations. | Desktop tooling. Android exposes the underlying in-scope app workflows directly and keeps the data store private. | [T-SCOPE-TOOLS-01](testPlan.md#scope-acceptance) |
| `SCOPE-OS-01` | Desktop installer updater, file-save locations, and exit commands. | Platform update, sharing, file-opening, printing, and navigation behavior. | [T-SCOPE-OS-01](testPlan.md#scope-acceptance) |

See the [desktop sources and decisions](sections/reports-data-and-preferences.md) for the rows above.
