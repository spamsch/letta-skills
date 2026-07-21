---
name: managing-letta-privacy-bridge
description: Builds, installs, and drives "Letta Privacy Bridge.app", the signed macOS helper that owns the Calendar, Reminders, Apple Events, and Full Disk Access grants other skills depend on. Use when macOS permission prompts fail to appear, a skill reports a TCC or automation denial, calendar/reminder access is missing, Full Disk Access must be checked, or the bridge needs to be (re)built or installed.
---

# Managing the Letta Privacy Bridge

The bridge is a small installed app (bundle id `ai.letta.privacybridge`) that holds macOS
privacy grants under one stable identity. Grants made to `swift -e` or to the calling
terminal are attributed to the wrong process and evaporate on the next toolchain update;
grants made to the bridge survive and show up as one entry per Privacy pane.

Installed location and binary:

```bash
BRIDGE="$HOME/Applications/Letta Privacy Bridge.app/Contents/MacOS/letta-privacy-bridge"
```

Every command prints exactly one JSON object on stdout; stderr is diagnostics only. Exit
code is 0 when `"ok": true`. Branch on `error.code`, never on message text.

## Check first

```bash
"$BRIDGE" status      # all tracked permissions at once
"$BRIDGE" help        # full command and option list
"$BRIDGE" version     # version + installed bundle path
```

If the binary does not exist, build and install it (below). If a permission reads
`not_determined`, request it. Never read user data to find out whether a permission
works — `status` answers that directly.

## Build and install

Source lives in `assets/privacy-bridge/`. The build is deterministic and needs no Xcode
project, only the Command Line Tools (`xcode-select --install` provides `swiftc`).

```bash
bash assets/privacy-bridge/build-install.sh
```

It compiles with `swiftc`, assembles the bundle, verifies the Info.plist usage strings,
signs (Developer ID when one exists, else ad-hoc), smoke-tests the binary, installs to
`~/Applications/Letta Privacy Bridge.app`, registers it with LaunchServices, and refreshes
a rebuildable source snapshot at `~/Library/Application Support/LettaPrivacyBridge/src`.

Options: `--no-install`, `--dest <dir>`, `--identity <name>`, `--no-snapshot`, `--request`.

Ad-hoc signatures identify the app to TCC by code hash, so **rebuilding an ad-hoc build
discards previously granted permissions**. If prompts reappear after a rebuild, that is
why. A Developer ID certificate (or `LETTA_BRIDGE_SIGN_IDENTITY`) keeps the identity
stable. The bundle is host-architecture only — rebuild on the target Mac, do not copy it
between Intel and Apple Silicon.

## Activate permissions

```bash
"$BRIDGE" request all                       # calendar, reminders, notes, mail
"$BRIDGE" request calendar                  # or reminders | notes | mail
"$BRIDGE" open-settings calendars           # reminders | automation | full-disk-access | privacy
```

`request` relaunches the installed bundle through LaunchServices so macOS attributes the
dialog to the bridge rather than to the calling terminal, then polls a temp result file
(default 180s, `--timeout`) and prints the child's JSON. Use `--in-process` only from a
process that is itself a LaunchServices-launched app.

`request` blocks on a human answering an on-screen dialog. It cannot complete in a fully
headless run. Tell the user what to click, then re-check with `status`.

For Notes and Mail the bridge launches the target app hidden first, because macOS cannot
decide an Apple Events request for an app that is not running. `automation status`
returning `undetermined_app_not_running` (`-600`) is that state, not a failure.

## Full Disk Access

macOS provides no API to request or grant Full Disk Access. No prompt, no entitlement, no
self-add. **Only the user can grant it, manually, in System Settings.** The bridge detects
and links; it never claims to request.

```bash
"$BRIDGE" fda status           # boolean probes only — opens and closes protected paths, reads nothing
"$BRIDGE" fda open-settings    # opens the pane, returns requires_manual_user_action: true
```

Walk the user through: System Settings → Privacy & Security → Full Disk Access → unlock if
dimmed → `+` → add `~/Applications/Letta Privacy Bridge.app` (or toggle it on) → restart the
process that needs the access, because TCC caches decisions per process.

## Data commands

Calendar and Reminders reads and writes go through the bridge:

```bash
"$BRIDGE" calendar list --with-counts
"$BRIDGE" calendar events --start 2026-07-21 --days 7 [--calendar <name>] [--limit <n>]
"$BRIDGE" calendar create --calendar Work --title "Review" --start "2026-07-22 15:00" --duration 45
"$BRIDGE" reminders lists
"$BRIDGE" reminders list [--list <name>] [--due-before <date>] [--limit <n>]
"$BRIDGE" reminders create --title "Renew passport" --list Personal --due "2026-08-01 09:00"
"$BRIDGE" reminders complete --id <id>
```

Notes commands are bridge-owned Apple Events: `notes folders|list|search|read|create|move|delete|folder-create|folder-rename|folder-delete|export`. The bridge sends those events in-process, so the Automation grant stays attached to this app. Mail remains permission plumbing only: `mail status|request|probe`; its probe returns counts and never content.

The bridge caches nothing, writes nothing but its own temp handoff file, and makes no
network calls.

## Troubleshooting

Common `error.code` values and what to do:

| code | meaning | action |
|---|---|---|
| `calendar_access_denied`, `reminders_access_denied` | user denied, or grant lost after rebuild | `request <subject>`; if still denied, `open-settings calendars` |
| `not_determined` | never asked | `request <subject>` |
| `automation_denied` | Apple Events refused for that app | `open-settings automation` |
| `undetermined_app_not_running` | target app is closed | `automation request --app <app>` |
| `not_installed_as_app` | running the binary outside the bundle | reinstall via `build-install.sh` |
| `request_timeout` | nobody answered the dialog | ask the user to answer it, then rerun |
| `restricted` | MDM or parental controls block it | not resolvable locally |

Error objects also carry `hint` and sometimes `recovery`, a list of commands to run.

Deeper background — why an app instead of `swift -e`, signing and sandboxing choices, the
full CLI surface, data-handling guarantees — is in `assets/privacy-bridge/README.md`.
