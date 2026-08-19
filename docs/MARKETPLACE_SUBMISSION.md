# Marketplace submission draft

Do not open this issue until the repository is public, the preview is reviewed,
the release checks pass, and the owner explicitly confirms every checklist
statement. Real Omarchy acceptance is not yet recorded, so the boxes remain
unchecked.

**Title**

```text
[Plugin]: ClearRead
```

**Body**

```markdown
### Repository URL

https://github.com/josephbriones/omarchy-clearread

### Category

Desktop

### Tags

hyprland, quickshell

### Suggest a missing tag

accessibility

### Maintainer notes

ClearRead turns an explicitly selected active window, screen region, or existing clipboard text into a transient, adjustable reading surface. Pixel captures pass from grim to local Tesseract in memory; the plugin creates no screenshot, OCR history, network request, account, analytics record, or automatic clipboard write. All capture paths require an explicit action. Only allowlisted presentation preferences persist. The plugin uses the capture, OCR, clipboard, Hyprland, Python, and process-ownership tools included with current Omarchy; it never installs packages, downloads language data, edits global configuration, or starts a capture daemon. OCR output is bounded and rendered only as plain text. ClearRead is an accessibility presentation layer, not an OCR archive, screen reader, or promise of exact recognition.

### Submission checklist

- [ ] The repository is public and contains installation and removal instructions.
- [ ] I have documented the plugin license and any external dependencies.
- [ ] I confirm that I own or have permission to submit this plugin and its preview assets.
- [ ] The plugin does not overwrite user configuration without explicit consent.
- [ ] I understand that approval is for listing and is not a security review.
```

After the owner personally confirms these statements, change all five boxes to
`[x]`, show the final title and body to the owner, obtain explicit approval,
and create one issue in the marketplace repository.

The category and tags must be rechecked against the marketplace's controlled
vocabulary at submission time. `accessibility` is intentionally proposed as a
missing ecosystem tag.
