; FedLeave Windows installer.
; Compile-time VERSION, NUMERIC_VERSION, SOURCE_DIR, and OUTPUT_DIR definitions
; are supplied by installer/package.py and the distribution workflow.

Unicode true
RequestExecutionLevel admin
SetCompressor /SOLID lzma

!include "MUI2.nsh"
!include "LogicLib.nsh"

!ifndef VERSION
  !error "VERSION is required (for example /DVERSION=0.2.1)"
!endif
!ifndef NUMERIC_VERSION
  !error "NUMERIC_VERSION is required (for example /DNUMERIC_VERSION=0.2.1.0)"
!endif
!ifndef SOURCE_DIR
  !error "SOURCE_DIR is required and must point to the verified PyInstaller bundle"
!endif
!ifndef OUTPUT_DIR
  !error "OUTPUT_DIR is required"
!endif

; These checks complement package.py's pyproject-driven full validation and
; make a direct NSIS invocation fail clearly for the core applications.
!if ! /FileExists "${SOURCE_DIR}\fedleave.exe"
  !error "Required fedleave CLI is missing from SOURCE_DIR"
!endif
!if ! /FileExists "${SOURCE_DIR}\FedLeaveCalendar.exe"
  !error "Required FedLeave Calendar executable is missing from SOURCE_DIR"
!endif
!if ! /FileExists "${SOURCE_DIR}\FedLeaveAnalytics.exe"
  !error "Required FedLeave Analytics executable is missing from SOURCE_DIR"
!endif

!define PRODUCT_NAME "FedLeave"
!define PRODUCT_PUBLISHER "Joshua Guthrie"
!define PRODUCT_URL "https://www.westmouthbay.com/fedleave-application/"
!define PRODUCT_REG_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\FedLeave"
!define MUI_ABORTWARNING
!define MUI_ICON "..\..\assets\fedleave-icon.ico"
!define MUI_UNICON "..\..\assets\fedleave-icon.ico"

Name "${PRODUCT_NAME} ${VERSION}"
OutFile "${OUTPUT_DIR}\FedLeave-Setup-${VERSION}-Windows-x64.exe"
InstallDir "$PROGRAMFILES64\FedLeave"
InstallDirRegKey HKLM "${PRODUCT_REG_KEY}" "InstallLocation"
BrandingText "FedLeave"

VIProductVersion "${NUMERIC_VERSION}"
VIAddVersionKey /LANG=1033 "ProductName" "${PRODUCT_NAME}"
VIAddVersionKey /LANG=1033 "ProductVersion" "${VERSION}"
VIAddVersionKey /LANG=1033 "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=1033 "CompanyName" "${PRODUCT_PUBLISHER}"
VIAddVersionKey /LANG=1033 "Comments" "${PRODUCT_URL}"
VIAddVersionKey /LANG=1033 "FileDescription" "FedLeave Setup"
VIAddVersionKey /LANG=1033 "LegalCopyright" "MIT License"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH
!insertmacro MUI_LANGUAGE "English"

Section "FedLeave application files" SEC_CORE
  SectionIn RO
  SetShellVarContext all
  SetRegView 64

  ; Writable records/configuration live in the user's normal application-data
  ; directory. Removing the Program Files tree here clears obsolete binaries
  ; during upgrades without touching user data.
  RMDir /r "$INSTDIR"
  SetOutPath "$INSTDIR"
  File /r "${SOURCE_DIR}\*"

  WriteUninstaller "$INSTDIR\Uninstall.exe"

  ; The stable registry key is reused across releases, so Windows Installed
  ; Apps treats upgrades as the same product. QuietUninstallString enables
  ; management tools to perform the same unattended uninstall tested in CI.
  WriteRegStr HKLM "${PRODUCT_REG_KEY}" "DisplayName" "${PRODUCT_NAME}"
  WriteRegStr HKLM "${PRODUCT_REG_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKLM "${PRODUCT_REG_KEY}" "Publisher" "${PRODUCT_PUBLISHER}"
  WriteRegStr HKLM "${PRODUCT_REG_KEY}" "URLInfoAbout" "${PRODUCT_URL}"
  WriteRegStr HKLM "${PRODUCT_REG_KEY}" "HelpLink" "${PRODUCT_URL}"
  WriteRegStr HKLM "${PRODUCT_REG_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "${PRODUCT_REG_KEY}" "DisplayIcon" "$INSTDIR\FedLeaveCalendar.exe"
  WriteRegStr HKLM "${PRODUCT_REG_KEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKLM "${PRODUCT_REG_KEY}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
  WriteRegDWORD HKLM "${PRODUCT_REG_KEY}" "NoModify" 1
  WriteRegDWORD HKLM "${PRODUCT_REG_KEY}" "NoRepair" 1

  RMDir /r "$SMPROGRAMS\FedLeave"
  CreateDirectory "$SMPROGRAMS\FedLeave"
  CreateShortcut "$SMPROGRAMS\FedLeave\FedLeave Calendar.lnk" \
    "$INSTDIR\FedLeaveCalendar.exe" "" \
    "$INSTDIR\FedLeaveCalendar.exe"
  CreateShortcut "$SMPROGRAMS\FedLeave\FedLeave Analytics.lnk" \
    "$INSTDIR\FedLeaveAnalytics.exe" "" \
    "$INSTDIR\FedLeaveAnalytics.exe"
  CreateShortcut "$SMPROGRAMS\FedLeave\Uninstall FedLeave.lnk" "$INSTDIR\Uninstall.exe"
SectionEnd

Section /o "Desktop shortcut" SEC_DESKTOP
  SetShellVarContext all
  ; Optional in the wizard and omitted by default during /S installation.
  CreateShortcut "$DESKTOP\FedLeave Calendar.lnk" \
    "$INSTDIR\FedLeaveCalendar.exe" "" \
    "$INSTDIR\FedLeaveCalendar.exe"
SectionEnd

LangString DESC_SEC_CORE ${LANG_ENGLISH} "Install FedLeave and all packaged companion applications."
LangString DESC_SEC_DESKTOP ${LANG_ENGLISH} "Create a public Desktop shortcut for FedLeave Calendar."
!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_CORE} $(DESC_SEC_CORE)
  !insertmacro MUI_DESCRIPTION_TEXT ${SEC_DESKTOP} $(DESC_SEC_DESKTOP)
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Section "Uninstall"
  SetShellVarContext all
  SetRegView 64
  Delete "$DESKTOP\FedLeave Calendar.lnk"
  RMDir /r "$SMPROGRAMS\FedLeave"
  DeleteRegKey HKLM "${PRODUCT_REG_KEY}"

  ; User data is deliberately outside $INSTDIR and is never referenced here.
  ; /S is handled natively by NSIS, so this same section supports unattended
  ; uninstall without an auxiliary runtime or PowerShell.
  RMDir /r "$INSTDIR"
SectionEnd
