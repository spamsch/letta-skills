---
name: managing-mac-displays
description: Inspects, snapshots, disconnects, and restores physical Mac display layouts with displayplacer while preserving a known recovery path. Use when the user mentions external monitors, display layouts, Remote Desktop screen size, disconnecting or reconnecting screens, displayplacer, or a monitor missing after software disable.
---

# Managing Mac displays

Use `scripts/mac_displays.py` for every status check, profile, disconnect, and restore. Use only `displayplacer` and native macOS inspection. **Never launch, query, or invoke BetterDisplay.** BetterDisplay must not be running during disconnect or restore; the helper refuses mutations when it detects that process.

## Read-only status

```bash
python3 scripts/mac_displays.py status
```

Report each persistent ID, serial ID, type, resolution, origin, main status, and enabled state.

## Snapshot before changing anything

Create a fresh profile before any display mutation:

```bash
python3 scripts/mac_displays.py snapshot --output /tmp/display-profile.json
```

Profiles contain displayplacer arguments, not shell source. Never overwrite an existing profile.

## Disconnect safety boundary

On Apple Silicon, `displayplacer enabled:false` can remove a physical screen from the macOS device tree. The same command cannot then re-enable it because the display ID is no longer visible. Reconnecting the same cable/port may also fail.

Before disconnecting:

1. Run `status` and identify one specific external persistent ID.
2. Confirm `betterdisplay_running` is `false`. If it is true, stop and ask the user to quit BetterDisplay normally; do not control the app yourself.
3. Ensure another enabled display—normally the MacBook panel—will remain.
4. Ensure the user is physically near the Mac and can move the display cable to another port or log out/reboot.
5. Create and show the snapshot path.
6. Explain the recovery sequence and obtain explicit confirmation.

Only then run the exact acknowledgment token:

```bash
python3 scripts/mac_displays.py disconnect \
  --id DISPLAY-PERSISTENT-ID \
  --profile /tmp/display-profile.json \
  --confirm I-ACCEPT-HARDWARE-RECOVERY
```

Never run this from a remote-only session where nobody can physically access the Mac. Never promise automatic software reconnection.

## Restore

If all screens in the profile are visible:

```bash
python3 scripts/mac_displays.py restore --profile /tmp/display-profile.json
```

If the external display is absent, do not retry displayplacer in a loop. Follow this recovery order:

1. Unplug the display connection.
2. Reconnect through a **different** USB-C, Thunderbolt, or HDMI port, preferably directly into the Mac rather than the same dock port.
3. Wait ten seconds, run `status`, then run `restore` when the display reappears.
4. If it remains absent, log out and back in or reboot. A WindowServer restart is disruptive and requires fresh explicit approval.

To wait while the user moves the cable, use a bounded foreground check:

```bash
python3 scripts/mac_displays.py wait-restore \
  --profile /tmp/display-profile.json \
  --timeout 180
```

Report whether restoration succeeded and the current topology. Preserve the profile for later diagnosis.
