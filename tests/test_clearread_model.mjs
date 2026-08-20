import assert from "node:assert/strict"
import { createRequire } from "node:module"

const require = createRequire(import.meta.url)
const model = require("../ClearReadModel.js")

let checks = 0
function test(name, body) {
  try {
    body()
    checks += 1
    process.stdout.write(`ok ${checks} - ${name}\n`)
  } catch (error) {
    process.stderr.write(`not ok ${checks + 1} - ${name}\n`)
    throw error
  }
}

test("payload parsing can open only the safe synthetic demo", () => {
  assert.deepEqual(model.parsePayload("not json"), { demo: false, language: "eng" })
  assert.deepEqual(model.parsePayload(JSON.stringify({
    demo: true,
    autostart: true,
    capture: true,
    mode: "region",
    language: "ENG+SPA"
  })), { demo: true, language: "eng+spa" })
  assert.deepEqual(model.parsePayload('{"language":"--help"}'), { demo: false, language: "eng" })
  assert.deepEqual(model.parsePayload("{}", "eng+spa"), { demo: false, language: "eng+spa" })
  assert.deepEqual(model.parsePayload('{"language":"deu"}', "eng+spa"), { demo: false, language: "deu" })
})

test("language values stay inside the Tesseract identifier grammar", () => {
  assert.equal(model.normalizeLanguage("eng"), "eng")
  assert.equal(model.normalizeLanguage("deu_frak+eng"), "deu_frak+eng")
  assert.equal(model.normalizeLanguage("../../secret"), "eng")
  assert.equal(model.normalizeLanguage("eng -c debug_file=x"), "eng")
  assert.equal(model.normalizeLanguage("a".repeat(121)), "eng")
})

test("document cleaning preserves reflow and strips unsafe controls", () => {
  assert.equal(
    model.cleanDocument("  First line\r\ncontinues\u0000\n\n\n\nSecond paragraph.  \n"),
    "First line\ncontinues\n\n\nSecond paragraph."
  )
  assert.equal(model.cleanDocument("A\tB"), "A    B")
  assert.equal(model.cleanDocument("A\u202eB\u200c\u200d"), "AB\u200c\u200d")
  assert.equal(model.cleanDocument({ unsafe: true }), "")
  assert.equal(model.cleanDocument("abcdef", 4), "abc…")
  assert.equal(model.cleanDocument("A😀BCD", 4), "A😀B…")
  assert.equal(model.cleanDocument("A😀B", 3), "A😀B")
  assert.equal(model.codePointLength("A😀B"), 3)
})

test("single-line diagnostics cannot inject controls or grow without bound", () => {
  assert.equal(model.cleanLine("  one\u0000\n two  "), "one two")
  assert.equal(model.cleanLine("safe\u202evalue\u200c"), "safevalue\u200c")
  assert.equal(model.cleanLine("abcdef", 4), "abc…")
  assert.equal(model.cleanLine("abc", 0), "")
  assert.equal(model.cleanLine(null), "")
})

test("presentation settings default safely and clamp only text size", () => {
  assert.deepEqual(model.normalizeSettings("{"), model.DEFAULT_SETTINGS)
  const settings = model.normalizeSettings({
    version: 99,
    fontSize: 500,
    fontFamily: "comic",
    fontWeight: "heavy",
    lineHeight: 1.7,
    letterSpacing: 50,
    wordSpacing: -2,
    columnWidth: "ocean",
    palette: "invisible",
    focusLines: 99,
    content: "must not persist"
  })
  assert.deepEqual(settings, {
    ...model.DEFAULT_SETTINGS,
    fontSize: 72
  })
  assert.equal(Object.hasOwn(settings, "content"), false)
})

test("all supported presentation choices survive a settings round trip", () => {
  const wanted = {
    fontSize: 18,
    fontFamily: "mono",
    fontWeight: "bold",
    lineHeight: 2,
    letterSpacing: 2,
    wordSpacing: 8,
    columnWidth: "wide",
    palette: "contrast",
    focusLines: 5
  }
  const parsed = JSON.parse(model.settingsJson(wanted))
  assert.deepEqual(parsed, { version: 1, ...wanted })
  assert.equal(model.settingsJson(wanted).endsWith("\n"), true)
})

test("font and column helpers resolve deterministic local values", () => {
  assert.equal(model.fontFamilyName("system", "Berkeley Mono"), "Berkeley Mono")
  assert.equal(model.fontFamilyName("serif", "Ignored"), "serif")
  assert.equal(model.fontFamilyName("mono", "Ignored"), "monospace")
  assert.equal(model.columnPixels("narrow", 1200), 640)
  assert.equal(model.columnPixels("medium", 700), 700)
  assert.equal(model.columnPixels("wide", 200), 280)
})

