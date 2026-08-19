# Release checklist

Unchecked boxes are work, not decoration. Do not publish a release or submit
to the marketplace until every applicable item has evidence.

## Repository

- [ ] Public repository contains exactly one plugin and one root manifest.
- [ ] Manifest ID is permanent, lowercase, unique, and matches IPC/docs.
- [ ] Version matches the changelog and release tag.
- [ ] README contains install, use, limits, dependencies, and removal.
- [ ] License and preview ownership are confirmed.
- [ ] Release commit is frozen while marketplace review runs.

## Automated checks

- [ ] `bash scripts/validate.sh` passes on Python 3.12 and current Arch Python.
- [ ] `qmllint` passes with current Omarchy shell imports.
- [ ] `omarchy plugin validate .` passes on current Omarchy.
- [ ] Marketplace static security baseline is clear at the exact commit.
- [ ] CI uses immutable action revisions and has least-privilege permissions.

## Privacy and lifecycle

- [ ] Opening and demo mode start no pixel capture, clipboard read, or OCR
      recognition.
- [ ] Region and active-window PNG bytes never touch disk.
- [ ] Recognized and clipboard text are absent from logs and settings.
- [ ] Clipboard is unchanged before explicit Copy.
- [ ] Cancel, Close, disable, reload, and shell exit reap every capture and OCR
      child.
- [ ] No listener, network request, analytics, capture daemon, or autostart
      exists.
- [ ] After explicit Copy, the standard `wl-copy` selection provider lifetime
      is understood and ends on clipboard replacement or manager takeover.
- [ ] Settings contain only allowlisted presentation preferences.

## Functional acceptance

- [ ] Active-window flow works end to end with keyboard only.
- [ ] Region selection, cancellation, no-text, timeout, and dependency errors
      are distinct and actionable.
- [ ] Generated OCR fixture produces the expected normalized text.
- [ ] Every presentation control changes only presentation and survives reopen.
- [ ] Explicit Copy works from both keyboard and pointer without placing text
      in an argument or persistent history.
- [ ] Demo, capture, copy, close, reopen, disable, and hot reload are repeatable.

## Visual and accessibility acceptance

- [ ] Tab and Shift+Tab order match the visual order; focus is always visible.
- [ ] Escape leaves every state without a focus trap.
- [ ] Pointer targets are at least 44×44 logical pixels.
- [ ] Four palettes meet the documented contrast targets.
- [ ] Maximum size and spacing fit 1280×720 without overlap or horizontal text
      scrolling.
- [ ] 1-, 3-, and 5-line focus masks stay inside the viewport.
- [ ] Reader placement is correct on two displays and fractional scale.
- [ ] Dynamic text is PlainText and Unicode/RTL samples do not crash or fetch.
- [ ] Orca behavior is observed and documented without claiming conformance.

## Submission

- [ ] Preview uses generated text and contains no private screen content.
- [ ] Fresh install, update, and removal are tested from the public URL.
- [ ] Marketplace issue body matches the current submission template.
- [ ] Repository owner personally confirms every marketplace checklist item.
