# Security

Omarchy plugins execute without a sandbox inside the long-running shell.
Review the exact plugin revision before enabling it.

## Design boundary

ClearRead uses fixed argument arrays to invoke local, standard Omarchy tools.
It does not execute a shell command assembled from OCR text, geometry, a
clipboard payload, a language name, or user input. Dynamic values are parsed,
bounded, and validated before they reach a subprocess.

The helper:

- accepts only documented capture modes;
- validates capture geometry and OCR language syntax;
- validates PNG structure and caps encoded bytes, decoded dimensions, decoded
  pixels, text, diagnostics, and JSON before invoking Tesseract or rendering;
- applies recognition and process-shutdown timeouts;
- uses a two-stage parent-death chain so a force-killed QML process still
  leaves the worker time to reap only children it owns;
- leases the native picker's frozen frame by verified process group and Linux
  pidfd, never by signalling an unverified numeric PID;
- writes no named screen-pixel or recognized-text file during capture and OCR;
- keeps an optional source image only in a size-bounded, sealed anonymous
  Linux memory file owned by the supervised worker;
- binds no socket and opens no network connection; and
- renders all dynamic QML strings as plain text.

Presentation settings live in a plugin-owned directory. ClearRead never
changes Omarchy, Hyprland, Tesseract, clipboard, service, or privilege policy.
An explicit Copy starts the ordinary `wl-copy` selection provider so the
chosen text stays pasteable until clipboard ownership changes; capture and OCR
children remain foreground-owned and bounded. `wl-copy` may use its standard
private, transient unlinked backing file while serving that selection.

The optional source descriptor is accepted only from the active, request-ID
matched capture result. QML validates its exact `/proc/<worker>/fd/<fd>` shape
and dimensions before loading it. Closing or replacing the result writes the
fixed `release` command; timeout, cancellation, launcher death, and shell death
also close the descriptor through the existing parent-death chain.

## Trust boundary

ClearRead trusts the current user's Omarchy installation and the local tools
resolved by its readiness check. It does not attempt to defend against a
compromised desktop session, replaced system executable, hostile compositor,
or another process already able to inspect the user's screen or memory.

OCR output is untrusted text. It is never interpreted as rich text, a URL,
QML, a command, or a path.

## Reporting

Please report a suspected vulnerability privately through GitHub's security
advisory feature for this repository. Do not include private screenshots,
clipboard contents, or recognized text in a public issue.
