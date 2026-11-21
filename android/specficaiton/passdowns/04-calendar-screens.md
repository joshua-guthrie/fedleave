# Passdown 04 — Phone navigation and Calendar screens

November 20, 2026. Closeout was at 83% remaining in the five-hour window. The accounting reference is still `7041ce9e9921dd4c407595ed3269de1aca43e699`.

- Added 5 annotated image boards covering 18 screen and state IDs and 30 callouts. They cover first use, setup, one dated balance panel, period detail, historical and unavailable states, adding and reviewing entries, and transaction history and corrections. [Screens and requirements](../sections/calendar-screens.md)
- Chose Calendar, Reports and Settings as the three persistent destinations and used a fixed blue Material 3 direction in the images. The date picker and Calendar visually distinguish pay-period ends from paydays. The example shows separate balance and editing dates.
- Added the editable [Calendar board data](../mockups/calendar.json) and [Pillow renderer](../mockups/render.py). Ran the generator, inspected the image boards and verified the numbered callouts, PNG readability, and prior Calendar screen IDs.
- Maintenance, parental detail and settings share the later data and settings screens. Design images show a light palette. The implementation acceptance plan still requires dark mode, contrast, scaling and TalkBack checks.

Start milestone 5 at the [nine report parity rows](../parity.md#reports). Next create report catalog, summary, Seasonality and supporting-entries mockups, followed by Heatmap, lifecycle, cumulative usage, balance charts, comparison, month preview and share or print. Reuse the same renderer and annotate the loading, empty and unavailable paths alongside the successful workflows. [Report requirements](../sections/reports-data-and-preferences.md#reports)