test("every palette has an opaque readable surface contract", () => {
  function luminance(hex) {
    const channels = [1, 3, 5].map(index => Number.parseInt(hex.slice(index, index + 2), 16) / 255)
      .map(value => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
  }
  function contrast(left, right) {
    const values = [luminance(left), luminance(right)].sort((a, b) => b - a)
    return (values[0] + 0.05) / (values[1] + 0.05)
  }
  for (const key of ["paper", "sepia", "dark", "contrast"]) {
    const colours = model.palette(key)
    assert.equal(colours.key, key)
    for (const field of ["background", "surface", "text", "muted", "accent", "border", "focus"])
      assert.match(colours[field], /^#[0-9a-f]{6}$/i)
    assert.notEqual(colours.surface, colours.text)
    assert.ok(contrast(colours.text, colours.surface) >= 4.5)
    assert.ok(contrast(colours.muted, colours.background) >= 4.5)
  }
  assert.equal(model.palette("unknown").key, "paper")
})

test("doctor events normalize the exact backend boundary", () => {
  const doctor = model.parseEvent({
    type: "doctor",
    requestId: 7,
    ready: true,
    capabilities: { window: true, region: true, clipboard: true, copy: true },
    missing: ["", "grim", 5],
    issues: ["  local only  "]
  })
  assert.equal(doctor.valid, true)
  assert.equal(doctor.requestId, 7)
  assert.equal(doctor.ready, true)
  assert.deepEqual(doctor.capabilities, { window: true, region: true, clipboard: true, copy: true })
  assert.deepEqual(doctor.missing, ["grim"])
  assert.deepEqual(doctor.issues, ["local only"])
  assert.deepEqual(model.parseEvent({ type: "doctor", ready: "yes" }), { valid: false, type: "doctor" })
  assert.deepEqual(model.parseEvent({ type: "doctor", requestId: 7, ready: false, capabilities: [] }), { valid: false, type: "doctor" })
  assert.deepEqual(model.parseEvent({ type: "doctor", requestId: 7, ready: true }), { valid: false, type: "doctor" })
  assert.deepEqual(model.parseEvent({
    type: "doctor", requestId: 7, ready: true,
    capabilities: { window: true, region: true, clipboard: true }
  }), { valid: false, type: "doctor" })
  assert.deepEqual(model.parseEvent({
    type: "doctor", requestId: 7, ready: true,
    capabilities: { window: true, region: false, clipboard: false, copy: true },
    missing: [], issues: [], surprise: true
  }), { valid: false, type: "doctor" })
  assert.deepEqual(model.parseEvent({
    type: "doctor", requestId: 7, ready: true,
    capabilities: { window: false, region: false, clipboard: false, copy: true }
  }), { valid: false, type: "doctor" })
})

test("doctor capabilities expose only canonical boolean actions", () => {
  assert.deepEqual(model.normalizeCapabilities({
    window: true,
    region: "yes",
    clipboard: false,
    copy: true,
    remote: true
  }), { window: true, region: false, clipboard: false, copy: true })
  assert.deepEqual(model.normalizeCapabilities(undefined), {
    window: false, region: false, clipboard: false, copy: false
  })
})

test("capture lifecycle accepts only known status states and modes", () => {
  assert.deepEqual(model.parseEvent('{"type":"status","requestId":8,"state":"selecting","mode":"region"}'), {
    valid: true,
    type: "status",
    requestId: 8,
    state: "selecting",
    mode: "region",
    monitor: ""
  })
  assert.equal(model.parseEvent({ type: "status", requestId: 8, state: "capturing", mode: "window" }).valid, true)
  assert.equal(model.parseEvent({ type: "status", requestId: 8, state: "capturing", mode: "clipboard" }).valid, true)
  assert.equal(model.parseEvent({ type: "status", requestId: 8, state: "recognizing", mode: "region", monitor: "DP-2" }).monitor, "DP-2")
  assert.deepEqual(model.parseEvent({ type: "status", requestId: 8, state: "uploading", mode: "region" }), { valid: false, type: "status" })
  assert.deepEqual(model.parseEvent({ type: "status", requestId: 8, state: "capturing", mode: "desktop" }), { valid: false, type: "status" })
  assert.deepEqual(model.parseEvent({ type: "status", requestId: 8, state: "capturing" }), { valid: false, type: "status" })
  assert.deepEqual(model.parseEvent({ type: "status", requestId: 8, state: "selecting", mode: "window" }), { valid: false, type: "status" })
  assert.deepEqual(model.parseEvent({ type: "status", requestId: 8, state: "recognizing", mode: "clipboard" }), { valid: false, type: "status" })
  assert.deepEqual(model.parseEvent({ type: "status", requestId: 8, state: "capturing", mode: "window", monitor: 9 }), { valid: false, type: "status" })
})

test("result events bound text and retain only display-safe metadata", () => {
  const result = model.parseEvent({
    type: "result",
    requestId: 9,
    mode: "region",
    text: "Heading\n\nA readable paragraph.",
    monitor: "eDP-1"
  })
  assert.equal(result.valid, true)
  assert.equal(result.requestId, 9)
  assert.equal(result.mode, "region")
  assert.equal(result.text, "Heading\n\nA readable paragraph.")
  assert.equal(result.monitor, "eDP-1")
  assert.deepEqual(model.parseEvent({ type: "result", requestId: 9, mode: "region", text: "  " }), { valid: false, type: "result" })
  assert.deepEqual(model.parseEvent({ type: "result", requestId: 9, mode: "region", text: ["unsafe"] }), { valid: false, type: "result" })
  assert.deepEqual(model.parseEvent({ type: "result", requestId: 9, mode: "network", text: "text" }), { valid: false, type: "result" })
  assert.deepEqual(model.parseEvent({ type: "result", requestId: 9, source: "region", text: "text" }), { valid: false, type: "result" })
  assert.deepEqual(model.parseEvent({ type: "result", requestId: 9, mode: "region", source: "window", text: "text" }), { valid: false, type: "result" })
})

test("oversized result text is deterministically capped", () => {
  const result = model.parseEvent({ type: "result", requestId: 10, mode: "window", text: "x".repeat(model.MAX_DOCUMENT_LENGTH + 50) })
  assert.equal(result.valid, true)
  assert.equal(result.text.length, model.MAX_DOCUMENT_LENGTH)
  assert.equal(result.text.endsWith("…"), true)
})

test("astral text uses the same Unicode character units as the backend", () => {
  const result = model.parseEvent({
    type: "result",
    requestId: 10,
    mode: "window",
    text: "😀".repeat(model.MAX_DOCUMENT_LENGTH + 5)
  })
  assert.equal(result.valid, true)
  assert.equal(model.codePointLength(result.text), model.MAX_DOCUMENT_LENGTH)
  assert.equal(result.text.endsWith("…"), true)
})

test("errors and cancellation are bounded terminal events", () => {
  assert.deepEqual(model.parseEvent({ type: "cancelled", requestId: 11, mode: "region" }), {
    valid: true,
    type: "cancelled",
    requestId: 11,
    mode: "region"
  })
  assert.deepEqual(model.parseEvent({ type: "error", requestId: 11, code: "no_text", message: " Nothing\nreadable " }), {
    valid: true,
    type: "error",
    requestId: 11,
    code: "no_text",
    message: "Nothing readable"
  })
  assert.deepEqual(model.parseEvent({ type: "error", requestId: 11, code: 500, message: "failed" }), { valid: false, type: "error" })
  assert.deepEqual(model.parseEvent({ type: "error", requestId: 11, message: "failed" }), { valid: false, type: "error" })
  assert.deepEqual(model.parseEvent({ type: "cancelled", requestId: 11, mode: "remote" }), { valid: false, type: "cancelled" })
  assert.deepEqual(model.parseEvent({ type: "cancelled", requestId: 11 }), { valid: false, type: "cancelled" })
})

test("request IDs are positive bounded protocol integers", () => {
  assert.equal(model.requestId(1), 1)
  assert.equal(model.requestId(model.MAX_REQUEST_ID), model.MAX_REQUEST_ID)
  for (const invalid of [undefined, null, 0, -1, 1.5, "1", Infinity, model.MAX_REQUEST_ID + 1])
    assert.equal(model.requestId(invalid), null)
  assert.deepEqual(model.parseEvent({ type: "status", state: "capturing", mode: "region" }), { valid: false, type: "status" })
})

test("malformed and unknown protocol messages never become state", () => {
  assert.deepEqual(model.parseEvent(""), { valid: false, type: "invalid" })
  assert.deepEqual(model.parseEvent("{"), { valid: false, type: "invalid" })
  assert.deepEqual(model.parseEvent("[]"), { valid: false, type: "invalid" })
  assert.deepEqual(model.parseEvent({}), { valid: false, type: "invalid" })
  assert.deepEqual(model.parseEvent({ type: "surprise", text: "payload" }), { valid: false, type: "surprise" })
})

test("labels and fallback errors reveal no document content", () => {
  assert.equal(model.modeLabel("window"), "active window")
  assert.equal(model.modeLabel("region"), "screen area")
  assert.equal(model.modeLabel("clipboard"), "clipboard")
  assert.equal(model.safeProcessError(" grim failed\n", 1), "grim failed")
  assert.equal(model.safeProcessError("", 9), "ClearRead helper exited with code 9.")
  assert.equal(model.formatCharacterCount(1), "1 character")
  assert.equal(model.formatCharacterCount(999), "999 characters")
  assert.equal(model.formatCharacterCount(1250), "1.3k characters")
})

test("the demo is substantial, reflowable, and contains no remote content", () => {
  assert.ok(model.DEMO_DOCUMENT.length > 400)
  assert.ok(model.DEMO_DOCUMENT.includes("\n\n"))
  assert.equal(/https?:\/\//.test(model.DEMO_DOCUMENT), false)
})

process.stdout.write(`1..${checks}\n`)
