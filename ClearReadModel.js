// Pure boundary helpers shared by QML and the Node test suite. Keep this file
// free of QML globals: helper output and persisted settings are untrusted input.

var MAX_DOCUMENT_LENGTH = 120000
var MAX_PROTOCOL_LIST = 32
var MAX_REQUEST_ID = 2147483647
var STATUS_STATES = ["selecting", "capturing", "recognizing"]
var MODES = ["window", "region", "clipboard"]
var FONT_FAMILIES = ["system", "serif", "mono"]
var FONT_WEIGHTS = ["regular", "bold"]
var LINE_HEIGHTS = [1.25, 1.5, 2]
var LETTER_SPACINGS = [0, 1, 2]
var WORD_SPACINGS = [0, 4, 8]
var COLUMN_WIDTHS = ["narrow", "medium", "wide"]
var PALETTES = ["paper", "sepia", "dark", "contrast"]
var FOCUS_LINES = [0, 1, 3, 5]

var DEFAULT_SETTINGS = {
  version: 1,
  fontSize: 28,
  fontFamily: "system",
  fontWeight: "regular",
  lineHeight: 1.5,
  letterSpacing: 0,
  wordSpacing: 4,
  columnWidth: "medium",
  palette: "paper",
  focusLines: 0
}

var DEMO_DOCUMENT = [
  "ClearRead turns text already visible on your screen into a calm, readable page.",
  "This preview is synthetic. It does not take a screenshot, inspect the clipboard, start OCR, or send anything over the network. When you choose a real capture, ClearRead processes it locally and keeps the result only for this open reader.",
  "Use the presentation controls to change typeface, size, weight, spacing, column width, colour palette, and line focus. The text reflows as the page changes, so magnification does not force horizontal reading.",
  "Close the reader when you are finished. The captured words disappear; only your presentation preferences remain."
].join("\n\n")

function clamp(value, minimum, maximum) {
  var number = Number(value)
  if (!isFinite(number)) number = minimum
  return Math.max(minimum, Math.min(maximum, number))
}

function plainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value)
}

function parseJson(raw) {
  if (plainObject(raw)) return raw
  if (typeof raw !== "string" || raw.trim() === "") return {}
  try {
    var parsed = JSON.parse(raw)
    return plainObject(parsed) ? parsed : {}
  } catch (error) {
    return {}
  }
}

function codePointLength(text) {
  var count = 0
  var index = 0
  while (index < text.length) {
    var first = text.charCodeAt(index++)
    if (first >= 0xd800 && first <= 0xdbff && index < text.length) {
      var second = text.charCodeAt(index)
      if (second >= 0xdc00 && second <= 0xdfff) index += 1
    }
    count += 1
  }
  return count
}

function sliceCodePoints(text, limit) {
  var count = 0
  var index = 0
  while (index < text.length && count < limit) {
    var first = text.charCodeAt(index++)
    if (first >= 0xd800 && first <= 0xdbff && index < text.length) {
      var second = text.charCodeAt(index)
      if (second >= 0xdc00 && second <= 0xdfff) index += 1
    }
    count += 1
  }
  return text.slice(0, index)
}

function ellipsize(text, limit, trimEnd) {
  if (codePointLength(text) <= limit) return text
  if (limit <= 0) return ""
  if (limit === 1) return "…"
  var prefix = sliceCodePoints(text, limit - 1)
  if (trimEnd) prefix = prefix.replace(/\s+$/g, "")
  return prefix + "…"
}

function stripUnsafeFormatControls(text) {
  return text.replace(/[\u061c\u200b\u200e\u200f\u202a-\u202e\u2060-\u2064\u2066-\u206f\ufeff]/g, "")
}

