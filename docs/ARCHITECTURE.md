# Architecture

ClearRead has two parts and one direction of control:

```text
explicit user action
        │
        ▼
ClearRead.qml ── foreground Process ── bin/clearread launcher
                                          │ parent-death boundary
                                          ▼
                                  lib/clearread.py worker
                                          │
              ┌───────────────────────────┼─────────────────────────┐
              │                           │                         │
        active window                screen region              clipboard
        Hyprland geometry       Omarchy native picker           wl-paste
              │                           │                         │
              └────────── grim PNG in memory ───────────┐          │
                                                       ▼          │
                                                local Tesseract    │
                                                       │          │
                                                       └────┬─────┘
                                                            ▼
                                                   bounded JSONL result
                                                            │
                                                            ▼
                                               plain-text reflow reader
```

The QML plugin passes `Quickshell.processId` to a tiny non-exec launcher. The
launcher verifies that exact parent before and after arming its Linux
parent-death signal, then passes its own PID to the worker for the same check.
On an ordinary close, the launcher forwards the stop signal and waits. If
Quickshell destroys its `Process` with SIGKILL during disable, reload, or shell
teardown, Linux delivers a parent-death signal to the worker instead. The
worker remains alive long enough to own and reap every capture and OCR process
group.

The extra process is intentional: it leaves the worker alive just long enough
to perform bounded cleanup even when the QML-owned process is force-killed.
No capture or OCR process is left as a daemon.

Explicit Copy follows the normal Wayland clipboard contract. `wl-copy` may
keep a selection provider after ClearRead exits so the chosen text remains
pasteable; it ends when another selection replaces it or a clipboard manager
takes ownership. That narrow, user-requested clipboard lifetime is not part of
capture or OCR processing.

## Capture paths

**Active window** asks Hyprland for the application geometry after the
ClearRead surface has hidden, then captures exactly that rectangle. This is the
pointer-free path.

**Screen area** uses Omarchy's native smart region picker, including its normal
window hints, frozen selection frame, and Escape behavior. With
`--keep-freeze`, the picker returns its frozen-screen PID followed by geometry.
ClearRead verifies that PID against the still-owned picker process group,
opens a Linux pidfd lease, and only then reaps the picker. The frozen frame is
released in a `finally` path immediately after `grim` succeeds or fails and
before OCR begins. No PID file is used, and an unrelated or reused PID is never
signalled.

**Clipboard** reads an existing text MIME payload. It opens neither `grim` nor
Tesseract.

For pixel paths, `grim` returns PNG bytes on stdout. Those bytes are passed to
Tesseract on stdin. Both stages are bounded and no filename exists.

## Protocol

The helper writes one JSON object per line. Events are deliberately small:

- `doctor` reports capability booleans, missing tools, language, and issues;
- `status` reports `selecting`, `capturing`, or `recognizing`;
- `result` carries bounded plain text, normalized paragraphs, source, capture
  geometry, and monitor name;
- `cancelled` distinguishes an ordinary Escape from a failure; and
- `error` carries a stable code and a bounded human-readable message.

The JavaScript boundary rejects malformed, oversized, or unknown events. QML
renders every dynamic field with `Text.PlainText`.

## Reflow

OCR lines are not document structure. ClearRead makes one modest
transformation: blank lines become paragraphs, wrapped lines join with spaces,
a trailing hyphen stays attached across a source line break, and obvious list
items stay separate.
It does not invent headings, repair facts, summarize, translate, or silently
rewrite ambiguous text.

The reader remains a literal plain-text surface. Presentation controls change
only layout: font, scale, spacing, width, contrast, and the viewport line-focus
mask. Copy is an explicit button action; v0.1 does not trade plain-text safety
for rich-text selection markup.

## Persistent state

Only an allowlisted presentation object is written. Capture mode state,
screen geometry, clipboard data, image bytes, OCR text, errors, and source
application details are not settings and are never persisted.
