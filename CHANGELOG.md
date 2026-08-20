# Changelog

## 0.2.0 — 2026-08-20

- Add one-action 100%, 200%, 300%, and 400% reflow magnification.
- Keep enlarged text inside one vertical reading flow, including long tokens.
- Add keyboard magnification shortcuts without changing the user's typeface,
  spacing, palette, column, or line-focus choices.
- Add a temporary Fit, 2x, and 4x source lens for checking OCR against the
  exact captured pixels without creating a named screenshot.
- Keep eligible source images in sealed anonymous memory and release them on
  Read another, Close, cancellation, or parent death.
- Point non-text inspection to Omarchy's native compositor zoom instead of
  adding a second live screen-capture loop.

## 0.1.0 — 2026-08-19

- Capture the active window or a selected region with Omarchy's native picker.
- Read clipboard text without taking a screenshot.
- Recognize text locally with Tesseract and keep image bytes in memory.
- Reflow recognized text into an adjustable, keyboard-operated reader.
- Add four high-contrast palettes, three font families, spacing controls,
  column widths, and a configurable line-focus mask.
- Keep presentation preferences while retaining no captured image or text.
- Supervise capture cleanup across close, disable, hot reload, and shell exit.
- Add deterministic demo, validation, privacy, security, and release tooling.
