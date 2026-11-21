"""Render editable phone mockups to PNG for the FedLeave Android specification."""

import argparse
import json
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SURFACE = "#FCFCFF"
CANVAS = "#E9EEF7"
INK = "#13223D"
MUTED = "#485A77"
PRIMARY = "#194AAB"
SELECTED = "#DDE8FF"
LINE = "#D9E3F2"
WARN = "#765009"
WARN_BG = "#FFF3D6"
PHONE_WIDTH = 366
PHONE_HEIGHT = 674
PADDING = 22
GAP = 24


@lru_cache
def get_font(font_dir, size, bold=False):
    name = "Lato-Bold.ttf" if bold else "Lato-Regular.ttf"
    return ImageFont.truetype(str(font_dir / name), size)


class Screen:
    def __init__(self, image, font_dir, x, top, screen):
        self.draw = ImageDraw.Draw(image)
        self.font_dir = font_dir
        self.x = x
        self.top = top
        self.right = x + PHONE_WIDTH
        self.bottom = top + PHONE_HEIGHT
        self.left = x + PADDING
        self.inner_right = self.right - PADDING
        self.width = PHONE_WIDTH - 2 * PADDING
        self.cursor = top + 22
        self.screen = screen

    def text(self, x, y, label, size=16, color=INK, bold=False, anchor="la"):
        font = get_font(self.font_dir, size, bold)
        self.draw.text((x, y), label, font=font, fill=color, anchor=anchor)

    def wrap(self, value, size, width, bold=False):
        font = get_font(self.font_dir, size, bold)
        lines = []
        current = ""
        for word in value.split():
            joined = f"{current} {word}".strip()
            if self.draw.textlength(joined, font=font) <= width or not current:
                current = joined
            else:
                lines.append(current)
                current = word
        return [*lines, current] if current else lines

    def box(self, x, y, right, bottom, fill, radius=10):
        self.draw.rounded_rectangle((x, y, right, bottom), radius, fill=fill)

    def mark(self, number, y):
        if number is None:
            return
        x = self.right - 14
        label = str(number)
        self.draw.ellipse((x - 11, y - 11, x + 11, y + 11), fill=PRIMARY, outline=SURFACE, width=2)
        self.text(x, y, label, 12, "#FFFFFF", bold=True, anchor="mm")

    def render(self):
        self.box(self.x + 3, self.top + 5, self.right + 3, self.bottom + 5, "#C5D2E6", 24)
        self.box(self.x, self.top, self.right, self.bottom, SURFACE, 24)
        self.text(self.left, self.cursor, "FedLeave", 13, PRIMARY, bold=True)
        top_action = self.screen.get("top_action")
        self.text(self.inner_right, self.cursor, top_action or "9:41", 13, PRIMARY if top_action else MUTED,
                  bool(top_action), "ra")
        self.cursor += 28
        subtitle = self.screen.get("subtitle")
        self.paragraph({"text": self.screen["title"]}, size=28, bold=True, padding=4)
        if subtitle:
            self.paragraph({"text": subtitle}, size=14, color=MUTED, padding=12)
        for element in self.screen["items"]:
            if element["type"] == "heading":
                self.paragraph(element, size=17, bold=True, padding=8)
            elif element["type"] == "text":
                self.paragraph(element, size=14, color=MUTED, padding=11)
            else:
                getattr(self, element["type"])(element)
        nav = self.screen.get("nav")
        limit = self.bottom - (58 if nav else 14)
        if self.cursor > limit:
            raise ValueError(f"{self.screen['id']} overflows by {self.cursor - limit}px")
        if nav:
            y = self.bottom - 48
            self.draw.line((self.left, y - 5, self.inner_right, y - 5), fill=LINE)
            for index, label in enumerate(("Calendar", "Reports", "Settings")):
                center = self.left + (index + 0.5) * (self.width // 3)
                if label == nav:
                    self.box(center - 50, y + 3, center + 50, y + 33, SELECTED, 14)
                self.text(center, y + 18, label, 13, PRIMARY if label == nav else MUTED, label == nav, "mm")
        self.text(self.x, self.bottom + 11, self.screen["id"], 12, MUTED, bold=True)

    def paragraph(self, item, size, color=INK, bold=False, padding=8):
        y = self.cursor
        step = size + 5
        for line in self.wrap(item["text"], size, self.width - 8, bold):
            self.text(self.left, self.cursor, line, size, color, bold)
            self.cursor += step
        self.mark(item.get("note"), y + 12)
        self.cursor += padding

    def row(self, item):
        label, value = item["text"], item.get("value", "")
        value_end = self.inner_right - 10
        self.box(self.left, self.cursor, self.inner_right, self.cursor + 35, "#F0F4FC", 8)
        self.text(self.left + 10, self.cursor + 17, label, 15, INK, True, "lm")
        if item.get("dropdown"):
            x, y = value_end - 5, self.cursor + 17
            self.draw.line((x - 4, y - 2, x, y + 2, x + 4, y - 2), fill=PRIMARY, width=2)
            value_end -= 16
        self.text(value_end, self.cursor + 17, value, 14, MUTED, anchor="rm")
        self.mark(item.get("note"), self.cursor + 17)
        self.cursor += 42

    def card(self, item):
        y = self.cursor
        lines = self.wrap(item.get("body", ""), 14, self.width - 28)
        height = 42 + 19 * len(lines)
        fill = WARN_BG if item.get("warning") else SELECTED
        color = WARN if item.get("warning") else INK
        self.box(self.left, y, self.inner_right, y + height, fill, 13)
        self.text(self.left + 14, y + 10, item["text"], 16, color, bold=True)
        if indicator := item.get("indicator"):
            self.text(self.inner_right - 14, y + 10, indicator, 21, PRIMARY, bold=True, anchor="ra")
        for index, text in enumerate(lines):
            self.text(self.left + 14, y + 34 + 19 * index, text, 14, color)
        self.mark(item.get("note"), y + 19)
        self.cursor += height + 10

    def action(self, item):
        emphasis = item.get("emphasis", True)
        fill = PRIMARY if emphasis else SELECTED
        self.box(self.left, self.cursor, self.inner_right, self.cursor + 38, fill, 18)
        self.text(
            (self.left + self.inner_right) // 2, self.cursor + 19, item["text"], 15,
            "#FFFFFF" if emphasis else PRIMARY, bold=True, anchor="mm",
        )
        self.mark(item.get("note"), self.cursor + 18)
        self.cursor += 47

    def calendar(self, item):
        y = self.cursor
        self.text(self.left, y, item["text"], 17, bold=True)
        self.text(self.inner_right - 6, y, "‹   ›", 17, PRIMARY, bold=True, anchor="ra")
        step = self.width // 7
        first_row = y + 54
        for column, label in enumerate(("S", "M", "T", "W", "T", "F", "S")):
            self.text(self.left + step * column + step // 2, y + 36, label, 12, MUTED, anchor="mm")
        marks = item.get("ends", [])
        paydays = item.get("paydays", [])
        for number in range(1, item.get("days", 31) + 1):
            row, column = divmod(item["start"] + number - 1, 7)
            x = self.left + step * column + step // 2
            cell_y = first_row + row * 28
            active = number == item.get("selected")
            if active:
                self.draw.ellipse((x - 12, cell_y - 12, x + 12, cell_y + 12), fill=PRIMARY)
            self.text(x, cell_y, str(number), 13, "#FFFFFF" if active else INK, number in marks, "mm")
            if number in marks:
                self.draw.ellipse((x - 2, cell_y + 9, x + 2, cell_y + 13), fill="#FFFFFF" if active else PRIMARY)
            if number in paydays:
                self.box(x - 4, cell_y + 10, x + 4, cell_y + 12, "#FFFFFF" if active else "#667D5E", 1)
        self.mark(item.get("note"), first_row + 18)
        self.cursor = first_row + 28 * ((item["start"] + item.get("days", 31) - 1) // 7) + 25
        legend = "●  Pay-period end      ▬  Payday" if paydays else "●  Pay-period end"
        self.paragraph({"text": item.get("legend", legend)}, 12, MUTED, padding=8)

    def activity_calendar(self, item):
        left = self.x + 8
        column_width = (PHONE_WIDTH - 16) // 7
        row_height = 60
        first_row = self.cursor + 24
        for column, label in enumerate(("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")):
            x = left + column * column_width + column_width // 2
            self.text(x, self.cursor + 5, label, 11, MUTED, anchor="mm")

        period_ends = set(item.get("ends", []))
        paydays = set(item.get("paydays", []))
        activity = item.get("activity", {})
        for day in range(1, item["days"] + 1):
            row, column = divmod(item["start"] + day - 1, 7)
            x = left + column * column_width
            y = first_row + row * row_height
            today = day == item.get("today")
            self.box(x + 1, y + 1, x + column_width - 1, y + row_height - 2, SELECTED if today else "#F0F4FC", 7)
            if today:
                self.draw.rounded_rectangle(
                    (x + 1, y + 1, x + column_width - 1, y + row_height - 2), 7, outline=PRIMARY, width=1,
                )
            self.text(x + 5, y + 4, str(day), 13, PRIMARY if today else INK, today or day in period_ends)
            if day in period_ends:
                self.draw.ellipse((x + 37, y + 9, x + 43, y + 15), fill=PRIMARY)
            if day in paydays:
                self.box(x + 34, y + 10, x + 43, y + 13, "#597451", 1)

            entries = activity.get(str(day), [])
            for index, entry in enumerate(entries[:2]):
                line_y = y + 23 + index * 12
                self.text(x + 5, line_y, entry["text"], 11, INK, bold=True)
                if entry.get("planned"):
                    self.text(x + column_width - 5, line_y, "P", 10, PRIMARY, bold=True, anchor="ra")
            if len(entries) > 2:
                self.text(x + 5, y + 47, f"+{len(entries) - 2}", 10, PRIMARY, bold=True)

        row_count = (item["start"] + item["days"] + 6) // 7
        self.mark(item.get("note"), first_row + row_height * 2)
        self.cursor = first_row + row_count * row_height + 9
        self.paragraph({"text": "A Annual   S Sick   C Comp   ·   Hours"}, 11, MUTED, padding=0)
        self.paragraph({"text": "P Planned     ● Period end     — Payday"}, 11, MUTED, padding=4)

    def chart(self, item):
        y = self.cursor
        self.box(self.left, y, self.inner_right, y + 118, "#F0F4FC", 12)
        self.text(self.left + 12, y + 9, item["text"], 13, bold=True)
        start, end, base = self.left + 28, self.inner_right - 18, y + 90
        for offset in (0, 25, 50):
            self.draw.line((start, base - offset, end, base - offset), fill=LINE, width=1)
        values = item["values"]
        scale = max(values) or 1
        if item.get("style") == "line":
            positions = item.get("positions", [index / (len(values) - 1) for index in range(len(values))])
            points = [
                (start + (end - start) * position, base - value * 57 / scale)
                for position, value in zip(positions, values, strict=True)
            ]
            if item.get("step"):
                points = [points[0], *[point for previous, current in zip(points, points[1:]) for point in (
                    (current[0], previous[1]), current,
                )]]
            self.draw.line(points, fill=PRIMARY, width=3, joint="curve")
        else:
            step = (end - start) / len(values)
            for index, value in enumerate(values):
                x = start + index * step + 5
                self.box(x, base - value * 57 / scale, x + step - 10, base, PRIMARY, 4)
        self.text(start, y + 96, item.get("start_label", ""), 11, MUTED)
        self.text(end, y + 96, item.get("end_label", ""), 11, MUTED, anchor="ra")
        self.mark(item.get("note"), y + 18)
        self.cursor += 129

    def heatmap(self, item):
        y = self.cursor
        rows = item["rows"]
        columns = len(rows[0])
        step = min(24, (self.width - 26) // columns)
        height = min(13, step)
        legend_y = y + 43 + len(rows) * (height + 2)
        self.box(self.left, y, self.inner_right, legend_y + 25, "#F0F4FC", 12)
        self.text(self.left + 12, y + 10, item["text"], 13, bold=True)
        colors = ("#E1E8F2", "#BDD1F6", "#789FDE", PRIMARY)
        for row_index, row in enumerate(rows):
            for column, value in enumerate(row):
                x = self.left + 12 + column * step
                cell_y = y + 37 + row_index * (height + 2)
                self.box(x, cell_y, x + step - 2, cell_y + height, colors[value], 2)
        self.text(self.left + 12, legend_y, "0 h    ·    up to 8 h", 11, MUTED)
        self.mark(item.get("note"), y + 16)
        self.cursor = legend_y + 37


def render_board(board, font_dir, destination):
    screens = board["screens"]
    width = len(screens) * PHONE_WIDTH + (len(screens) + 1) * GAP
    image = Image.new("RGB", (width, PHONE_HEIGHT + 118), CANVAS)
    draw = ImageDraw.Draw(image)
    draw.text((GAP, 16), board["title"], font=get_font(font_dir, 25, True), fill=INK)
    draw.text((GAP, 54), board["subtitle"], font=get_font(font_dir, 14), fill=MUTED)
    ids = [screen["id"] for screen in screens]
    if len(ids) != len(set(ids)):
        raise ValueError(f"Duplicate screen in {board['file']}")
    for index, screen in enumerate(screens):
        x = GAP + index * (PHONE_WIDTH + GAP)
        Screen(image, font_dir, x, 82, screen).render()
    image.save(destination / board["file"], optimize=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, nargs="+")
    parser.add_argument("--font-dir", type=Path, default=Path("/usr/share/fonts/truetype/lato"))
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for source in args.source:
        for board in json.loads(source.read_text(encoding="utf-8")):
            render_board(board, args.font_dir, args.output)


if __name__ == "__main__":
    main()
