# Passdown 07 — Shared core and compatibility

November 20, 2026. Suite baseline remains desktop source `7041ce9e9921dd4c407595ed3269de1aca43e699`. The five-hour window had 77% remaining at this checkpoint.

- Recommended a Kotlin and Compose app that calls an extracted Python accounting library in process. The desktop CLI continues as a separate adapter over shared operations and retains its existing compatibility. [Core specification](../sections/core-and-compatibility.md)
- Assigned UI, device lifecycle and storage to Kotlin and accounting validation and calculation to the shared Python library. Specified explicit snapshots, clock and immutable or reviewed operations, structured results and a golden fixture contract.
- Verified the current dependency boundary and Chaquopy's published integration and API requirements. Native package and 16 KB alignment, signing, device behavior and parity require the first implementation proof of concept. No Android build was produced in this milestone.

Start milestone 8 at the storage diagram boundary in the [core specification](../sections/core-and-compatibility.md#responsibilities-and-data-flow) and the [restore and share screens](../sections/data-settings-screens.md#backups-and-system-file-picker). Specify Android's private store contents, compatibility with the CLI schema-v1 archive and both desktop GUIs, field precedence, complete validation, atomic publication and recovery, lifecycle of shared files, and reinstall and phone replacement. Add reproducible compatibility and fault cases.
