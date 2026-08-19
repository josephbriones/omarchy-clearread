# Setup

ClearRead is designed for a current Omarchy Quattro installation. A standard
installation already contains its runtime pieces: the Omarchy capture helper,
Hyprland tools, `grim`, `tesseract`, English Tesseract data, `wl-copy`,
`wl-paste`, Python, and `setpriv`.

## Check readiness

From the installed plugin directory:

```bash
./bin/clearread doctor --omarchy-path "${OMARCHY_PATH:-$HOME/.local/share/omarchy}"
```

The command prints one JSON object. `ready: true` means at least one reading
action is available. Inspect `capabilities` for the active-window, region,
clipboard, and explicit-copy paths; one unavailable command does not hide the
rest of the reader.

The doctor does not capture a window, open the region picker, read the
clipboard, or run Tesseract recognition.

## OCR languages

English is the default:

```bash
tesseract --list-langs
```

Set the same language expression accepted by Tesseract before launching the
Omarchy shell, for example:

```bash
export OMARCHY_OCR_LANGS=eng+spa
```

ClearRead validates the expression but does not install or download language
data. If Tesseract reports a missing language, add the matching Arch language
data package through your normal, reviewed system-maintenance workflow and run
the doctor again.

## Optional shortcut

ClearRead does not edit keybindings. A user-owned Hyprland binding can invoke:

```text
omarchy-shell shell toggle io.github.josephbriones.clearread
```

The active-window action is intentionally first in Tab order, so the complete
capture flow is usable without a pointer once the overlay opens.