function cleanLine(value, maximum) {
  var limit = maximum === undefined ? 600 : Math.max(0, Number(maximum) || 0)
  var text = String(value === undefined || value === null ? "" : value)
    .replace(/[\u0000-\u001f\u007f-\u009f]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
  return ellipsize(stripUnsafeFormatControls(text), limit, false)
}

function cleanDocument(value, maximum) {
  var limit = maximum === undefined ? MAX_DOCUMENT_LENGTH : Math.max(0, Number(maximum) || 0)
  if (typeof value !== "string") return ""
  var text = value
    .replace(/\r\n?/g, "\n")
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f]/g, "")
    .replace(/\t/g, "    ")
    .split("\n")
    .map(function(line) { return line.replace(/[ \u00a0]+$/g, "") })
    .join("\n")
    .replace(/\n[ \u00a0]+\n/g, "\n\n")
    .replace(/\n{4,}/g, "\n\n\n")
    .trim()
  return ellipsize(stripUnsafeFormatControls(text), limit, true)
}

function stringList(value, maximumItems, maximumLength) {
  if (!Array.isArray(value)) return []
  var cap = Math.max(0, Number(maximumItems) || 0)
  var result = []
  for (var index = 0; index < value.length && result.length < cap; index++) {
    if (typeof value[index] !== "string") continue
    var item = cleanLine(value[index], maximumLength)
    if (item !== "") result.push(item)
  }
  return result
}

function choice(value, choices, fallback) {
  return choices.indexOf(value) === -1 ? fallback : value
}

function numericChoice(value, choices, fallback) {
  if (typeof value !== "number" || !isFinite(value)) return fallback
  return choices.indexOf(value) === -1 ? fallback : value
}

function normalizeLanguage(value) {
  if (typeof value !== "string") return "eng"
  var language = value.trim().toLowerCase()
  return /^[a-z0-9_]+(?:\+[a-z0-9_]+)*$/.test(language) && language.length <= 120
    ? language
    : "eng"
}

function modeKey(value) {
  if (typeof value !== "string") return ""
  var mode = value.toLowerCase()
  return MODES.indexOf(mode) === -1 ? "" : mode
}

function normalizeCapabilities(value) {
  var source = plainObject(value) ? value : {}
  return {
    window: source.window === true,
    region: source.region === true,
    clipboard: source.clipboard === true,
    copy: source.copy === true
  }
}

function validCapabilities(value) {
  return plainObject(value)
    && typeof value.window === "boolean"
    && typeof value.region === "boolean"
    && typeof value.clipboard === "boolean"
    && typeof value.copy === "boolean"
}

function hasOnlyKeys(value, keys) {
  return Object.keys(value).every(function(key) { return keys.indexOf(key) !== -1 })
}

function parsePayload(raw, fallbackLanguage) {
  var payload = parseJson(raw)
  return {
    // Only the synthetic demo may open directly into a document. There is no
    // capture/autostart payload: real screen access always begins in the UI.
    demo: typeof payload.demo === "boolean" ? payload.demo : false,
    language: typeof payload.language === "string"
      ? normalizeLanguage(payload.language)
      : normalizeLanguage(fallbackLanguage)
  }
}

function normalizeSettings(raw) {
  var settings = parseJson(raw)
  return {
    version: 1,
    fontSize: Math.round(clamp(settings.fontSize === undefined ? DEFAULT_SETTINGS.fontSize : settings.fontSize, 18, 72)),
    fontFamily: choice(settings.fontFamily, FONT_FAMILIES, DEFAULT_SETTINGS.fontFamily),
    fontWeight: choice(settings.fontWeight, FONT_WEIGHTS, DEFAULT_SETTINGS.fontWeight),
    lineHeight: numericChoice(settings.lineHeight, LINE_HEIGHTS, DEFAULT_SETTINGS.lineHeight),
    letterSpacing: numericChoice(settings.letterSpacing, LETTER_SPACINGS, DEFAULT_SETTINGS.letterSpacing),
    wordSpacing: numericChoice(settings.wordSpacing, WORD_SPACINGS, DEFAULT_SETTINGS.wordSpacing),
    columnWidth: choice(settings.columnWidth, COLUMN_WIDTHS, DEFAULT_SETTINGS.columnWidth),
    palette: choice(settings.palette, PALETTES, DEFAULT_SETTINGS.palette),
    focusLines: numericChoice(settings.focusLines, FOCUS_LINES, DEFAULT_SETTINGS.focusLines)
  }
}

