# ForcedFocus Production Readiness Gate

This checklist is the required final-release gate for the Web Dashboard, Menu Bar app, Chrome Extension, daemon API, settings, notifications, and synchronization behavior.

## Canonical Build Inputs

- web/ is the canonical UI source. `install.sh` deploys this directory to `/usr/local/share/forcefocus/web`.
- `forcefocus_daemon.py` is the canonical HTTP/API runtime on `http://127.0.0.1:7070`.
- `chrome-extension/` is the canonical unpacked Chrome Extension source.
- `forcefocus_menubar.swift` and `web/menubar.html` / `web/menubar.js` make up the Menu Bar surface.

## Automated Gate

Run these before every release:

```bash
node --check web/app.js
node --check web/settings.js
node --check web/menubar.js
node --check chrome-extension/background.js
node --check chrome-extension/popup.js
plutil -lint ForcedFocusBar.app/Contents/Info.plist
swiftc -typecheck forcefocus_menubar.swift
python3 -m pytest
```

All checks must pass. Any static source-divergence or production-readiness test failure blocks release.

## Synchronization SLA

- Web/Menu Bar <= 1 second after daemon state changes when SSE is connected.
- Extension <= 3 seconds after active-session transitions when the service worker is awake.
- Extension <= 60 seconds through the MV3 alarm fallback after service worker suspension or SSE loss.
- Compared state fields: `active`, `mode`, `session_type`, `remaining_seconds`, `pomo_phase`, `pending_unlock`, `schedules`, and `recurring_schedules`.
- Settings-only changes must bump `state_revision` so `/api/stream` emits immediately and the extension refreshes cached settings.
- Chrome DNR rule rebuilds must validate rule capacity before clearing existing rules; oversized lists must show an `ERR` badge and notification rather than leaving partial rules.

## Manual Release Scenarios

- Start and stop a standard focus session from the Web Dashboard.
- Start Pomodoro, observe focus to break to focus transition, and confirm timer rings stay smooth.
- Start Rescue from each idle surface, then verify Rescue is unavailable while any session is active.
- Add a permanent block during an active blacklist session and confirm Chrome blocks it without waiting for the session to restart.
- Create, edit, pause, resume, duplicate, and remove a recurring schedule.
- Save settings, upload a valid `.mp3`, reject a non-mp3, delete a sound, and edit/delete a group.
- Deny macOS notification permission and confirm the app logs or displays a fallback instead of silently failing.
- Review `chrome-extension/PERMISSIONS.md` against `manifest.json` before extension packaging.
- Load the Chrome Extension unpacked, wait for service worker suspension, then confirm alarm sync reconciles rules.
- Validate desktop, tablet, and mobile-width dashboard layouts at roughly `1280px`, `950px`, and `390px`.

## Visual And Accessibility Gate

- Active focus must not dull or disable whole dashboard cards.
- Keyboard focus must remain visible for buttons, inputs, selects, chips, and modal controls.
- Reduced-motion mode must disable nonessential animation.
- Compact surfaces must avoid text overlap and keep touch targets at least 44px where practical.
- Icon-only controls must have an accessible name via text, `title`, or `aria-label`.
