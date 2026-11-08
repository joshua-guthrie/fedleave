"""Plain-language action descriptions shared by Planning controls."""

ACTION_HELP = {
    "Add tentative use": "Add a Proposed row to this scenario. Existing bookings stay in place; nothing is booked in the ledger.",
    "Undo selected changes": "For a Scheduled row, reset its operation to Unchanged. For a Proposed row, discard its addition. Original scheduled rows always remain visible.",
    "Reset all changes": "Clear every draft operation and restore the scheduled baseline. Keep the name, cutoff, horizon and reserve settings.",
    "Recalculate": "Recompute this draft from the cached read-only snapshot. Use File > Refresh to read current ledger data.",
    "Cancel": "Stop waiting for the current calculation/load and discard its late result. Keep draft entries and leave records unchanged.",
    "Resolve selected references": "After reviewing refreshed originals, accept their current identities for the selected scenario rows and recalculate.",
    "Export scenario JSON...": "Save an editable scenario definition outside the datastore. This is a plan file, not a ledger update.",
    "Import scenario JSON...": "Load a saved plan against a fresh read-only snapshot. Choose Replace or Merge; invalid or stale references leave the current draft unchanged.",
    "Open Chart": "Open the current chart with its exact supporting table and CSV, PNG, PDF and Print actions.",
    "Save Table as CSV...": "Export the currently selected result table with its filters, source identity and assumptions, outside the leave datastore.",
    "Close": "Close this window without changing leave records.",
}