function settingsJson(settings) {
  return JSON.stringify(normalizeSettings(settings), null, 2) + "\n"
}

function fontFamilyName(value, systemFamily) {
  var family = choice(value, FONT_FAMILIES, DEFAULT_SETTINGS.fontFamily)
  if (family === "serif") return "serif"
  if (family === "mono") return "monospace"
  return cleanLine(systemFamily, 160) || "sans-serif"
}

function columnPixels(value, available) {
  var key = choice(value, COLUMN_WIDTHS, DEFAULT_SETTINGS.columnWidth)
  var requested = key === "narrow" ? 640 : key === "wide" ? 1040 : 820
  var maximum = Math.max(280, Number(available) || requested)
  return Math.min(requested, maximum)
}

function palette(value) {
  var key = choice(value, PALETTES, DEFAULT_SETTINGS.palette)
  if (key === "sepia") return {
    key: key, background: "#d5c3a2", surface: "#f2e3c6", text: "#2d251d",
    muted: "#5d4e3c", accent: "#8a4b27", border: "#bda987", focus: "#1f1a14"
  }
  if (key === "dark") return {
    key: key, background: "#111318", surface: "#1c2028", text: "#f1f3f5",
    muted: "#a7adb8", accent: "#8db8ff", border: "#3b4351", focus: "#000000"
  }
  if (key === "contrast") return {
    key: key, background: "#000000", surface: "#000000", text: "#ffffff",
    muted: "#ffffff", accent: "#ffe600", border: "#ffffff", focus: "#000000"
  }
  return {
    key: "paper", background: "#d9dde2", surface: "#fbfbf8", text: "#20242a",
    muted: "#59616b", accent: "#285ea8", border: "#aeb5bf", focus: "#11151a"
  }
}

function eventBase(type) {
  return { valid: true, type: type }
}

function requestId(value) {
  return typeof value === "number" && isFinite(value)
    && Math.floor(value) === value && value > 0 && value <= MAX_REQUEST_ID
    ? value
    : null
}

