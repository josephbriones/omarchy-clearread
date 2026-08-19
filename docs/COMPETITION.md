# Competition position

## The idea

ClearRead turns text that an application exposes only as pixels into an
adjustable reading surface.

Omarchy already extracts text to the clipboard. Community plugins already
store OCR history, read clipboard text aloud, and accelerate reading one word
at a time. ClearRead does none of those jobs. Its product is the missing step
after recognition: immediate, transient, personalized reflow for people who
cannot comfortably read the original presentation.

## Why it endures

This is not a novelty overlay. The same need recurs whenever text appears in a
remote desktop, scan, screenshot, video, canvas, image-only PDF, or application
that ignores the user's preferred typography. ClearRead makes that material
usable without asking the source application to cooperate.

The durable extension points are presentation presets, better layout
reconstruction, additional local OCR engines, accessibility-tree extraction,
and optional speech output. The 0.1 release keeps those out until the central
capture-to-reading path is trustworthy.

## Twenty-second demonstration

1. Open a screenshot containing dense, small text.
2. Invoke ClearRead and choose **Read active window** from the keyboard.
3. Enlarge the result, narrow the column, switch to Sepia, open the spacing,
   and enable one-line focus.
4. Navigate and copy without touching the pointer.
5. Close, then show that no capture file, OCR history, or worker remains.

That demonstrates the value proposition and the privacy boundary in one pass.

## Honest claim

“Turn visible text into adjustable text.”

ClearRead does not promise perfect recognition, semantic document structure,
screen-reader replacement, handwriting support, or access to protected pixels.
