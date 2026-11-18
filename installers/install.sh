#!/usr/bin/env bash
set -Eeuo pipefail

# This bootstrap installs a checksum-verified, prebuilt PyInstaller bundle. It
# never clones the repository and never requires Python or build tools.

readonly REPOSITORY="joshua-guthrie/fedleave"
readonly DEFAULT_INSTALL_ROOT="/opt/fedleave"
readonly DEFAULT_BIN_DIR="/usr/local/bin"
readonly TOP_LEVEL_DIRECTORY="FedLeave"

INSTALL_ROOT="$DEFAULT_INSTALL_ROOT"
BIN_DIR="$DEFAULT_BIN_DIR"
RELEASE_VERSION=""
ASSET_BASE_URL=""
ARCHIVE_NAME=""
DOWNLOAD_BASE_URL=""
UNATTENDED=0
TEMP_DIR=""
STAGING_DIR=""
SUDO=()

log() {
  printf '[FedLeave] %s\n' "$*"
}

die() {
  printf '[FedLeave] ERROR: %s\n' "$*" >&2
  exit 1
}

cleanup() {
  if [[ -n "$STAGING_DIR" ]]; then
    run_privileged rm -rf -- "$STAGING_DIR"
  fi
  if [[ -n "$TEMP_DIR" && -d "$TEMP_DIR" ]]; then
    rm -rf -- "$TEMP_DIR"
  fi
}

on_error() {
  local exit_code=$?
  printf '[FedLeave] ERROR: installation failed near line %s (exit %s).\n' "${BASH_LINENO[0]}" "$exit_code" >&2
  exit "$exit_code"
}

trap cleanup EXIT
trap on_error ERR

usage() {
  cat <<'EOF'
Install the latest successful FedLeave master build for 64-bit Debian/Ubuntu.

Official project website:
  https://www.westmouthbay.com/fedleave-application/

Author:
  Joshua Guthrie

Usage:
  install.sh [OPTIONS]

Options:
  --unattended             Run without interactive input.
  --version VERSION        Install a legacy versioned package instead of the rolling build.
  --install-root PATH      Installation root (default: /opt/fedleave).
  --bin-dir PATH           Command-link directory (default: /usr/local/bin).
  --asset-base-url URL     Override the release asset directory (primarily for testing).
  -h, --help               Show this help.

Examples:
  curl -fsSL https://raw.githubusercontent.com/joshua-guthrie/fedleave/master/installer/linux/install.sh | bash
  curl -fsSL https://raw.githubusercontent.com/joshua-guthrie/fedleave/master/installer/linux/install.sh | bash -s -- --unattended
EOF
}

