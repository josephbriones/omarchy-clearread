# Privacy

ClearRead has one narrow reason to inspect the screen: the user explicitly
asks it to turn visible text into adjustable text.

## Before capture

Opening the plugin performs a dependency check. It does not take a screenshot,
read the clipboard, or run OCR recognition. Screen and clipboard access begin
only after the matching button is activated.

## During capture

- ClearRead hides its own surface before pixel capture.
- The active-window or selected-region image moves from `grim` to local
  Tesseract through memory.
- An eligible image may then remain in a sealed anonymous Linux memory file so
  the user can compare OCR with the exact captured pixels. It has no named or
  persistent filesystem entry, is never added to history, and is released on
  Close or Read another.
- No named PNG, OCR result, capture history, debug transcript, or cache file is
  created.
- Recognition starts no network client and sends no image or text away from
  the machine.
- Cancel, Close, timeout, and shell exit terminate plugin-owned children with
  bounded cleanup.

Clipboard reading is a separate explicit action. Copying recognized text is
also separate and explicit. ClearRead does not clear or restore the clipboard
on close. After Copy, `wl-copy` may keep the selected text available through a
standard Wayland selection provider until the clipboard is replaced or a
clipboard manager takes ownership. ClearRead starts that lifetime only from
the visible Copy action. The standard `wl-copy` implementation may create a
private temporary backing file and unlink it before the provider backgrounds;
ClearRead itself creates no named clipboard file or history.

## After capture

The QML reader holds recognized text in process memory while it is open. For
eligible window and region reads, the supervised worker may also hold the
sealed anonymous source image for the optional **Compare source** view.
Starting another read and closing the plugin release both. This is ordinary
process-memory disposal, not a claim of secure memory erasure. Clipboard text,
demo mode, unsupported platforms, and images beyond the source-view bounds do
not receive a source image.

ClearRead retains only presentation preferences:

- font family, size, and weight;
- line, letter, and word spacing;
- column width and color theme; and
- line-focus size.

They are stored in a plugin-owned settings directory under
`$XDG_CONFIG_HOME`, or `~/.config` when that variable is unset. The settings
file contains no screen image, clipboard payload, or recognized text.

## No hidden services

ClearRead has no capture daemon, autostart capture, account, analytics,
telemetry, remote API, or background clipboard watcher. `keepLoaded` keeps
only the lightweight QML owner resident so it can complete child cleanup after
the visible overlay closes. The supervised launcher and worker exist only for
an explicit setup check, capture, source-image hold, or copy action and then
exit. A source holder is never detached and ends when the image is released.
The ordinary clipboard provider described above is the sole detached
post-action lifetime.
