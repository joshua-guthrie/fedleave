# Paid Parental Leave and FMLA tracking

FedLeave records employee-entered and agency-confirmed information. A displayed
amount does not establish eligibility, approval, qualifying service, or an
intermittent-use agreement. Check those with the agency. The application does
not track a return-to-work service obligation or separation dates.

## Entering and editing leave

Use the existing `add`, `set-day`, `correct`, `reconcile` and `void` commands.
The PPL **earned transaction date is the qualifying event date** for calculations.
Entering a later date would incorrectly extend the computed deadline. There is
no separate credit/event date or birth/adoption/foster category.

```bash
fedleave add --date 2026-09-01 --category ppl --earned 480 --description "Agency-confirmed entitlement"
fedleave add --date 2026-10-01 --category ppl --used 8
fedleave reconcile --date 2026-10-01 --category ppl --direction used --hours 8 --reason "Actual leave taken"
fedleave add --date 2026-10-15 --category fmla --used 8
```

Supply `--data-dir` on every command when using an alternate store. `--year` may
select an initialized file for `add`; otherwise actual inclusive leave-year
bounds select the file. `--earned` always requires explicit hours. There are no
automatic PPL grants or FMLA credits.

In Calendar, choose the date, add **Paid Parental Leave (PPL)**, switch to
**Earn**, review the editable 480-hour standard full-time example, and save.
Enter subsequent PPL **Use** normally. **Family and Medical Leave Act (FMLA)**
offers **Use only**. The day editor explains the date/window relationship and
automatic FMLA consumption. The selected backend executable and resolved data
directory own every authoritative operation.

`set-day --ppl 480` replaces that day's earned PPL entry; `--ppl -8` replaces
usage. `--ppl 0` clears usage and preserves the earned entry. To remove/correct a
grant, use its original ID with `void`/`correct`. A same-day grant and use remain
separate records. `--fmla -8` is usage; positive FMLA is refused.

PPL use already consumes FMLA. Manual FMLA means **additional non-PPL** use, not
a mirror. New same-day combinations require `--acknowledge-fmla-overlap` on
`add`, `set-day`, `correct` or `reconcile`. Calendar asks for this clarification
before passing the flag. An acknowledgement marker remains on the affected
transaction. Historical overlaps are retained and warned about rather than
silently removed. Record underlying annual/sick/LWOP time separately when it
represents the physical absence.

## Windows, periods and schedules

PPL starts on the earned date, ends the day before its twelve-calendar-month
anniversary, and cannot be extended, paid out or disabled in configuration.
Calendar anniversary arithmetic clamps February 29 to February 28 in the next
nonleap year: February 27 is the last eligible day in that case. No fixed
365-day approximation is used. Original history remains visible after expiry.

Each distinct event has its own limit. Same-date duplicate grants are refused;
correct the existing entry for a simultaneous birth/placement. Use during
overlapping windows debits every applicable event. The minimum remaining active
allowance constrains use, including an exhausted allowance until its deadline.
The report shows separate windows and overlap debits so they cannot be mistaken
for freely additive grants.

FMLA's twelve-month period starts with first actual use, independently of the PPL
earned date. Earlier non-PPL use may constrain later PPL. A new leave year does
not reset FMLA. After a period ends the tracker is zero until the next use starts
another period. Prior periods and source contributions stay auditable.

Both limits represent twelve administrative workweeks. Weekly hours come from
configured workday duration less lunch, multiplied by normal workdays, or the
agency-confirmed `rules.fmla.weekly_hours` override. Four ten-hour days still
mean 40 hours/week and 480 hours; five ten-hour days mean 50 and 600. Holidays
never create automatic use. Only explicitly dated hours are charged.

New explicit writes capture `scheduled_weekly_hours` on grants and uses.
Changing the configured tour converts **remaining workweeks**, preserving
original recorded hours. For example, 480 granted and 120 used on a 40-hour
week leave nine workweeks; changing to 20 hours/week gives 180 remaining hours.
Historical imported events without a captured tour use the configured conversion
as a disclosed assumption; supply verified per-transaction tour metadata through
an archive import when historical tours differ. Never assume that a changed
current tour describes all historical use.

## Coverage and provisional results

FMLA capacity is unknown until the relevant period origin and usage history have
been reviewed. In `config.json`, the following records that review and optionally
overrides the current weekly conversion:

```json
"fmla": {
  "carryover_mode": "usage_tracking",
  "weekly_hours": 40,
  "history_complete_from": "2026-01-01"
}
```

Only set the coverage date after entering the original FMLA period start and all
relevant usage, including prior years; earlier unrecorded use must not affect
the dates being evaluated. Leave the field null when unsure. Reports display
`history_status=incomplete`, `remaining_hours=null`, and `ppl_usable_hours=null`;
the negative balance still describes recorded usage. `known_remaining_hours`
is the arithmetic remainder **assuming the supplied history and tours**, not
verified eligibility. Missing explicitly linked files produce
`MISSING_SOURCE_YEAR` with the required source year and incomplete-history
explanation; no query substitutes full unused entitlement.

Past `planned`, `requested` or `approved` rows do not prove leave was taken.
Future and unresolved events participate in labeled provisional planning
periods. `confirmed_period`, `confirmed_periods` and `confirmed_balance` use only
effective past `worked`, `submitted`, `certified` or `reconciled` usage. Denied,
cancelled and legacy void rows consume neither entitlement. Reconcile actual
usage through the CLI to confirm it.

## Cross-year reads and audit output

Create successors with `init --from-year` or the existing carryover flow. Source
grants/corrections entered after destination creation affect ordinary queries
and new usage immediately. A reconciliation is not required for correctness.
Manual initialization intentionally starts an independent boundary and does not
discover older entitlement files. Missing required ancestry never means zero
prior use. Reads do not migrate, accrue, dispose, back up or rewrite files.

`balance --json`, `month --json`, `expirations --json` and `list --json` include
an additive `parental` report. Its PPL windows expose original grant/year/ID,
recorded and future use, protected scheduled hours, potential unused loss, exact
last eligible/first ineligible dates and expired-unused hours. FMLA exposes
periods, workweek/hour limits, explicit and PPL-derived contributions, status,
source identity, negative tracking balance, capacity and coverage warnings.
Derived FMLA contributions have `derived=true`; they are never separately saved
transactions. Expiration lots also retain carried origin IDs and years.

Generic absence analytics count PPL once and FMLA zero times. FMLA-specific
series remain available as entitlement tracking. No forecast invents awards or
renewals. Invalid legacy usage remains auditable with warnings and unverified
availability; new known-invalid mutations fail before a ledger is replaced.

Policy sources, checked for this implementation:

- [OPM Paid Parental Leave](https://www.opm.gov/policy-data-oversight/pay-leave/leave-administration/fact-sheets/paid-parental-leave/)
- [OPM Family and Medical Leave Act](https://www.opm.gov/policy-data-oversight/pay-leave/leave-administration/fact-sheets/family-and-medical-leave/)
- [5 CFR 630.1707: overlapping events](https://www.ecfr.gov/current/title-5/chapter-I/subchapter-B/part-630/subpart-Q/section-630.1707)
- [5 CFR 630.1203: entitlement and periods](https://www.ecfr.gov/current/title-5/chapter-I/subchapter-B/part-630/subpart-L/section-630.1203)