function parseEvent(raw) {
  var data
  if (plainObject(raw)) data = raw
  else {
    if (typeof raw !== "string" || raw.trim() === "") return { valid: false, type: "invalid" }
    try { data = JSON.parse(raw) }
    catch (error) { return { valid: false, type: "invalid" } }
  }
  if (!plainObject(data) || typeof data.type !== "string") return { valid: false, type: "invalid" }

  var type = data.type.toLowerCase()
  var eventRequestId = requestId(data.requestId)
  if (type === "doctor") {
    if (eventRequestId === null || typeof data.ready !== "boolean"
        || !Array.isArray(data.missing)
        || !Array.isArray(data.issues)
        || !validCapabilities(data.capabilities))
      return { valid: false, type: "doctor" }
    if (!hasOnlyKeys(data, ["type", "requestId", "ready", "capabilities", "missing", "issues"]))
      return { valid: false, type: "doctor" }
    var capabilities = normalizeCapabilities(data.capabilities)
    if (data.ready !== (capabilities.window || capabilities.region || capabilities.clipboard))
      return { valid: false, type: "doctor" }
    var doctor = eventBase("doctor")
    doctor.requestId = eventRequestId
    doctor.ready = data.ready
    doctor.missing = stringList(data.missing, MAX_PROTOCOL_LIST, 120)
    doctor.issues = stringList(data.issues, MAX_PROTOCOL_LIST, 400)
    doctor.capabilities = capabilities
    return doctor
  }

  if (type === "status") {
    if (eventRequestId === null || typeof data.state !== "string"
        || STATUS_STATES.indexOf(data.state.toLowerCase()) === -1
        || modeKey(data.mode) === ""
        || (data.monitor !== undefined && typeof data.monitor !== "string")
        || !hasOnlyKeys(data, ["type", "requestId", "state", "mode", "monitor"]))
      return { valid: false, type: "status" }
    var statusState = data.state.toLowerCase()
    var statusMode = modeKey(data.mode)
    if ((statusState === "selecting" && statusMode !== "region")
        || (statusState === "recognizing" && statusMode === "clipboard"))
      return { valid: false, type: "status" }
    var status = eventBase("status")
    status.requestId = eventRequestId
    status.state = statusState
    status.mode = statusMode
    status.monitor = typeof data.monitor === "string" ? cleanLine(data.monitor, 160) : ""
    return status
  }

  if (type === "result") {
    if (eventRequestId === null || typeof data.text !== "string"
        || (data.monitor !== undefined && typeof data.monitor !== "string")
        || !hasOnlyKeys(data, ["type", "requestId", "mode", "text", "monitor"]))
      return { valid: false, type: "result" }
    var resultMode = modeKey(data.mode)
    if (resultMode === "") return { valid: false, type: "result" }
    var resultText = cleanDocument(data.text)
    if (resultText === "") return { valid: false, type: "result" }
    var result = eventBase("result")
    result.requestId = eventRequestId
    result.mode = resultMode
    result.text = resultText
    result.monitor = typeof data.monitor === "string" ? cleanLine(data.monitor, 160) : ""
    return result
  }

  if (type === "error") {
    if (eventRequestId === null || typeof data.message !== "string"
        || typeof data.code !== "string"
        || !hasOnlyKeys(data, ["type", "requestId", "code", "message"]))
      return { valid: false, type: "error" }
    var failure = eventBase("error")
    failure.requestId = eventRequestId
    failure.code = cleanLine(data.code, 80)
    failure.message = cleanLine(data.message, 600) || "ClearRead could not read that content."
    return failure
  }

  if (type === "cancelled") {
    if (eventRequestId === null || modeKey(data.mode) === ""
        || !hasOnlyKeys(data, ["type", "requestId", "mode"]))
      return { valid: false, type: "cancelled" }
    var cancelled = eventBase("cancelled")
    cancelled.requestId = eventRequestId
    cancelled.mode = modeKey(data.mode)
    return cancelled
  }

  return { valid: false, type: cleanLine(type, 80) || "invalid" }
}

function safeProcessError(diagnostic, exitCode, fallback) {
  var message = cleanLine(diagnostic, 600)
  if (message !== "") return message
  if (fallback) return cleanLine(fallback, 600)
  return "ClearRead helper exited with code " + String(exitCode === undefined ? "?" : exitCode) + "."
}

function modeLabel(mode) {
  var key = modeKey(mode)
  if (key === "window") return "active window"
  if (key === "region") return "screen area"
  if (key === "clipboard") return "clipboard"
  return "content"
}

function formatCharacterCount(value) {
  var count = Math.max(0, Math.floor(Number(value) || 0))
  if (count < 1000) return count + (count === 1 ? " character" : " characters")
  return (count / 1000).toFixed(count < 10000 ? 1 : 0) + "k characters"
}

if (typeof module !== "undefined") {
  module.exports = {
    MAX_DOCUMENT_LENGTH: MAX_DOCUMENT_LENGTH,
    MAX_REQUEST_ID: MAX_REQUEST_ID,
    DEFAULT_SETTINGS: DEFAULT_SETTINGS,
    DEMO_DOCUMENT: DEMO_DOCUMENT,
    clamp: clamp,
    codePointLength: codePointLength,
    ellipsize: ellipsize,
    cleanLine: cleanLine,
    cleanDocument: cleanDocument,
    parsePayload: parsePayload,
    normalizeLanguage: normalizeLanguage,
    modeKey: modeKey,
    requestId: requestId,
    normalizeCapabilities: normalizeCapabilities,
    normalizeSettings: normalizeSettings,
    settingsJson: settingsJson,
    fontFamilyName: fontFamilyName,
    columnPixels: columnPixels,
    palette: palette,
    parseEvent: parseEvent,
    safeProcessError: safeProcessError,
    modeLabel: modeLabel,
    formatCharacterCount: formatCharacterCount
  }
}
