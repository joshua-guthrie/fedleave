# Developer setup and testing

Start with **Android Studio** on Linux. It contains the editor, debugger and build integration. The **Android SDK** supplies the platform and device tools. **Gradle** builds the project using the version pinned by its wrapper. **Kotlin** is the UI programming language and **Jetpack Compose** builds the screens. [Android Studio installation](https://developer.android.com/studio/install) · [Kotlin and Compose course](https://developer.android.com/courses/android-basics-compose/course) · [Shared core](core-and-compatibility.md)

## Set up the computer and first run

1. If Android Studio is already installed, open it and verify that it starts. Otherwise choose the current stable release for Linux, follow Google's Linux installation steps, and complete the Setup Wizard. Use the bundled Java runtime for Studio and start with the template-selected Gradle JDK. Record the pinned combination when creating the actual project. [Studio installation](https://developer.android.com/studio/install#linux) · [Java versions and Gradle](https://developer.android.com/build/jdks)
2. Open **SDK Manager** in Studio. Install the platform requested by the project, Android SDK Platform-Tools and its required build tools. Install Android Emulator and an emulator system image if using a virtual phone. Platform-Tools includes `adb`, the tool Studio uses to talk to a phone. Use the project wrapper to build. [SDK Manager](https://developer.android.com/studio/intro/update#sdk-manager)
3. To learn the workflow, create a temporary Kotlin Compose template project. Sync Gradle, pick an available device next to **Run**, and launch the sample. The FedLeave source project will be created under `android/` in the implementation milestone. Open that Gradle project once it exists. These steps can be practiced independently of a Play Console account.
4. An **Android Virtual Device**, or AVD, is an emulator profile. In **Device Manager**, create a compact phone profile and select a supported image matching the development host's architecture. Start it and launch the practice app. On Linux check hardware virtualization and emulator acceleration if performance or setup is poor. A connected phone is sufficient to get started if the computer cannot run an emulator. [AVD setup](https://developer.android.com/studio/run/managing-avds) · [Emulator acceleration](https://developer.android.com/studio/run/emulator-acceleration)
5. For a physical phone, enable Developer options and USB debugging, connect with a data-capable USB cable, and accept the debugging prompt on the phone. Select it under **Run**. If it does not appear, use Studio's device connection assistant and `adb devices` from SDK Platform-Tools. Disable debugging when the session is finished if it is not needed. [Physical device setup](https://developer.android.com/studio/run/device)

Studio manages the Kotlin build and the emulator directly. For desktop parity tests and fixture creation, use the existing Python `.venv` or create a host virtual environment. If the Chaquopy experiment succeeds, Gradle also needs a compatible host Python for packaging. Pin it and keep it reproducible as part of the proof of concept. The installed Android app brings the supported runtime with it. [Bridge build setup](https://chaquo.com/chaquopy/doc/current/android.html#buildpython)

## Test devices and API levels

API levels are Android's numerical platform versions. Use a provisional **minimum API 26 (Android 8.0)** for the phone app, which supplies the `java.time` date APIs and exceeds the bridge's current minimum. Accept or adjust this floor when the toolchain experiment runs and publish the result in the app's requirements. **Target API** declares the behavior level used by Google Play. **Compile API** supplies symbols at build time. Install a compile SDK and target level meeting the current Play requirement, and test behavior on those levels. [Android API levels](https://developer.android.com/guide/topics/manifest/uses-sdk-element) · [Android LocalDate](https://developer.android.com/reference/java/time/LocalDate) · [Play target API requirements](https://support.google.com/googleplay/android-developer/answer/11926878?hl=en)

| Target | What to verify |
| --- | --- |
| Oldest supported emulator image | Install, open, local storage, base Material layouts, and the bridge on that Android version. |
| Recent compact emulator image | Small phone, keyboard, Back, dark theme, largest practical font and display scaling, date picker and file handoffs. |
| Recent larger emulator image | Larger layout, rotation, split-window behavior, report chart and exact-value table readability. |
| ARM64 physical handset | Offline use, signed candidate install or update, sharing with actual apps, receiving a backup, in-app reminders, startup and local lookup time. |
| Native page-size test | On a compatible emulator or device with 16 KB pages, confirm all embedded native libraries load and the signed app completes the core parity smoke tests. |
| Installed desktop Linux and Windows GUIs | Execute all four interchange directions and inspect the calendar after import. Windows access is a release dependency to arrange with a runner, VM or tester. |

## How to run checks

Create or use synthetic fixtures only. Keep the pinned clock and fixture hash with failures. The commands below are examples for the eventual Gradle project. Confirm the actual tasks during the project setup and write them into an implementation runbook. [Android test command line](https://developer.android.com/studio/test/command-line)

```bash
# Existing desktop regression suite from the repository root on Linux
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q

# Once the Android Gradle wrapper exists, run from its project root
./gradlew testDebugUnitTest
./gradlew connectedDebugAndroidTest
```

| Layer | Where and what to test |
| --- | --- |
| Fast accounting parity | Desktop Python tests and Kotlin bridge contract tests with fixed dates. Compare the expected records and balances for accrual, periods, edits, carryover, expirations and parental rules. |
| Android storage and integration | On an emulator or handset, test file selection, private staging, restart, JSON IDs and field preservation, recovery at each failure point, input compatibility and late callbacks. A synthetic receiver verifies Share contents. |
| Compose UI and accessibility | Run tests from the Studio gutter or the connected test task. Exercise top tasks, selected dates, TalkBack order, accessible labels, 48 dp targets, large text, dark mode, cancellation and no-data states. Test system surfaces with device-level tests or a guided manual case. |
| Manual release rehearsal | Install and upgrade the same candidate on a handset. Set up a new leave year, edit and correct leave, look up a period end, reopen offline, use Share for a chart and backup, restore, and exercise expired and failed input states. Run the four desktop GUI round trips. |

## Before calling a build ready

1. Record Android build and commit, desktop reference, emulator and phone levels and ABIs, fixture IDs and hashes, expected outcomes, and failures. All in-scope [acceptance cases](../testPlan.md) need a result or a documented blocker.
2. Record cold-start and dated-query timings for the shared-core proof of concept and at least one larger synthetic ledger. Verify progress or cancellation for long loads and that rapid month and filter changes cannot show a stale result.
3. Inspect the actual screens against the annotated boards on a phone. Check Calendar date labels, charts with a readable table, help content, native pickers, user-initiated file sharing, and recovery after a failed or interrupted restore.
4. Rehearse the debug and signed variants separately. Real Play testing uses the signed candidate and a separate test store. Complete the storage and interoperability gates before a production rollout. [Storage acceptance](../testPlan.md#storage-and-interchange-acceptance)
