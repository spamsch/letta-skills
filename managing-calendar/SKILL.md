---
name: managing-calendar
description: Reads and creates events in Calendar.app on macOS through EventKit and Swift scripts. Use when the user asks about their calendar, today's events, upcoming events, or creating calendar events.
---

# Managing Calendar

Use the Swift EventKit scripts in `scripts/` to read and create calendar events. These scripts require Calendar permissions in System Settings > Privacy & Security > Calendars.

## Get today's events

```bash
bash scripts/get-today-events.sh
bash scripts/get-today-events.sh --calendar "Work"
bash scripts/get-today-events.sh --account "Google"
```

Returns all events scheduled for today, grouped by calendar and account. Shows time, title, location, and calendar name.

## Get upcoming events

```bash
bash scripts/get-week-events.sh
bash scripts/get-week-events.sh --days 14
bash scripts/get-week-events.sh --calendar "Personal" --account "iCloud"
```

Returns events for the next 7 days (or custom range) with the same grouping and detail as today's events.

## Create calendar events

```bash
# All-day event
bash scripts/create-event.sh \
  --calendar "Personal" \
  --title "Birthday" \
  --date "2026-07-25" \
  --all-day
```

Creates a new event with title, date/time, location, and notes. Supports both all-day and timed events.

**Timed event with end time:**
```bash
bash scripts/create-event.sh \
  --calendar "Work" \
  --title "Conference Call" \
  --start "2026-07-22 10:00" \
  --end "2026-07-22 11:30" \
  --location "Zoom" \
  --notes "Join link: https://zoom.us/j/123456"
```

**Timed event with duration:**
```bash
bash scripts/create-event.sh \
  --calendar "Work" \
  --title "Code Review" \
  --start "2026-07-22 15:00" \
  --duration 45 \
  --notes "Review PR #123"
```

## List available calendars

```bash
bash scripts/list-calendars.sh
bash scripts/list-calendars.sh --with-counts
```

Lists all calendars with their account names, useful for finding the correct calendar name for filtering or creating events. Use `--with-counts` to see event counts per calendar.

## Permissions

The first time these scripts run, macOS will prompt for Calendar access. Grant full access to EventKit in System Settings > Privacy & Security > Calendars.

## Prerequisites

- Xcode Command Line Tools (provides `swift` command)
- Calendar permission granted in System Settings > Privacy & Security > Calendars