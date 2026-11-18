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
| SEC-005 | High, conditional; shared privileged Linux deployment | Extracted unprivileged ownership survived installation | Normalize staged ownership/modes/ACLs and activate fresh verified bytes | Fixed |
| SEC-003 | Medium; untrusted text opened in a formula-evaluating spreadsheet | CSV delimiter quoting preserved formulas | Encode dangerous text cells at every CSV writer | Fixed |
| SEC-001 | Medium, conditional; Windows batch backend selected | Batch launchers introduced shell parsing | Require existing native `.exe` backends on Windows | Fixed |
| SEC-008 | Medium; unsafe destination or writable export directory | Writers followed links into canonical files | Datastore guard, private staging and atomic publication | Fixed |
| SEC-009 | Medium; affected source dependency and controlled metadata | OpenTelemetry trace parsing delayed MCP | Fixed dependency minimum and resolved advisory gate | Fixed |
| SEC-010 | Medium, conditional; Windows drive layout and imported archive | Cache keys changed the destination drive | Reject nonportable names and preflight all targets | Fixed |
| SEC-004 | Low; selected or compromised response endpoint | Network reads had no byte budget | Enforce actual response-byte budgets | Fixed |
| SEC-006 | Low established application exposure; affected Pillow resolution | No fixed minimum for advisory matches | Pillow 13.0.0 minimum and rendering validation | Pending |
| SEC-007 | Low established application exposure; affected icalendar resolution | No fixed minimum for complexity advisory | icalendar 7.1.3 minimum and import validation | Pending |

## High severity

### SEC-002 — Holiday downloads bypassed restricted MCP local-file permissions

**Impact:** A connector peer with network initialization permission could read a local file outside its authorized read roots through parser diagnostics or imported calendar contents.

Initialization sanitized a stored URL but handed the original argument to the holiday generator. The downloader accepted urllib-supported `file:` URLs, so `file_read_roots=[]` did not block this alternate read path. A plaintext marker appeared through parser errors; a valid local ICS outside the store could be imported. Real Executor/CLI-child reproductions established the bypass. Classification: CWE-918 / permission-boundary bypass.

