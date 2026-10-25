"""PPL event windows and FMLA first-use periods on canonical private snapshots.

No derived FMLA credit/debit is persisted. PPL use contributes once to FMLA and
once to physical absence; explicit FMLA is entitlement tracking only.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta
from math import isfinite

from .transaction_effects import transaction_is_effective

EPSILON = 1e-6
CATEGORY_LABELS = {"ppl": "Paid Parental Leave (PPL)", "fmla": "Family and Medical Leave Act (FMLA)"}


def anniversary(first: date) -> date:
    """First ineligible day after twelve calendar months (Feb 29 -> Feb 28)."""
    try:
        return first.replace(year=first.year + 1)
    except ValueError:
        return first.replace(year=first.year + 1, day=28)


def weekly_hours(config: dict | None) -> float:
    config = config or {}
    explicit = config.get("rules", {}).get("fmla", {}).get("weekly_hours")
    defaults = config.get("defaults", {})
    if explicit is not None:
        result = float(explicit)
    else:

        def clock(value):
            return datetime.strptime(value, "%H:%M")

        start, end = clock(defaults.get("workday_start", "07:00")), clock(defaults.get("workday_end", "15:30"))
        lunch_start, lunch_end = clock(defaults.get("lunch_start", "11:30")), clock(defaults.get("lunch_end", "12:00"))
        result = ((end - start).total_seconds() - (lunch_end - lunch_start).total_seconds()) / 3600
        result *= len(set(defaults.get("normal_workdays", ["mon", "tue", "wed", "thu", "fri"])))
    if not isfinite(result) or result <= 0:
        raise ValueError("INVALID_PARENTAL_POLICY: weekly scheduled hours must be positive and finite")
    return result


def history(ledger: dict) -> list[dict]:
    """Combine explicit ancestors and genuine local events, never carried credits."""
    supplied = getattr(ledger, "entitlement_history", ledger.get("entitlement_history", []))
    rows = [deepcopy(row) for row in supplied]
    for tx in ledger.get("transactions", []):
        if (
            tx.get("category") not in CATEGORY_LABELS
            or tx.get("carryover_generated")
            or tx.get("source") in {"expiration-rollover", "expiration-engine"}
        ):
            continue
        row = deepcopy(tx)
        row.setdefault("source_leave_year", ledger.get("leave_year"))
        rows.append(row)
    unique = {}
    for row in rows:
        key = (row.get("source_leave_year"), str(row.get("id")))
        if key in unique and unique[key] != row:
            raise ValueError(f"CONFLICTING_PARENTAL_HISTORY: duplicate event {key}")
        unique[key] = row
    return sorted(unique.values(), key=lambda row: (row["date"], str(row.get("source_leave_year")), row["id"]))


def fmla_report(
    ledger: dict,
    config: dict | None,
    as_of: date,
    *,
    today: date | None = None,
    _confirmed_only: bool = False,
    strict: bool = True,
) -> dict:
    today = today or date.today()
    week = weekly_hours(config)
    periods = []
    contributions = []
    warnings = []
    missing_tours = [
        row
        for row in history(ledger)
        if transaction_is_effective(row)
        and row.get("direction") in {"earned", "used"}
        and row["date"] <= as_of.isoformat()
        and "scheduled_weekly_hours" not in row
    ]
    if missing_tours:
        warnings.append(
            {
                "code": "UNVERIFIED_HISTORICAL_TOUR",
                "transaction_ids": [row["id"] for row in missing_tours],
                "message": "Historical tour is unverified; arithmetic assumes the configured weekly hours. Import agency-confirmed scheduled_weekly_hours for these events before relying on capacity.",
            }
        )
    for tx in history(ledger):
        if not transaction_is_effective(tx) or tx.get("direction") != "used" or tx["date"] > as_of.isoformat():
            continue
        hours = float(tx["hours"])
        if hours <= EPSILON:
            continue
        day = date.fromisoformat(tx["date"])
        if not periods or day >= date.fromisoformat(periods[-1]["expiration_effective_date"]):
            periods.append(
                {
                    "start_date": day.isoformat(),
                    "last_eligible_usage_date": (anniversary(day) - timedelta(days=1)).isoformat(),
                    "expiration_effective_date": anniversary(day).isoformat(),
                    "used_hours": 0.0,
                    "used_weeks": 0.0,
                    "explicit_used_hours": 0.0,
                    "ppl_derived_hours": 0.0,
                    "provisional": False,
                }
            )
        period = periods[-1]
        event_week = float(tx.get("scheduled_weekly_hours", week))
        if not isfinite(event_week) or event_week <= 0:
            raise ValueError("INVALID_PARENTAL_POLICY: event weekly hours must be positive")
        period["used_hours"] += hours
        period["used_weeks"] += hours / event_week
        period["ppl_derived_hours" if tx["category"] == "ppl" else "explicit_used_hours"] += hours
        confirmed = day <= today and tx.get("status") in {"worked", "submitted", "certified", "reconciled"}
        if not confirmed:
            period["provisional"] = True
            warnings.append(
                {
                    "code": "PROVISIONAL_FMLA_USAGE",
                    "transaction_id": tx["id"],
                    "message": "Scheduled or unresolved usage is a planning assumption; reconcile actual leave taken.",
                }
            )
        if period["used_weeks"] > 12 + EPSILON:
            message = f"FMLA_LIMIT_EXCEEDED: {tx['id']} exceeds 12 workweeks starting {period['start_date']}"
            if strict:
                raise ValueError(message)
            warnings.append({"code": "FMLA_LIMIT_EXCEEDED", "transaction_id": tx["id"], "message": message})
        contributions.append(
            {
                "transaction_id": tx["id"],
                "source_leave_year": tx.get("source_leave_year"),
                "date": tx["date"],
                "hours": hours,
                "category": tx["category"],
                "physical_absence": tx["category"] == "ppl",
                "period_start": period["start_date"],
                "derived": tx["category"] == "ppl",
                "status": tx.get("status", "planned"),
                "confirmed": confirmed,
            }
        )
    current = periods[-1] if periods and as_of.isoformat() < periods[-1]["expiration_effective_date"] else None
    coverage = (config or {}).get("rules", {}).get("fmla", {}).get("history_complete_from")
    first = min((row["date"] for row in contributions), default=as_of.isoformat())
    complete = bool(coverage and date.fromisoformat(coverage).isoformat() <= first)
    for period in periods:
        period["history_verified"] = complete
        period["limit_verified"] = complete and not missing_tours
        period["provisional"] = period["provisional"] or not complete
    if not complete:
        warnings.append(
            {
                "code": "INCOMPLETE_FMLA_HISTORY",
                "message": "History incomplete: PPL/FMLA availability cannot be verified. Review prior FMLA period origins and usage, then set rules.fmla.history_complete_from to the verified coverage start.",
            }
        )
    for day in sorted({row["date"] for row in contributions}):
        same_day = [row for row in contributions if row["date"] == day]
        if {row["category"] for row in same_day} == {"ppl", "fmla"}:
            warnings.append(
                {
                    "code": "POSSIBLE_DUPLICATE_FMLA",
                    "date": day,
                    "message": "PPL already consumes FMLA automatically. Manual FMLA on this day must represent additional non-PPL use.",
                }
            )
    known_remaining = max(0.0, (12 - current["used_weeks"]) * week) if current else 12 * week
    confirmed = None
    if not _confirmed_only:
        confirmed_rows = [
            row
            for row in history(ledger)
            if row["date"] <= today.isoformat()
            and row.get("status") in {"worked", "submitted", "certified", "reconciled"}
        ]
        confirmed = fmla_report(
            {"transactions": confirmed_rows},
            config,
            min(as_of, today),
            today=today,
            _confirmed_only=True,
            strict=strict,
        )
    return {
        "balance": -current["used_hours"] if current else 0.0,
        "used_hours": current["used_hours"] if current else 0.0,
        "remaining_hours": known_remaining
        if complete and not missing_tours and not any(row["code"] == "FMLA_LIMIT_EXCEEDED" for row in warnings)
        else None,
        "known_remaining_hours": known_remaining,
        "limit_hours": 12 * week,
        "limit_workweeks": 12,
        "weekly_hours": week,
        "history_complete_from": coverage,
        "history_status": "complete" if complete else "incomplete",
        "schedule_status": "unverified" if missing_tours else "recorded",
        "provisional": bool(current and current["provisional"]),
        "confirmed_periods": confirmed["periods"] if confirmed else periods,
        "confirmed_period": confirmed["period"] if confirmed else current,
        "confirmed_balance": confirmed["balance"] if confirmed else (-current["used_hours"] if current else 0.0),
        "scheduled_contributions": [
            {
                "transaction_id": row["id"],
                "source_leave_year": row.get("source_leave_year"),
                "date": row["date"],
                "category": row["category"],
                "hours": float(row["hours"]),
                "status": row.get("status", "planned"),
                "derived": row["category"] == "ppl",
            }
            for row in history(ledger)
            if transaction_is_effective(row)
            and row["direction"] == "used"
            and row["date"] > min(as_of, today).isoformat()
        ],
        "explicit_used_hours": current["explicit_used_hours"] if current else 0.0,
        "ppl_derived_hours": current["ppl_derived_hours"] if current else 0.0,
        "period": current,
        "periods": periods,
        "contributions": contributions,
        "warnings": warnings,
    }


def parental_report(
    ledger: dict,
    config: dict | None = None,
    *,
    as_of: date | None = None,
    strict: bool = False,
    today: date | None = None,
) -> dict:
    from .expirations import synchronize_expirations

    as_of = as_of or date.today()
    work = deepcopy(ledger)
    state = synchronize_expirations(work, config, as_of=as_of)
    conflicts = [warning for warning in state["warnings"] if warning.get("category") == "ppl"]
    conflicts.extend(
        row
        for row in getattr(ledger, "warnings", ledger.get("accounting_warnings", []))
        if row.get("code") == "INVALID_PARENTAL_HISTORY"
    )
    if conflicts and strict:
        raise ValueError("INVALID_PPL_USAGE: " + str(conflicts))
    active = [lot for lot in state["lots"] if lot["category"] == "ppl" and lot["expiration_date"] >= as_of.isoformat()]
    available = min((state["remaining"][str(lot["id"])] for lot in active), default=0.0)
    fmla = fmla_report(ledger, config, as_of, strict=strict, today=today)
    details = ppl_windows(ledger, config, as_of, today=today)
    return {
        "as_of": as_of.isoformat(),
        "ppl_available_hours": available if not conflicts else None,
        "ppl_usable_hours": min(available, fmla["remaining_hours"])
        if fmla["remaining_hours"] is not None and not conflicts
        else None,
        "ppl_windows": details,
        "warnings": [*conflicts, *fmla["warnings"]],
        "fmla": fmla,
    }


def ppl_windows(ledger: dict, config: dict | None, as_of: date, *, today: date | None = None) -> list[dict]:
    """Audit original event windows, including future protected use and loss."""
    from .expirations import synchronize_expirations

    today = today or date.today()
    events = history(ledger)
    # IDs are unique within a year, not necessarily across legacy year files.
    # Namespace only this private audit calculation, retaining public source IDs.
    for event in events:
        event["_source_transaction_id"] = event["id"]
        event["id"] = f"{event.get('source_leave_year')}:{event['id']}"
        event.pop("earned_transaction_id", None)
    past = {"transactions": deepcopy(events)}
    state = synchronize_expirations(past, config, as_of=as_of)
    future = {"transactions": deepcopy(events)}
    horizon = max([as_of, *(date.fromisoformat(row["date"]) for row in events)])
    synchronize_expirations(future, config, as_of=horizon)
    rows = []
    week = weekly_hours(config)
    for lot in state["lots"]:
        if lot["category"] != "ppl":
            continue
        grant_week = float(lot.get("scheduled_weekly_hours", week))
        uses = []
        for use in future["transactions"]:
            allocation = next(
                (row for row in use.get("ppl_allocations", []) if row["transaction_id"] == lot["id"]), None
            )
            if allocation and transaction_is_effective(use) and use["direction"] == "used":
                uses.append(
                    {
                        "transaction_id": use["_source_transaction_id"],
                        "date": use["date"],
                        "hours": float(use["hours"]),
                        "current_schedule_hours": allocation["current_schedule_hours"],
                        "source_leave_year": use.get("source_leave_year"),
                        "status": use.get("status", "planned"),
                        "overlap_debit": len(use["ppl_allocations"]) > 1,
                    }
                )
        charged = sum(row["current_schedule_hours"] for row in uses if row["date"] <= as_of.isoformat())
        scheduled = sum(row["current_schedule_hours"] for row in uses if row["date"] > as_of.isoformat())
        remaining = max(0.0, float(lot["hours"]) * week / grant_week - charged)
        expired = lot["expiration_date"] < as_of.isoformat()
        rows.append(
            {
                "transaction_id": lot["_source_transaction_id"],
                "source_leave_year": lot.get("source_leave_year"),
                "earned_date": lot["date"],
                "earned_hours": float(lot["hours"]),
                "weekly_hours_at_grant": grant_week,
                "remaining_hours": remaining,
                "available_hours": 0.0 if expired else remaining,
                "recorded_used_hours": sum(
                    row["hours"] for row in uses if row["date"] <= min(as_of, today).isoformat()
                ),
                "scheduled_used_hours": scheduled,
                "protected_scheduled_hours": min(remaining, scheduled),
                "potential_unused_loss_hours": max(0.0, remaining - scheduled),
                "expired_unused_hours": remaining if expired else 0.0,
                "last_eligible_usage_date": lot["expiration_date"],
                "expiration_effective_date": anniversary(date.fromisoformat(lot["date"])).isoformat(),
                "uses": uses,
            }
        )
    return rows


def validate_parental_state(ledger: dict, config: dict | None) -> None:
    """Validate a complete proposed mutation on copies before any ledger write."""
    for category in CATEGORY_LABELS:
        if float(ledger.get("starting_balances", {}).get(category, 0.0)):
            raise ValueError("INVALID_PARENTAL_OPENING: PPL needs a dated earned entitlement; FMLA is usage only")
    relevant = [tx for tx in ledger.get("transactions", []) if tx.get("category") in CATEGORY_LABELS]
    if not relevant:
        return
    grants = set()
    for tx in relevant:
        hours = float(tx["hours"])
        if not isfinite(hours) or hours < 0:
            raise ValueError("INVALID_PARENTAL_HOURS: hours must be finite and nonnegative")
        if not tx.get("carryover_generated") and tx.get("source") != "expiration-engine":
            increment = float((config or {}).get("defaults", {}).get("time_increment_hours", 0.25))
            if not isfinite(increment) or increment <= 0:
                raise ValueError("INVALID_PARENTAL_POLICY: time increment must be positive and finite")
            if hours <= 0 or abs(hours / increment - round(hours / increment)) > EPSILON:
                raise ValueError(
                    f"INVALID_PARENTAL_HOURS: record positive hours in increments of {increment}; void unused entries"
                )
            if (
                ledger.get("leave_year_start")
                and not ledger["leave_year_start"] <= tx["date"] <= ledger["leave_year_end"]
            ):
                raise ValueError("INVALID_PARENTAL_DATE: record the transaction in the leave year containing its date")
        event_week = float(tx.get("scheduled_weekly_hours", weekly_hours(config)))
        if not isfinite(event_week) or event_week <= 0:
            raise ValueError("INVALID_PARENTAL_POLICY: event weekly hours must be positive and finite")
        if tx["category"] == "fmla" and tx["direction"] != "used":
            raise ValueError("FMLA_USAGE_ONLY: FMLA cannot be earned or adjusted")
        if tx["category"] == "fmla" and (
            tx.get("carryover_generated")
            or tx.get("source") in {"carryover", "expiration-rollover", "expiration-engine"}
        ):
            raise ValueError("FMLA_USAGE_ONLY: FMLA has no generated rollover or expiration transactions")
        if tx["category"] == "ppl":
            if tx["direction"] not in {"earned", "used"} and not (
                tx["direction"] == "expired" and tx.get("source") == "expiration-engine"
            ):
                raise ValueError("INVALID_PPL_DIRECTION: record a dated earned entitlement or usage")
            if tx.get("source") == "expiration-engine" and tx["direction"] != "expired":
                raise ValueError("INVALID_PPL_SOURCE: expiration-engine is reserved for derived expiry")
            if tx.get("carryover_generated") or tx.get("source") == "expiration-rollover":
                metadata = ledger.get("initialization", {})
                if (
                    metadata.get("mode", metadata.get("method")) != "carryover"
                    or metadata.get("source_leave_year") != ledger.get("leave_year", 0) - 1
                ):
                    raise ValueError(
                        "INVALID_PPL_PROVENANCE: a carried PPL lot requires verified adjacent-year lineage"
                    )
            if not transaction_is_effective(tx):
                continue
            if tx["direction"] == "earned":
                anchor = tx.get("original_earned_date") or tx["date"]
                if anchor in grants:
                    raise ValueError(
                        "DUPLICATE_PPL_EVENT: same-date births/placements form one entitlement; correct the existing grant"
                    )
                grants.add(anchor)
                grant_week = float(tx.get("scheduled_weekly_hours", weekly_hours(config)))
                if not isfinite(grant_week) or grant_week <= 0:
                    raise ValueError("INVALID_PARENTAL_POLICY: grant weekly hours must be positive")
                if not tx.get("carryover_generated") and float(tx["hours"]) > 12 * grant_week + EPSILON:
                    raise ValueError("PPL_LIMIT_EXCEEDED: grant exceeds 12 scheduled workweeks")
    cutoff = max(date.fromisoformat(tx["date"]) for tx in relevant)
    parental_report(ledger, config, as_of=cutoff, strict=True)


def validate_write(path, data: dict) -> None:
    """Storage-boundary validation shared by all explicit CLI mutations/imports."""
    acknowledged = data.pop("_fmla_overlap_acknowledged", False) is True
    if path.parent.name != "leave_years" or not (
        any(tx.get("category") in CATEGORY_LABELS for tx in data.get("transactions", []) if isinstance(tx, dict))
        or any(data.get("starting_balances", {}).get(category) for category in CATEGORY_LABELS)
    ):
        return
    from .cross_year import Snapshot, derive_carryover, replace_generated, resolve_snapshot
    from .storage import load_json

    base = path.parent.parent
    config = load_json(base / "config.json") if (base / "config.json").exists() else {}
    original = load_json(path) if path.exists() else {}
    previous = {row.get("id"): row for row in original.get("transactions", [])}
    # Only new or changed effective uses require acknowledgement. Historical
    # overlap remains intact and is reported as a warning on every query.
    uses = [
        row
        for row in data.get("transactions", [])
        if row.get("category") in CATEGORY_LABELS and row.get("direction") == "used" and transaction_is_effective(row)
    ]
    for row in uses:
        old = previous.get(row["id"], {})
        changed = any(
            row.get(key) != old.get(key) for key in ("date", "category", "direction", "hours", "status", "void")
        )
        if changed and any(other["date"] == row["date"] and other["category"] != row["category"] for other in uses):
            if not acknowledged:
                raise ValueError(
                    "POSSIBLE_DUPLICATE_FMLA: PPL already consumes FMLA. Confirm the manual FMLA is additional non-PPL use with --acknowledge-fmla-overlap."
                )
            row["fmla_overlap_acknowledged"] = True
    # Capture the tour when a new entitlement or usage is recorded. Future
    # schedule changes then convert remaining workweeks, not historical hours.
    for tx in data.get("transactions", []):
        if tx.get("category") in CATEGORY_LABELS:
            if tx["id"] not in previous:
                tx.setdefault("scheduled_weekly_hours", weekly_hours(config))
    proposed = Snapshot(deepcopy(data))
    proposed.config, proposed.warnings = config, []
    source = data.get("initialization", {}).get("source_leave_year")
    if source is not None:
        ancestor = resolve_snapshot(base, source, config)
        derived, _ = derive_carryover(
            ancestor, int(data["leave_year"]), config, pay_periods=data.get("pay_period_count")
        )
        proposed = Snapshot(replace_generated(proposed, derived, config))
        proposed.config, proposed.warnings = config, []
        proposed.entitlement_history = history(ancestor)
    else:
        proposed.entitlement_history = []
    validate_parental_state(proposed, config)
    # Persist fixed grant deadlines through the CLI only. Uses/allocations and
    # cross-year credits stay derived; genuine source records remain untouched.
    for row in data.get("transactions", []):
        if row.get("category") == "ppl" and row.get("direction") == "earned" and not row.get("carryover_generated"):
            if not row.get("expiration_date"):
                row["expiration_date"] = (anniversary(date.fromisoformat(row["date"])) - timedelta(days=1)).isoformat()


def validate_imports(base, items) -> None:
    """Validate proposed linked archive state before creating any store files."""
    from .cross_year import Snapshot, derive_carryover, read_raw, replace_generated
    from .storage import load_json

    ledgers = {int(path.stem): payload for path, payload in items if path.parent.name == "leave_years"}
    if not any(
        tx.get("category") in CATEGORY_LABELS for payload in ledgers.values() for tx in payload.get("transactions", [])
    ) and not any(
        payload.get("starting_balances", {}).get(category)
        for payload in ledgers.values()
        for category in CATEGORY_LABELS
    ):
        return
    config = next((payload for path, payload in items if path == base / "config.json"), None)
    if config is None:
        config = load_json(base / "config.json") if (base / "config.json").exists() else {}
    cache = {}

    def resolve(year):
        if year in cache:
            return cache[year]
        raw = ledgers[year] if year in ledgers else read_raw(base, year)
        current = Snapshot(deepcopy(raw))
        current.config, current.warnings = config, []
        source = raw.get("initialization", {}).get("source_leave_year")
        if source is not None and source != year - 1:
            raise ValueError("SOURCE_NOT_CONTIGUOUS: imported parental lineage is invalid")
        if source is not None:
            ancestor = resolve(source)
            derived, _ = derive_carryover(ancestor, year, config, pay_periods=current.get("pay_period_count"))
            current = Snapshot(replace_generated(current, derived, config))
            current.config, current.warnings = config, []
            current.entitlement_history = history(ancestor)
        else:
            current.entitlement_history = []
        validate_parental_state(current, config)
        cache[year] = current
        return current

    for year in sorted(ledgers):
        resolve(year)
