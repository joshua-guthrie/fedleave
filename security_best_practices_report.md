# FedLeave security audit and remediation report

Date: 2026-11-14. Audited baseline: `9a63d2b3a9c3d9eaf51dc0b725f6fa045cdb1c0e`.
Remediation and commit verification: 2026-11-18.

## Executive assessment

The audit identified **10 findings: two High, five Medium and three Low**. The strongest demonstrated risks were a holiday-download path that bypassed restricted MCP local-file permissions and a Linux system installation that retained ordinary-user ownership of shared programs. Export integrity, spreadsheet interpretation, Windows launcher selection, archive targets and dependency/resource controls also required changes.

The status table tracks source remediation. Native Windows checks and installer acceptance are tracked by the project workflows. Independent verification remains separate from implementation.

Original audit notes and raw evidence are retained in the local audit archive under `artifacts/security/`.

## Scope and method

Reviewed surfaces include the CLI, Calendar and Analytics desktops, chart/report exporters, JSON archive import/export, holiday retrieval, MCP policy and child execution, executable discovery, Linux bootstrap/archive metadata, Windows installer source, dependency resolutions and CI/distribution workflows. Tests use temporary synthetic leave data, inert formulas and disposable local fixtures.

Evidence includes actual CLI/MCP children, real Qt PNG/PDF rendering, LibreOffice formula evaluation, a kernel-isolated Linux guest with root and ordinary identities, and inspection of the exact published Windows/Linux packages. Released checksums were verified. The earlier exact Linux package passed MCP/Analytics smoke tests in both access profiles; Windows package inspection was static.

Findings distinguish demonstrated behavior from inferred impact. A version/advisory match alone is not proof of a reachable exploit. This was not exhaustive fuzzing, a complete native-library/SBOM assessment, production-data testing or a remotely exposed service penetration test. Native Windows ACL/execution and Excel behavior were unavailable locally.

## Finding summary

| ID | Severity and prerequisite | Baseline defect | Remediation | Source status |
| --- | --- | --- | --- | --- |
| SEC-002 | High; restricted MCP peer with network-init permission | Holiday URLs bypassed local-file read roots | Validate the actual download URL and suppress parser-content errors | Fixed |
| SEC-005 | High, conditional; shared privileged Linux deployment | Extracted unprivileged ownership survived installation | Normalize staged ownership/modes/ACLs and activate fresh verified bytes | Pending |
| SEC-003 | Medium; untrusted text opened in a formula-evaluating spreadsheet | CSV delimiter quoting preserved formulas | Encode dangerous text cells at every CSV writer | Pending |
| SEC-001 | Medium, conditional; Windows batch backend selected | Batch launchers introduced shell parsing | Require existing native `.exe` backends on Windows | Pending |
| SEC-008 | Medium; unsafe destination or writable export directory | Writers followed links into canonical files | Datastore guard, private staging and atomic publication | Pending |
| SEC-009 | Medium; affected source dependency and controlled metadata | OpenTelemetry trace parsing delayed MCP | Fixed dependency minimum and resolved advisory gate | Pending |
| SEC-010 | Medium, conditional; Windows drive layout and imported archive | Cache keys changed the destination drive | Reject nonportable names and preflight all targets | Pending |
| SEC-004 | Low; selected or compromised response endpoint | Network reads had no byte budget | Enforce actual response-byte budgets | Pending |
| SEC-006 | Low established application exposure; affected Pillow resolution | No fixed minimum for advisory matches | Pillow 13.0.0 minimum and rendering validation | Pending |
| SEC-007 | Low established application exposure; affected icalendar resolution | No fixed minimum for complexity advisory | icalendar 7.1.3 minimum and import validation | Pending |

## High severity

### SEC-002 — Holiday downloads bypassed restricted MCP local-file permissions

**Impact:** A connector peer with network initialization permission could read a local file outside its authorized read roots through parser diagnostics or imported calendar contents.

Initialization sanitized a stored URL but handed the original argument to the holiday generator. The downloader accepted urllib-supported `file:` URLs, so `file_read_roots=[]` did not block this alternate read path. A plaintext marker appeared through parser errors; a valid local ICS outside the store could be imported. Real Executor/CLI-child reproductions established the bypass. Classification: CWE-918 / permission-boundary bypass.

The fix validates HTTP(S), host, length and NUL constraints at [the actual downloader](src/fedleave/holidays.py#L72), passes the validated configuration value from [initialization](src/fedleave/config.py#L250), and translates malformed-calendar exceptions into a content-free error at [the parser boundary](src/fedleave/holidays.py#L22). Actual `opm_ics` initialization rejects invalid URLs; offline mode retains the existing fallback for an unused optional URL. Authorized local ICS file import remains available separately.

[Permanent tests](tests/test_holiday_download_security.py) cover zero opener calls on rejected URLs, normalized valid HTTP(S), text/JSON error redaction and restricted Executor children importing neither plaintext nor ICS fixtures. The initial focused suite passed 27 tests. No arbitrary-host allowlist was added: this addresses local-file permission bypass rather than claiming general SSRF isolation.

**Commit verification:** 20 passed in 2.51s.

### SEC-005 — System installation preserved ordinary-user ownership

Source remediation pending.

## Medium severity

### SEC-003 — CSV exports retained spreadsheet formulas

Source remediation pending.

### SEC-001 — Windows desktop backends accepted batch launchers

Source remediation pending.

### SEC-008 — Exports could overwrite linked canonical data

Source remediation pending.

### SEC-009 — MCP metadata reached a vulnerable OpenTelemetry parser

Source remediation pending.

### SEC-010 — Imported cache keys could change the Windows destination drive

Source remediation pending.

## Low severity

### SEC-004 — Network documents lacked byte budgets

Source remediation pending.

### SEC-006 — Pillow resolution matched published advisories

Source remediation pending.

### SEC-007 — icalendar resolution matched a complexity advisory

Source remediation pending.