The fix validates HTTP(S), host, length and NUL constraints at [the actual downloader](src/fedleave/holidays.py#L74), passes the validated configuration value from [initialization](src/fedleave/config.py#L250), and translates malformed-calendar exceptions into a content-free error at [the parser boundary](src/fedleave/holidays.py#L24). Actual `opm_ics` initialization rejects invalid URLs; offline mode retains the existing fallback for an unused optional URL. Authorized local ICS file import remains available separately.

[Permanent tests](tests/test_holiday_download_security.py) cover zero opener calls on rejected URLs, normalized valid HTTP(S), text/JSON error redaction and restricted Executor children importing neither plaintext nor ICS fixtures. The initial focused suite passed 27 tests. No arbitrary-host allowlist was added: this addresses local-file permission bypass rather than claiming general SSRF isolation.

**Commit verification:** 20 passed in 2.51s.

### SEC-005 — System installation preserved ordinary-user ownership

**Impact:** Shared installed programs could remain writable by the downloading user; another identity, including root, could later execute modified bytes.

The bootstrap extracted as the caller and used privileged `cp -a`, preserving caller ownership under the system installation root. The baseline isolated guest confirmed owner write access and later guest-root execution of an inert modified CLI. This is a conditional local privilege boundary, not remote compromise. Classification: CWE-732 / CWE-276.

[Staging and activation](installer/linux/install.sh#L346) now require trusted root-owned system destination ancestors, reject escaping bundle links/special files, copy verified bytes into a private staging directory without preserving ownership or extended attributes, set root ownership without following links, clear ACLs and strip group/world write and setuid/setgid bits before invoking the CLI. Existing versions receive fresh uniquely named verified releases; an older writable CLI is never run or legitimized. Atomic activation and user-local ownership remain supported. [Archive creation](installer/package.py) also emits root metadata and safe modes.

Tests cover user-local installation, external links, old tampered releases and archive metadata. A [privileged CI test](tests/test_linux_system_install_security.py) uses a disposable `/var/lib` tree with real root/nonroot identities, never the application's install or datastore. Distribution invokes it explicitly with sudo. The earlier fixed isolated guest showed root ownership in both caller modes, denied ordinary-user modification and did not execute the old modified release. That fixture uses GNU tools and a small privilege helper; supported Debian/Ubuntu sudo/PAM and Distribution acceptance remain CI work.

**Commit verification:** 24 passed in 2.30s, one privileged CI test skipped locally. The final isolated Linux guest retest confirmed root ownership and denied ordinary-user writes for both caller modes.

## Medium severity

### SEC-003 — CSV exports retained spreadsheet formulas

Descriptions, scenario names and metadata reached CSV writers unchanged. CSV delimiter quoting did not neutralize formula characters or control/whitespace prefixes. LibreOffice actually evaluated harmless arithmetic from a production comparison CSV. Spreadsheet-dependent network/command effects were neither attempted nor demonstrated. Classification: CWE-1236.

The shared [cell encoder](src/fedleave_analytics/csv_export.py#L7) now prefixes dangerous text with an apostrophe across comparison, planning and ordinary Analytics exports, including headers and metadata. It recognizes ASCII/fullwidth formula characters and leading control/format characters. Numbers, including negative values, stay numeric; JSON/source records retain their original text. Help documents the marker and consumer/resaving limitations.

[Tests](tests/test_csv_export_security.py) cover quoting, multiline text, Unicode, control prefixes, real planner exports, GUI saves and JSON fidelity. The focused suite passed 46 tests. Fixed production exports contained **zero formula cells** in LibreOffice with default and explicitly enabled formula-import settings. Excel and later transformations remain untested; there is no universal CSV-safety claim.

**Commit verification:** 124 passed in 1.68s.

### SEC-001 — Windows desktop backends accepted batch launchers

Discovery/explicit overrides accepted `.bat`/`.cmd`; PATH fallback could reintroduce them. Comments were argv elements, but Windows may introduce a shell for batch execution even with `shell=False`. Selection was demonstrated; native command execution was inferred from [Python's subprocess documentation](https://docs.python.org/3.11/library/subprocess.html#security-considerations), not reproduced locally. Normal shipped native `.exe` use was not identified as affected. Classification: conditional CWE-78.

The shared [validator](src/fedleave/executable_search.py#L27), companion finders and direct Analytics/snapshot/report boundaries now require an existing `.exe` on Windows, case-insensitively, including bare-name/PATH resolution and the resolved target of a link. Linux executable scripts still work. Explicit unsupported selections produce a useful error. Comments remain literal user data.

[Tests](tests/test_windows_backend_security.py) reject batch variants before process creation across public callers. Linux scripts and related callers passed in the 69-test focused suite. A native Windows test uses the installed CLI and hostile-looking literal comments; Windows fake-backend contract tests now build a genuine native test executable. Package smoke coverage also checks literal comment preservation. Native Windows results are tracked by CI.

**Commit verification:** 70 passed, 1 skipped in 35.55s.

### SEC-008 — Exports could overwrite linked canonical data

CSV, Calendar/Analytics PNG/PDF and month PDF writers opened destinations directly. Final writer review also reproduced the same overwrite through the print dialogs' file output in six actual Qt cases. Hard/symbolic links could turn a report save into ledger truncation. CLI month PNG also used a predictable temporary name; a planted link redirected staging writes. Actual Qt/Pillow/CSV paths reproduced these effects on synthetic ledgers. An unsafe selected destination or shared writable export directory was required; no remote write was established. Classification: CWE-59.

All affected writers use [one GUI-independent boundary](src/fedleave/exporting.py#L12), including print-to-file and month print-preview output. Ordinary native printer jobs retain their existing rendering path. It rejects selected-datastore destinations and final symlinks, renders inside a private randomly named staging directory on the destination filesystem, closes handles and atomically replaces the external directory entry. Replacing an external hard link preserves the ledger inode. Failed rendering closes printer handles before cleaning staging and preserves the previous report. Atomic create-only publication preserves concurrent creators.

[Regressions](tests/test_export_security.py) exercise real chart PNG/PDF combinations, month PDF, CSV aliases, legacy staging links, direct datastore targets, failure cleanup, print-to-file and create-only races. The native Windows test also inspects actual staging ACLs; POSIX tests check private directory permissions. Related exporter suites passed; printer tests retain layout assertions while checking staging. This protects the identified link attacks; it is not an OS sandbox against arbitrary concurrent ancestor-directory replacement. Native Windows link semantics remain CI acceptance work.

**Commit verification:** 61 passed in 8.91s.

### SEC-009 — MCP metadata reached a vulnerable OpenTelemetry parser

MCP 2.3.0 installs tracing middleware without needing an exporter. Source OpenTelemetry API 1.45.1 parsed `_meta.traceparent` before CLI execution. A bounded 8-KiB malformed whitespace input delayed a real read-only MCP ping to about 598 ms versus about 3 ms normally. CLI deadlines/read-only policy did not bound the in-process parse. No indefinite hang or external service attack was attempted. Classification: CWE-1333; [GHSA-mf5v-w3w3-f6cg](https://github.com/open-telemetry/opentelemetry-python/security/advisories/GHSA-mf5v-w3w3-f6cg).

[Dependencies](pyproject.toml) now require `opentelemetry-api>=1.45.2,<2`, compatible with pinned MCP. Local resolution is 1.45.2. The original actual-wire probe now completes its bounded cases in approximately 1–3 ms, including the largest case. Permanent [stdio metadata coverage](tests/test_mcp_protocol.py) exercises absent, valid, oversized and malformed context through uncached catalog requests, asserts denied writes and leaves the datastore absent. Version tests enforce the fixed parser without brittle timing thresholds.

Both inspected earlier installers already contained 1.45.2. This finding applies to permitted source resolutions, not those packages.

**Commit verification:** 17 passed in 52.70s.

### SEC-010 — Imported cache keys could change the Windows destination drive

Archive validation rejected separators but allowed colons. A key such as `C:outside` joined to a datastore on a different drive can replace the intended drive/root under Windows pathlib semantics. The real import path passed an escaped target to its write sink in a path-semantics probe. Native Windows file creation was not demonstrated. Filesystem permissions/overwrite rules still apply; no restricted-MCP write-root bypass is claimed. Classification: CWE-22.

[Validation](src/fedleave/commands/data.py#L386) now rejects colon, slash and backslash consistently on both platforms and preflights every canonical target before creating any configuration, directories or data. Safe Unicode names and merge/overwrite behavior remain supported.

[Tests](tests/test_import_path_security.py) cover rejection before all writes, safe names and escaping cache-directory links. A native Windows test maps only a disposable directory to a second drive and cleans that mapping afterward. The focused import/export/storage suite passed 20 tests before the native addition; Windows execution awaits CI.

**Commit verification:** 20 passed, 1 skipped in 0.84s.

## Low severity

### SEC-004 — Network documents lacked byte budgets

Holiday/update readers used unbounded `read()`. Timeouts did not prevent a selected/compromised endpoint from supplying a large body. Moderate synthetic fixtures established the missing budget; no OOM was induced. Classification: CWE-400/CWE-770.

The [bounded reader](src/fedleave/network.py) enforces **5 MiB for holiday ICS** and **64 KiB for update metadata**, independently of Content-Length and with at most one overflow byte. Oversized initialization fails before committed configuration/calendar data; update checks return unavailable. Responses close and diagnostics omit body content. [Tests](tests/test_network_response_limits.py) cover below/exact/over boundaries and high-level behavior; the focused suite passed 29 tests. These are not total elapsed-time or arbitrary parser-complexity limits.

**Commit verification:** 35 passed in 2.48s.

### SEC-006 — Pillow resolution matched published advisories

Source remediation pending.

### SEC-007 — icalendar resolution matched a complexity advisory

Source remediation pending.
