# ClearRead for Omarchy

If text is visible, it should be readable.

ClearRead turns text trapped in screenshots, scanned documents, videos,
canvas apps, and remote desktops into a calm, adjustable reading surface.
Select what you want to read. ClearRead recognizes it locally, reflows the
words, and gets out of the way.

It is the difference between making pixels larger and making text readable.

![ClearRead reflowing a small scanned document into a focused Sepia reading view](preview.png)

## What it does

- Reads the active window without requiring a pointer.
- Uses Omarchy's native picker for a precise screen region.
- Opens existing clipboard text without taking a screenshot.
- Reflows recognized text at a comfortable line length.
- Adjusts typeface, size, weight, line height, letter spacing, word spacing,
  column width, contrast, and line focus.
- Works from the keyboard, including capture, reading, copying, and closing.

ClearRead is local and transient. It creates no screenshot file, OCR history,
account, analytics record, or network request. The captured image exists only
long enough to reach Tesseract. Recognized text is discarded from ClearRead
when the reader closes. Text the user explicitly copied remains on the normal
Wayland clipboard. Only presentation preferences remain in ClearRead.

## Try it

Omarchy plugins run inside the long-lived shell without a sandbox, so review
this repository before installing it.

```bash
omarchy plugin add https://github.com/josephbriones/omarchy-clearread.git --enable
omarchy-shell shell summon io.github.josephbriones.clearread '{"demo":true}'
```

The demo uses fixed sample text. It does not inspect the screen, open the
clipboard, or start Tesseract.

## Use it

Open ClearRead:

```bash
omarchy-shell shell toggle io.github.josephbriones.clearread
```

Then choose one explicit action:

- **Read active window** captures the application behind ClearRead. This is
  the fully keyboard-operated path.
- **Select screen area** hides ClearRead and opens Omarchy's native region
  picker. Escape cancels the selection.
- **Read clipboard** reflows text already on the clipboard without capturing
  the screen.

ClearRead hides its own surface before pixel capture. Once the image is in
memory, it returns with a local recognition state and then opens the reader.

In the reader, Tab moves through every control, including the explicit
**Copy** button. Other useful keys:

| Key | Action |
|---|---|
| `Ctrl` + `+` / `Ctrl` + `-` | Increase or decrease text size |
| `Ctrl` + `0` | Restore the default text size |
| `Page Up` / `Page Down` | Move one viewport |
| `Home` / `End` | Move to the start or end |
| `Escape` | Cancel recognition or close ClearRead |

Copying is always explicit. ClearRead never replaces the clipboard merely
because it recognized text.

## Local requirements

ClearRead targets current Omarchy Quattro. It uses the capture and OCR tools
already present in a standard installation: Omarchy's region picker, `grim`,
`tesseract`, `wl-clipboard`, Hyprland tools, Python, and `setpriv`.

English OCR data is part of the standard installation. Additional Tesseract
languages are optional. ClearRead honors `OMARCHY_OCR_LANGS`, using `eng` when
it is unset. The [setup guide](docs/SETUP.md) covers language checks and the
local doctor command.

Opening ClearRead checks these local capabilities. It never installs a
package, downloads language data, changes a global shortcut, or rewrites
Omarchy, Hyprland, Tesseract, or clipboard configuration.

## Deliberately small

ClearRead is an accessible presentation layer, not an OCR filing cabinet.

- No saved images, text archive, search history, or watched region.
- No automatic capture or clipboard watcher.
- No cloud OCR, translation, summarization, or generated rewriting.
- No automatic clipboard write.
- No claim that OCR is exact. The reader labels recognized text so critical
  details can be checked against the source.
- No claim to replace a screen reader or expose document semantics.

Handwriting, equations, tables, complex columns, and protected surfaces may
recognize poorly or not at all. Accuracy depends on source size, contrast,
language data, and Tesseract.

## Remove it

Close ClearRead, then use Omarchy's normal removal path:

```bash
omarchy plugin remove io.github.josephbriones.clearread
```

Removal leaves the small presentation-settings file alone. It contains no
captured image or recognized text; [Privacy](PRIVACY.md) documents its exact
fields and location.

## Development

Run the portable suite:

```bash
bash scripts/validate.sh
```

The tests use fake capture and OCR tools, so they exercise the complete
in-memory protocol without inspecting the developer's screen. Real Hyprland,
multi-display, keyboard-focus, and OCR-quality checks remain explicit Omarchy
acceptance gates; see [Testing](docs/TESTING.md).

The [architecture](docs/ARCHITECTURE.md) describes the capture boundary and
process lifecycle. [Security](SECURITY.md) explains the threat model.

## License

[MIT](LICENSE) © 2026 Joseph Briones.