parse_args() {
  while (($#)); do
    case "$1" in
      --unattended)
        UNATTENDED=1
        shift
        ;;
      --version)
        (($# >= 2)) || die "--version requires a value"
        RELEASE_VERSION="${2#v}"
        shift 2
        ;;
      --install-root)
        (($# >= 2)) || die "--install-root requires a path"
        INSTALL_ROOT="$2"
        shift 2
        ;;
      --bin-dir)
        (($# >= 2)) || die "--bin-dir requires a path"
        BIN_DIR="$2"
        shift 2
        ;;
      --asset-base-url)
        (($# >= 2)) || die "--asset-base-url requires a URL"
        ASSET_BASE_URL="${2%/}"
        shift 2
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        die "Unknown argument: $1 (use --help)"
        ;;
    esac
  done
}

detect_platform() {
  [[ "$(uname -s)" == "Linux" ]] || die "Only Linux is supported by this installer."
  case "$(uname -m)" in
    x86_64|amd64) ;;
    *) die "Unsupported CPU architecture: $(uname -m). FedLeave requires x86_64." ;;
  esac

  [[ -r /etc/os-release ]] || die "Cannot identify this Linux distribution."
  # shellcheck disable=SC1091 # /etc/os-release is the standard distribution metadata file.
  . /etc/os-release
  local identity="${ID:-} ${ID_LIKE:-}"
  identity="${identity,,}"
  [[ "$identity" == *debian* || "$identity" == *ubuntu* ]] ||
    die "Unsupported distribution '${PRETTY_NAME:-unknown}'. Use Ubuntu, Debian, or a Debian-based distribution."
  log "Detected ${PRETTY_NAME:-Debian-based Linux} on x86_64."
}

configure_sudo() {
  if ((EUID == 0)); then
    SUDO=()
    return
  fi
  command -v sudo >/dev/null 2>&1 ||
    die "Administrative installation is required, but sudo is unavailable."
  SUDO=(sudo)
  # When this script is piped to bash, stdin is the script stream rather than
  # the terminal. Authenticate through /dev/tty so sudo and sudo-rs can read
  # the password instead of waiting on the pipe and timing out.
  if (exec </dev/tty) 2>/dev/null; then
    "${SUDO[@]}" -v </dev/tty || die "Administrator authentication failed."
  else
    "${SUDO[@]}" -v || die "Administrator authentication failed."
  fi
}

run_privileged() {
  if ((${#SUDO[@]} == 0)); then
    "$@"
  elif (exec </dev/tty) 2>/dev/null; then
    "${SUDO[@]}" "$@" </dev/tty
  else
    "${SUDO[@]}" "$@"
  fi
}

install_runtime_tools() {
  local -a packages=()
  command -v curl >/dev/null 2>&1 || packages+=(curl ca-certificates)
  command -v tar >/dev/null 2>&1 || packages+=(tar)
  command -v sha256sum >/dev/null 2>&1 || packages+=(coreutils)
  # PySide6 carries Qt itself, while libEGL remains a small host runtime
  # dependency on supported Debian/Ubuntu desktops.
  dpkg-query -W -f='${Status}' libegl1 2>/dev/null | grep -q "ok installed" ||
    packages+=(libegl1)
  ((${#packages[@]} == 0)) && return

  command -v apt-get >/dev/null 2>&1 ||
    die "Missing runtime tools (${packages[*]}) and apt-get is unavailable."
  configure_sudo
  log "Installing required runtime tools: ${packages[*]}"
  run_privileged apt-get update
  run_privileged apt-get install -y --no-install-recommends "${packages[@]}"
}

resolve_download() {
  if [[ -n "$RELEASE_VERSION" ]]; then
    ARCHIVE_NAME="FedLeave-${RELEASE_VERSION}-Linux-x86_64.tar.gz"
    DOWNLOAD_BASE_URL="${ASSET_BASE_URL:-https://github.com/${REPOSITORY}/releases/download/v${RELEASE_VERSION}}"
    return
  fi
  ARCHIVE_NAME="FedLeave-Latest-Linux-x86_64.tar.gz"
  DOWNLOAD_BASE_URL="${ASSET_BASE_URL:-https://github.com/${REPOSITORY}/releases/download/beta}"
  log "Using the rolling package from the latest successful master push."
}

download_archive() {
  local output="$1" url="$2"
  # The rolling archive is large enough that a silent download looks frozen.
  # Show curl's progress bar only when the user has an interactive terminal;
  # unattended/CI runs stay quiet and readable in captured logs.
  if [[ -t 2 ]]; then
    curl -fL --retry 3 --progress-bar --show-error --output "$output" "$url"
  else
    curl -fsSL --retry 3 --output "$output" "$url"
  fi
}

download_and_verify() {
  local checksum_name archive_version unpacked_bytes available_bytes reserve_bytes required_bytes
  checksum_name="${ARCHIVE_NAME}.sha256"

  TEMP_DIR="$(mktemp -d)"
  log "Downloading $ARCHIVE_NAME."
  download_archive "$TEMP_DIR/$ARCHIVE_NAME" "$DOWNLOAD_BASE_URL/$ARCHIVE_NAME"
  curl -fsSL --retry 3 --output "$TEMP_DIR/$checksum_name" "$DOWNLOAD_BASE_URL/$checksum_name"

  log "Verifying SHA-256 checksum before installation."
  (
    cd "$TEMP_DIR"
    sha256sum --check --strict "$checksum_name"
  )

  while IFS= read -r member; do
    [[ "$member" != /* && "/$member/" != *"/../"* ]] ||
      die "The release archive contains an unsafe path: $member"
  done < <(tar -tzf "$TEMP_DIR/$ARCHIVE_NAME")

  # The archive and its expanded files coexist briefly in /tmp. Check before
  # extraction so a small tmpfs produces one actionable error instead of
  # thousands of partial "No space left on device" messages from tar.
  unpacked_bytes="$(
    tar -tvzf "$TEMP_DIR/$ARCHIVE_NAME" |
      awk '{ total += $3 } END { printf "%.0f\n", total }'
  )"
  available_bytes="$(
    df -Pk "$TEMP_DIR" |
      awk 'NR == 2 { printf "%.0f\n", $4 * 1024 }'
  )"
  reserve_bytes=$((128 * 1024 * 1024))
  required_bytes=$((unpacked_bytes + reserve_bytes))
  if ((available_bytes < required_bytes)); then
    die "The temporary filesystem needs $((required_bytes / 1024 / 1024)) MiB free to extract this package, but only $((available_bytes / 1024 / 1024)) MiB is available."
  fi
  log "Temporary-space check passed ($((unpacked_bytes / 1024 / 1024)) MiB package expansion)."

  tar -xzf "$TEMP_DIR/$ARCHIVE_NAME" -C "$TEMP_DIR"
  [[ -d "$TEMP_DIR/$TOP_LEVEL_DIRECTORY" ]] ||
    die "The archive is missing its $TOP_LEVEL_DIRECTORY top-level directory."
  [[ -f "$TEMP_DIR/$TOP_LEVEL_DIRECTORY/VERSION" ]] ||
    die "The archive does not identify the source build version."
  archive_version="$(tr -d '\r\n' < "$TEMP_DIR/$TOP_LEVEL_DIRECTORY/VERSION")"
  [[ "$archive_version" =~ ^[A-Za-z0-9][A-Za-z0-9._+-]*$ ]] ||
    die "The archive contains an invalid build version: $archive_version"
  if [[ -n "$RELEASE_VERSION" && "$archive_version" != "$RELEASE_VERSION" ]]; then
    die "Requested version $RELEASE_VERSION does not match archive version $archive_version."
  fi
  RELEASE_VERSION="$archive_version"
}

nearest_existing_parent() {
  local path="$1"
  while [[ ! -e "$path" && "$path" != "/" ]]; do
    path="$(dirname "$path")"
  done
  printf '%s\n' "$path"
}

prepare_privileges() {
  local install_parent bin_parent
  install_parent="$(nearest_existing_parent "$INSTALL_ROOT")"
  bin_parent="$(nearest_existing_parent "$BIN_DIR")"
  if ((EUID != 0)) && { [[ ! -w "$install_parent" ]] || [[ ! -w "$bin_parent" ]]; }; then
    configure_sudo
    log "Administrative privileges are required for $INSTALL_ROOT and $BIN_DIR."
  else
    SUDO=()
  fi
  INSTALL_ROOT="$(readlink -m -- "$INSTALL_ROOT")"
  BIN_DIR="$(readlink -m -- "$BIN_DIR")"
  if is_system_install; then
    verify_system_ancestors "$INSTALL_ROOT"
    verify_system_ancestors "$BIN_DIR"
    if ! command -v setfacl >/dev/null 2>&1; then
      command -v apt-get >/dev/null 2>&1 || die "System installation requires the acl package."
      run_privileged apt-get update
      run_privileged apt-get install -y --no-install-recommends acl
    fi
  fi
}

is_system_install() {
  ((EUID == 0 || ${#SUDO[@]} > 0))
}

verify_system_ancestors() {
  local path="$1" mode
  while :; do
    if [[ -e "$path" || -L "$path" ]]; then
      [[ ! -L "$path" && -d "$path" ]] || die "Unsafe system installation directory: $path"
      mode="$(stat -c %a -- "$path")"
      # POSIX ACL write permissions are bounded by the group-class mode mask.
      if [[ "$(stat -c %u -- "$path")" != 0 ]] || (( (8#$mode & 0022) != 0 )); then
        die "System installation requires root-owned, non-writable ancestors: $path"
      fi
    fi
    [[ "$path" == / ]] && break
    path="$(dirname -- "$path")"
  done
}

verify_bundle_paths() {
  local root="$1" path resolved
  [[ ! -L "$root" ]] || die "Bundle root must not be a symbolic link."
  run_privileged find "$root" -type l -print0 | while IFS= read -r -d '' path; do
    resolved="$(run_privileged readlink -m -- "$path")"
    [[ "$resolved" == "$root" || "$resolved" == "$root/"* ]] ||
      die "Bundle link escapes its release directory: $path"
  done
  path="$(run_privileged find "$root" ! -type d ! -type f ! -type l -print -quit)"
  if [[ -n "$path" ]]; then
    die "Unsupported special file in release: $path"
  fi
}

secure_system_stage() {
  local stage="$1" unsafe
  # Do not inherit downloader ownership, ACLs or privileged executable bits.
  run_privileged chown -hR -P root:root -- "$stage"
  run_privileged setfacl -R -P -b -k -- "$stage"
  run_privileged find "$stage" ! -type l -exec chmod u+rwX,go+rX,go-w,a-s -- '{}' +
  unsafe="$(run_privileged find "$stage" \( ! -uid 0 -o ! -gid 0 -o \( ! -type l -a -perm /6022 \) \) -print -quit)"
  if [[ -n "$unsafe" ]]; then
    die "Unsafe ownership or permissions in staged system release: $unsafe"
  fi
}

find_packaged_command() {
  local root="$1" command="$2"
  find "$root" -type f -name "$command" -perm -u+x -print -quit
}

is_legacy_fedleave_wrapper() {
  local path="$1" command="$2" wrapper_line
  [[ -f "$path" && -r "$path" ]] || return 1
  wrapper_line="$(sed -n '2p' "$path")"
  case "$wrapper_line" in
    "exec $INSTALL_ROOT/current/"*"/$command \"\$@\"") return 0 ;;
    *) return 1 ;;
  esac
}

install_release() {
  local extracted="$TEMP_DIR/$TOP_LEVEL_DIRECTORY"
  local releases_dir="$INSTALL_ROOT/releases"
  local release_dir="$releases_dir/$RELEASE_VERSION"
  local stage_dir
  local current_link="$INSTALL_ROOT/current"
  local pending_link="$INSTALL_ROOT/.current.$$.$RANDOM"
  local cli

  [[ ! -L "$extracted" ]] || die "Bundle root must not be a symbolic link."
  if is_system_install; then
    verify_system_ancestors "$releases_dir"
    verify_system_ancestors "$BIN_DIR"
  fi
  run_privileged install -d -m 0755 "$releases_dir" "$BIN_DIR"

  [[ ! -L "$release_dir" ]] || die "Refusing a symbolic-link release directory: $release_dir"
  if [[ -e "$release_dir" ]]; then
    # Never execute or legitimize bytes an older installation left user-writable.
    release_dir="$releases_dir/${RELEASE_VERSION}.reinstall.$$.$RANDOM"
  fi
  log "Installing the verified bundle into $release_dir."
  # The outer directory keeps copied permissions from exposing incomplete files.
  STAGING_DIR="$(run_privileged mktemp -d "$releases_dir/.${RELEASE_VERSION}.staging.XXXXXXXX")"
  stage_dir="$STAGING_DIR/$TOP_LEVEL_DIRECTORY"
  run_privileged install -d -m 0755 "$stage_dir"
  run_privileged cp -a --no-preserve=ownership,xattr "$extracted/." "$stage_dir/"
  if is_system_install; then
    secure_system_stage "$stage_dir"
  fi
  verify_bundle_paths "$stage_dir"
  run_privileged mv -T "$stage_dir" "$release_dir"
  run_privileged rmdir -- "$STAGING_DIR"
  STAGING_DIR=""

  cli="$(find_packaged_command "$release_dir" fedleave)"
  [[ -n "$cli" ]] || die "The installed release does not contain the required fedleave CLI."
  if ! "$cli" --version >/dev/null 2>&1; then
    "$cli" --help >/dev/null
  fi
  log "Verified the installed CLI before activation."

  local -a optional_commands=(
    fedleave-mcp
    FedLeaveCalendar FedLeaveAnalytics
    AnnualLeaveChartForTheYear SickLeaveChartForTheYear
    CreditHoursChartForTheYear CompTimeChartForTheYear
    TravelCompChartForTheYear TimeOffAwardChartForTheYear
    AnnualLeaveYearlyComparison SickLeaveYearlyComparison
    CreditHoursYearlyComparison CompTimeYearlyComparison
    TravelCompYearlyComparison TimeOffAwardYearlyComparison
    OvertimeYearlyComparison fedleaveMonthReportGraphic
  )
  local command path relative link existing_target

  for command in fedleave "${optional_commands[@]}"; do
    path="$(find_packaged_command "$release_dir" "$command")"
    if [[ -z "$path" ]]; then
      log "Optional packaged application not found: $command"
      continue
    fi
    relative="${path#"$release_dir"/}"
    link="$BIN_DIR/$command"
    if [[ -e "$link" || -L "$link" ]]; then
      if [[ -L "$link" ]]; then
        existing_target="$(readlink "$link")"
        [[ "$existing_target" == "$INSTALL_ROOT/current/"* ]] ||
          die "Refusing to replace command link not owned by FedLeave: $link"
      elif is_legacy_fedleave_wrapper "$link" "$command"; then
        log "Migrating legacy FedLeave command wrapper: $link"
      else
        die "Refusing to replace non-symbolic-link command not owned by FedLeave: $link"
      fi
    fi
    # Command links target "current", not a version, so the final atomic link
    # switch activates every application at the same instant.
    run_privileged ln -sfn "$INSTALL_ROOT/current/$relative" "$link"
  done

  if [[ -e "$current_link" && ! -L "$current_link" ]]; then
    die "Refusing to replace non-symbolic-link path: $current_link"
  fi
  run_privileged ln -s "$release_dir" "$pending_link"
  run_privileged mv -Tf "$pending_link" "$current_link"

  "$BIN_DIR/fedleave" --version >/dev/null 2>&1 || "$BIN_DIR/fedleave" --help >/dev/null
  log "FedLeave ${RELEASE_VERSION} installed successfully."
  log "Launch the calendar with: FedLeaveCalendar"
  log "Use the command line with: fedleave --help"
  log "Previous release directories remain available beneath $releases_dir."
}

main() {
  parse_args "$@"
  detect_platform
  install_runtime_tools
  resolve_download
  ((UNATTENDED == 1)) && log "Running in unattended mode."
  prepare_privileges
  download_and_verify
  install_release
}

main "$@"
