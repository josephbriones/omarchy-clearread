# Testing

Portable validation is deterministic and does not inspect the developer's
screen:

```bash
bash scripts/validate.sh
```

The Python suite supplies fake picker, Hyprland, capture, OCR, and clipboard
executables. It covers geometry and language validation, every Wayland output
transform, reflow, Unicode, stable failure families, timeouts, cancellation,
output bounds, JSON protocol, copy input, child cleanup, and the absence of
plugin-created capture artifacts. On Linux it also SIGKILLs the QML-facing
launcher during selection, after the frozen frame has been handed to `grim`,
and during Tesseract recognition, then proves the worker and owned descendants
exit. The Node suite covers payload, event, settings, theme, and
presentation-state boundaries.

Portable tests prove code paths. They do not prove Wayland focus, compositor
capture, OCR quality, display placement, or visual layout.

## Omarchy acceptance

Run the no-capture demo first:

```bash
bash scripts/acceptance-test.sh
```

Real capture is intentionally a separate, interactive gate:

```bash
bash scripts/acceptance-test.sh --real
```

The real gate requires an interactive Omarchy Hyprland session and verifies
active-window OCR and selected-region OCR as separate captures. It runs the
portable suite first and closes the overlay on success, failure, or interrupt.

Before release, record evidence for every unchecked item in
[the release checklist](RELEASE_CHECKLIST.md), including:

- active-window capture with only the keyboard;
- selected-region capture and Escape cancellation;
- the ClearRead surface being absent from its own capture;
- 200% text size at 1280×720 without horizontal reading scroll;
- Tab order and visible focus for every control;
- 1-, 3-, and 5-line focus behavior;
- clipboard unchanged until Copy;
- two-display placement and scale factors 1.0, 1.25, and 2.0;
- no image or text artifact in plugin config, cache, runtime, or temporary
  paths; and
- capture and OCR processes gone within two seconds after Cancel, Close,
  disable, hot reload, and shell restart; and
- after explicit Copy, the ordinary `wl-copy` provider remains usable until
  clipboard ownership changes, then exits.

Use generated, non-sensitive fixture text for screenshots and logs. Never put
a personal document, remote-desktop session, or clipboard payload in a bug
report.
