import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Hyprland
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import qs.Ui
import "ClearReadModel.js" as ClearReadModel

Item {
  id: root

  // Quattro assigns these after Loader construction, so they cannot be
  // required properties on a plugin root.
  property string omarchyPath: Quickshell.env("OMARCHY_PATH")
  property var shell: null
  property var manifest: null

  property bool opened: false
  property bool surfaceVisible: false
  property bool demoMode: false
  property string phase: "idle"
  property string language: "eng"
  property string activeMode: ""
  property string captureMonitor: ""
  property string targetMonitor: ""
  property string documentText: ""
  property string copyPayload: ""
  property int documentCharacters: 0
  property string errorMessage: ""
  property string doctorDiagnostic: ""
  property string captureDiagnostic: ""
  property string copyDiagnostic: ""
  property string transientMessage: ""
  property bool sourceHeld: false
  property bool sourceViewVisible: false
  property var sourceDescriptor: null
  property int sourceZoom: 0

  property bool doctorReady: false
  property string doctorMessage: ""
  property var doctorMissing: []
  property var doctorIssues: []
  property var doctorCapabilities: ({ window: false, region: false, clipboard: false, copy: false })
  property bool doctorStartPending: false
  property bool doctorExpectedStop: false
  property bool doctorTerminalSeen: false

  property bool captureStartPending: false
  property bool captureExpectedStop: false
  property bool captureTerminalSeen: false
  property bool copyStartPending: false
  property bool copyExpectedStop: false
  property bool pendingOpen: false
  property string pendingPayload: ""
  property int requestSerial: 0
  property int activeDoctorRequestId: 0
  property int activeCaptureRequestId: 0

  property int fontSize: 28
  property string fontFamily: "system"
  property string fontWeight: "regular"
  property real lineHeight: 1.5
  property real letterSpacing: 0
  property real wordSpacing: 4
  property string columnWidth: "medium"
  property string paletteName: "paper"
  property int focusLines: 0
  property bool settingsLoaded: false
  property bool settingsHydrating: false
  property bool settingsDirectoryReady: false
  property bool settingsDirectoryStartPending: false
  property bool settingsDirty: false

  // Every control meets the 44-by-44 logical-pixel target without replacing
  // Omarchy's native button behavior, focus ring, or theme tokens.
  component AccessButton: Button {
    readonly property real minimumTargetSize: Math.max(44, Style.space(44))
    verticalPadding: Math.max(Style.spacing.controlPaddingY, (minimumTargetSize - fontSize) / 2)
    horizontalPadding: Math.max(Style.spacing.controlPaddingX, (minimumTargetSize - fontSize) / 2)
  }

  readonly property string pluginId: manifest && manifest.id
    ? String(manifest.id)
    : "io.github.josephbriones.clearread"
  readonly property string sourceDir: manifest && manifest.__sourceDir ? String(manifest.__sourceDir) : ""
  readonly property string backendPath: sourceDir + "/bin/clearread"
  readonly property string shellProcessId: String(Quickshell.processId)
  readonly property string configHome: Quickshell.env("XDG_CONFIG_HOME") !== ""
    ? Quickshell.env("XDG_CONFIG_HOME")
    : (Quickshell.env("HOME") !== "" ? Quickshell.env("HOME") + "/.config" : "")
  readonly property string settingsDirectory: configHome === ""
    ? ""
    : configHome + "/io.github.josephbriones.clearread"
  readonly property string settingsPath: settingsDirectory === "" ? "" : settingsDirectory + "/settings.json"
  readonly property bool readerVisible: phase === "reading" && documentText !== ""
  readonly property bool clipboardCaptureActive: phase === "capturing" && activeMode === "clipboard"
  readonly property bool sourceAvailable: sourceHeld && !demoMode
    && (activeMode === "window" || activeMode === "region")
  readonly property string sourceUri: sourceDescriptor ? String(sourceDescriptor.uri) : ""
  readonly property int sourceWidth: sourceDescriptor ? Number(sourceDescriptor.width) : 0
  readonly property int sourceHeight: sourceDescriptor ? Number(sourceDescriptor.height) : 0
  readonly property var colours: ClearReadModel.palette(paletteName)
  readonly property string resolvedFontFamily: ClearReadModel.fontFamilyName(fontFamily, Style.font.family)
  readonly property real readerLineStep: Math.max(1, readerFontMetrics.lineSpacing * lineHeight)
  readonly property string setupDetails: {
    var parts = []
    if (errorMessage) parts.push(errorMessage)
    if (doctorMessage) parts.push(doctorMessage)
    if (doctorIssues && doctorIssues.length > 0) parts.push(doctorIssues.join("\n"))
    if (doctorMissing && doctorMissing.length > 0) parts.push("Missing: " + doctorMissing.join(", "))
    if (parts.length === 0) parts.push("ClearRead needs the local Omarchy capture and OCR tools.")
    return parts.join("\n")
  }
  readonly property string privacyStatus: {
    if (demoMode) return "Synthetic preview · no screen or clipboard access"
    if (sourceViewVisible) return "Temporary source view · released when you close or read another"
    if (phase === "selecting") return "Waiting for your selection"
    if (clipboardCaptureActive) return "Reading clipboard text · no screen capture or OCR"
    if (phase === "capturing") return "Capturing only what you requested"
    if (phase === "recognizing") return "Recognizing locally · nothing is uploaded"
    if (readerVisible && sourceHeld) return "Temporary local result and source · nothing is saved"
    if (readerVisible) return "Temporary local result · cleared when this reader closes"
    return "Nothing is being captured"
  }
  readonly property var readerScreen: {
    var screens = Quickshell.screens
    if (!screens || screens.length === 0) return null
    var wanted = targetMonitor
    if (wanted !== "") {
      for (var index = 0; index < screens.length; index++) {
        if (String(screens[index].name || "") === wanted) return screens[index]
      }
    }
    return screens[0]
  }

  function processesBusy() {
    return doctorProcess.running || (captureProcess.running && !sourceHeld) || copyProcess.running
      || doctorExpectedStop || captureExpectedStop || copyExpectedStop
  }

  function processesRunning() {
    return doctorProcess.running || captureProcess.running || copyProcess.running
      || settingsDirectoryProcess.running
  }

  function discardSource() {
    sourceViewVisible = false
    sourceHeld = false
    sourceDescriptor = null
    sourceZoom = 0
    sourceFlick.contentX = 0
    sourceFlick.contentY = 0
  }

  function releaseSource() {
    if (!sourceHeld) return false
    sourceViewVisible = false
    sourceHeld = false
    sourceDescriptor = null
    sourceZoom = 0
    sourceFlick.contentX = 0
    sourceFlick.contentY = 0
    if (!captureProcess.running) return false
    captureExpectedStop = true
    captureProcess.write("release\n")
    sourceReleaseTimer.restart()
    return true
  }

  function replaceSource(descriptor) {
    if (sourceHeld) releaseSource()
    sourceDescriptor = descriptor
    sourceHeld = descriptor !== null
    sourceViewVisible = false
    sourceZoom = 0
  }

  function showSource() {
    if (!sourceAvailable) return
    sourceViewVisible = true
    sourceZoom = 0
    sourceFlick.contentX = 0
    sourceFlick.contentY = 0
    Qt.callLater(function() { sourceBackButton.forceActiveFocus() })
  }

  function showText() {
    if (!sourceViewVisible) return
    sourceViewVisible = false
    Qt.callLater(function() { compareSourceButton.forceActiveFocus() })
  }

  function setSourceZoom(value) {
    var zoom = value === 2 || value === 4 ? value : 0
    var horizontalCenter = sourceFlick.contentWidth > 0
      ? (sourceFlick.contentX + sourceFlick.width / 2) / sourceFlick.contentWidth : 0.5
    var verticalCenter = sourceFlick.contentHeight > 0
      ? (sourceFlick.contentY + sourceFlick.height / 2) / sourceFlick.contentHeight : 0.5
    sourceZoom = zoom
    Qt.callLater(function() {
      sourceFlick.contentX = ClearReadModel.clamp(
        horizontalCenter * sourceFlick.contentWidth - sourceFlick.width / 2,
        0, Math.max(0, sourceFlick.contentWidth - sourceFlick.width))
      sourceFlick.contentY = ClearReadModel.clamp(
        verticalCenter * sourceFlick.contentHeight - sourceFlick.height / 2,
        0, Math.max(0, sourceFlick.contentHeight - sourceFlick.height))
    })
  }

  function adjustSourceZoom(direction) {
    var levels = [0, 2, 4]
    var index = levels.indexOf(sourceZoom)
    setSourceZoom(levels[ClearReadModel.clamp(index + direction, 0, levels.length - 1)])
  }

  function panSource(horizontal, vertical, accelerated) {
    var step = accelerated ? 192 : 48
    sourceFlick.contentX = ClearReadModel.clamp(sourceFlick.contentX + horizontal * step,
      0, Math.max(0, sourceFlick.contentWidth - sourceFlick.width))
    sourceFlick.contentY = ClearReadModel.clamp(sourceFlick.contentY + vertical * step,
      0, Math.max(0, sourceFlick.contentHeight - sourceFlick.height))
  }

  function modeAvailable(mode) {
    var key = ClearReadModel.modeKey(mode)
    return key !== "" && doctorCapabilities && doctorCapabilities[key] === true
  }

  function focusedMonitorName() {
    var monitor = Hyprland.focusedMonitor
    return monitor ? String(monitor.name || "") : ""
  }

  function nextRequestId() {
    requestSerial = requestSerial >= ClearReadModel.MAX_REQUEST_ID ? 1 : requestSerial + 1
    return requestSerial
  }

  function launchDoctor() {
    if (!opened || demoMode || doctorProcess.running || doctorStartPending) return
    activeDoctorRequestId = nextRequestId()
    doctorTerminalSeen = false
    doctorStartPending = true
    doctorProcess.running = true
  }

  function launchCapture() {
    if (!opened || activeMode === "" || captureProcess.running || captureStartPending) return
    activeCaptureRequestId = nextRequestId()
    captureTerminalSeen = false
    captureStartPending = true
    captureProcess.running = true
  }

  function beginOpen(payloadJson) {
    var options = ClearReadModel.parsePayload(payloadJson, Quickshell.env("OMARCHY_OCR_LANGS"))
    opened = true
    surfaceVisible = true
    demoMode = options.demo
    language = options.language
    activeMode = ""
    captureMonitor = ""
    targetMonitor = focusedMonitorName()
    documentText = ""
    copyPayload = ""
    documentCharacters = 0
    errorMessage = ""
    doctorDiagnostic = ""
    captureDiagnostic = ""
    copyDiagnostic = ""
    transientMessage = ""
    discardSource()
    doctorReady = false
    doctorMessage = ""
    doctorMissing = []
    doctorIssues = []
    doctorCapabilities = ({ window: false, region: false, clipboard: false, copy: false })
    doctorTerminalSeen = false
    captureTerminalSeen = false
    activeDoctorRequestId = 0
    activeCaptureRequestId = 0

    if (demoMode) {
      documentText = ClearReadModel.DEMO_DOCUMENT
      documentCharacters = ClearReadModel.codePointLength(documentText)
      phase = "reading"
      requestReaderFocus()
      return
    }

    // Opening performs a dependency check only. Pixel and clipboard access
    // remain behind the three explicit actions on the landing screen.
    phase = "checking"
    Qt.callLater(function() {
      root.launchDoctor()
    })
    requestReaderFocus()
  }

  function open(payloadJson) {
    var payload = typeof payloadJson === "string" ? payloadJson : ""
    if (pendingOpen) {
      pendingPayload = payload
      opened = true
      surfaceVisible = true
      phase = "checking"
      if (!processesBusy()) resumePendingOpen()
      return
    }
    if (opened && !pendingOpen) {
      if (surfaceVisible) requestReaderFocus()
      return
    }
    if (processesBusy()) {
      pendingOpen = true
      pendingPayload = payload
      opened = true
      surfaceVisible = true
      phase = "checking"
      return
    }
    beginOpen(payload)
  }

  function close() {
    captureDelay.stop()
    var sourceReleasePending = releaseSource()
    opened = false
    surfaceVisible = false
    pendingOpen = false
    pendingPayload = ""
    documentText = ""
    copyPayload = ""
    documentCharacters = 0
    activeMode = ""
    captureMonitor = ""
    targetMonitor = ""
    transientMessage = ""
    doctorDiagnostic = ""
    captureDiagnostic = ""
    copyDiagnostic = ""
    activeDoctorRequestId = 0
    activeCaptureRequestId = 0

    if (doctorProcess.running) doctorExpectedStop = true
    else doctorStartPending = false
    if (captureProcess.running) captureExpectedStop = true
    else captureStartPending = false
    if (copyProcess.running) copyExpectedStop = true
    else copyStartPending = false

    doctorProcess.running = false
    if (!sourceReleasePending) captureProcess.running = false
    copyProcess.running = false
    phase = "idle"
    demoMode = false
  }

  function dismiss() {
    if (shell && typeof shell.hide === "function") shell.hide(pluginId)
    else close()
  }

  function resumePendingOpen() {
    if (!pendingOpen || processesBusy()) return
    var payload = pendingPayload
    pendingOpen = false
    pendingPayload = ""
    beginOpen(payload)
  }

  function requestReaderFocus() {
    Qt.callLater(function() {
      if (!root.opened || !root.surfaceVisible) return
      var target = closeButton
      if (root.readerVisible) {
        if (root.sourceViewVisible) target = sourceBackButton
        else if (copyButton.visible && copyButton.enabled) target = copyButton
        else if (readAnotherButton.visible && readAnotherButton.enabled) target = readAnotherButton
      } else if (root.phase === "ready") {
        if (windowButton.visible && windowButton.enabled) target = windowButton
        else if (regionButton.visible && regionButton.enabled) target = regionButton
        else if (clipboardButton.visible && clipboardButton.enabled) target = clipboardButton
        else if (previewButton.visible && previewButton.enabled) target = previewButton
      } else if ((root.phase === "setup" || root.phase === "error")
          && setupPrimaryButton.visible && setupPrimaryButton.enabled) {
        target = setupPrimaryButton
      }
      target.forceActiveFocus()
    })
  }

  function showSurface() {
    if (!opened) return
    surfaceVisible = true
    requestReaderFocus()
  }

  function showDemo() {
    if (!opened || pendingOpen || processesBusy() || doctorStartPending
        || captureStartPending || copyStartPending || sourceHeld || captureProcess.running) return
    demoMode = true
    doctorReady = false
    captureTerminalSeen = true
    activeCaptureRequestId = 0
    activeMode = ""
    errorMessage = ""
    documentText = ClearReadModel.DEMO_DOCUMENT
    documentCharacters = ClearReadModel.codePointLength(documentText)
    phase = "reading"
    showSurface()
  }

  function retryDoctor() {
    if (!opened || demoMode || doctorProcess.running || doctorStartPending) return
    doctorReady = false
    doctorMessage = ""
    doctorMissing = []
    doctorIssues = []
    doctorCapabilities = ({ window: false, region: false, clipboard: false, copy: false })
    doctorTerminalSeen = false
    errorMessage = ""
    doctorDiagnostic = ""
    phase = "checking"
    launchDoctor()
  }

  function beginCapture(mode) {
    var requested = ClearReadModel.modeKey(mode)
    if (!opened || demoMode || !modeAvailable(requested) || requested === ""
        || doctorProcess.running || doctorStartPending
        || captureProcess.running || captureStartPending) return

    activeMode = requested
    documentText = ""
    documentCharacters = 0
    errorMessage = ""
    captureDiagnostic = ""
    transientMessage = ""
    captureTerminalSeen = false
    phase = requested === "region" ? "selecting" : "capturing"

    if (requested === "clipboard") {
      Qt.callLater(function() {
        if (root.opened && root.activeMode === "clipboard") root.launchCapture()
      })
      return
    }

    // Unmap the reader before grim takes pixels. A short compositor tick is
    // intentional; otherwise ClearRead can OCR its own landing card.
    surfaceVisible = false
    captureDelay.restart()
  }

  function readAnother() {
    if (!opened || (captureProcess.running && !sourceHeld) || captureStartPending) return
    releaseSource()
    documentText = ""
    documentCharacters = 0
    activeMode = ""
    captureMonitor = ""
    transientMessage = ""
    errorMessage = ""
    captureDiagnostic = ""
    captureTerminalSeen = true
    activeCaptureRequestId = 0

    if (demoMode) {
      demoMode = false
      retryDoctor()
      return
    }
    phase = doctorReady ? "ready" : "checking"
    if (!doctorReady) retryDoctor()
    showSurface()
  }

  function copyDocument() {
    if (!opened || documentText === "" || (captureProcess.running && !sourceHeld) || captureStartPending
        || copyProcess.running || copyStartPending) return
    copyPayload = documentText
    copyDiagnostic = ""
    transientMessage = "Copying…"
    copyStartPending = true
    copyProcess.running = true
  }

  function applyDoctor(event) {
    if (!opened || pendingOpen || demoMode || doctorExpectedStop || !event || !event.valid
        || event.requestId !== activeDoctorRequestId) return
    doctorTerminalSeen = true
    activeDoctorRequestId = 0
    doctorCapabilities = event.capabilities || ({ window: false, region: false, clipboard: false, copy: false })
    doctorReady = doctorCapabilities.window === true
      || doctorCapabilities.region === true
      || doctorCapabilities.clipboard === true
    doctorMessage = ""
    doctorMissing = event.missing || []
    doctorIssues = event.issues || []
    errorMessage = ""
    phase = doctorReady ? "ready" : "setup"
    requestReaderFocus()
  }

  function applyCaptureEvent(event) {
    if (!opened || pendingOpen || captureExpectedStop || !event || !event.valid
        || event.requestId !== activeCaptureRequestId) return

    if (event.type === "status") {
      if (event.mode !== activeMode) return
      phase = event.state
      if (event.monitor) {
        captureMonitor = event.monitor
        targetMonitor = event.monitor
      }
      if (event.state === "recognizing" || activeMode === "clipboard") showSurface()
      return
    }
    if (event.type === "result") {
      if (event.mode !== activeMode) return
      captureTerminalSeen = true
      activeCaptureRequestId = 0
      documentText = event.text
      documentCharacters = ClearReadModel.codePointLength(event.text)
      replaceSource(event.source)
      captureMonitor = event.monitor || captureMonitor
      if (captureMonitor !== "") targetMonitor = captureMonitor
      errorMessage = ""
      phase = "reading"
      showSurface()
      docFlick.contentY = 0
      return
    }
    if (event.type === "cancelled") {
      if (event.mode !== activeMode) return
      captureTerminalSeen = true
      activeCaptureRequestId = 0
      documentText = ""
      documentCharacters = 0
      errorMessage = ""
      phase = "ready"
      showSurface()
      return
    }
    if (event.type === "error") {
      captureTerminalSeen = true
      activeCaptureRequestId = 0
      documentText = ""
      documentCharacters = 0
      errorMessage = event.message
      phase = "error"
      showSurface()
    }
  }

  function presentationSettings() {
    return {
      version: 1,
      fontSize: fontSize,
      fontFamily: fontFamily,
      fontWeight: fontWeight,
      lineHeight: lineHeight,
      letterSpacing: letterSpacing,
      wordSpacing: wordSpacing,
      columnWidth: columnWidth,
      palette: paletteName,
      focusLines: focusLines
    }
  }

  function loadSettings(raw) {
    if (settingsLoaded) return
    var settings = ClearReadModel.normalizeSettings(raw)
    settingsHydrating = true
    fontSize = settings.fontSize
    fontFamily = settings.fontFamily
    fontWeight = settings.fontWeight
    lineHeight = settings.lineHeight
    letterSpacing = settings.letterSpacing
    wordSpacing = settings.wordSpacing
    columnWidth = settings.columnWidth
    paletteName = settings.palette
    focusLines = settings.focusLines
    settingsHydrating = false
    settingsLoaded = true
  }

  function scheduleSettingsSave() {
    if (!settingsLoaded || settingsHydrating || settingsPath === "") return
    settingsDirty = true
    if (!settingsDirectoryReady) {
      if (!settingsDirectoryProcess.running && !settingsDirectoryStartPending) {
        settingsDirectoryStartPending = true
        settingsDirectoryProcess.running = true
      }
      return
    }
    settingsSaveTimer.restart()
  }

  function flushSettings() {
    if (!settingsDirty || !settingsDirectoryReady || settingsPath === "") return
    settingsDirty = false
    settingsFile.setText(ClearReadModel.settingsJson(presentationSettings()))
  }

  function applySetting(group, value) {
    if (group === "family") fontFamily = value
    else if (group === "weight") fontWeight = value
    else if (group === "line") lineHeight = value
    else if (group === "letter") letterSpacing = value
    else if (group === "word") wordSpacing = value
    else if (group === "column") columnWidth = value
    else if (group === "palette") paletteName = value
    else if (group === "focus") focusLines = value
  }

  function adjustFontSize(amount) {
    fontSize = ClearReadModel.normalizeFontSize(fontSize + amount)
  }

  function setMagnification(percent) {
    fontSize = ClearReadModel.fontSizeForMagnification(percent)
  }

  function scrollDocument(amount) {
    var maximum = Math.max(0, docFlick.contentHeight - docFlick.height)
    docFlick.contentY = ClearReadModel.clamp(docFlick.contentY + amount, 0, maximum)
  }

  function revealSetting(item) {
    if (!item || !item.activeFocus) return
    var point = item.mapToItem(settingsColumn, 0, 0)
    var top = Math.max(0, point.y - Style.space(8))
    var bottom = point.y + item.height + Style.space(8)
    if (top < settingsFlick.contentY) settingsFlick.contentY = top
    else if (bottom > settingsFlick.contentY + settingsFlick.height)
      settingsFlick.contentY = Math.min(
        Math.max(0, settingsFlick.contentHeight - settingsFlick.height),
        bottom - settingsFlick.height)
  }

  onFontSizeChanged: scheduleSettingsSave()
  onFontFamilyChanged: scheduleSettingsSave()
  onFontWeightChanged: scheduleSettingsSave()
  onLineHeightChanged: scheduleSettingsSave()
  onLetterSpacingChanged: scheduleSettingsSave()
  onWordSpacingChanged: scheduleSettingsSave()
  onColumnWidthChanged: scheduleSettingsSave()
  onPaletteNameChanged: scheduleSettingsSave()
  onFocusLinesChanged: scheduleSettingsSave()

  Timer {
    id: captureDelay
    interval: 140
    repeat: false
    onTriggered: {
      if (!root.opened || root.activeMode === "" || root.activeMode === "clipboard") return
      root.launchCapture()
    }
  }

  Timer {
    id: settingsSaveTimer
    interval: 250
    repeat: false
    onTriggered: root.flushSettings()
  }

  Timer {
    id: transientMessageTimer
    interval: 1800
    repeat: false
    onTriggered: root.transientMessage = ""
  }

  Timer {
    id: sourceReleaseTimer
    interval: 750
    repeat: false
    onTriggered: {
      if (root.captureExpectedStop && captureProcess.running && !root.sourceHeld)
        captureProcess.running = false
    }
  }

  FontMetrics {
    id: readerFontMetrics
    font: documentBody.font
  }

  FileView {
    id: settingsFile
    path: root.settingsPath
    watchChanges: false
    atomicWrites: true
    printErrors: false
    onLoaded: {
      root.settingsDirectoryReady = true
      root.loadSettings(text())
    }
    onLoadFailed: root.loadSettings("")
  }

  Process {
    id: settingsDirectoryProcess
    command: ["mkdir", "-m", "700", "-p", "--", root.settingsDirectory]
    onStarted: root.settingsDirectoryStartPending = false
    onRunningChanged: {
      if (running || !root.settingsDirectoryStartPending) return
      root.settingsDirectoryStartPending = false
      root.settingsDirty = false
      console.warn("clearread: could not start settings directory creation")
    }
    onExited: function(exitCode) {
      root.settingsDirectoryStartPending = false
      if (exitCode !== 0) {
        root.settingsDirty = false
        console.warn("clearread: could not create private settings directory")
        return
      }
      root.settingsDirectoryReady = true
      if (root.settingsDirty) settingsSaveTimer.restart()
    }
  }

  Process {
    id: doctorProcess
    command: [root.backendPath, "--shell-pid", root.shellProcessId,
      "doctor", "--omarchy-path", root.omarchyPath,
      "--language", root.language, "--request-id", String(root.activeDoctorRequestId)]
    stdout: SplitParser {
      onRead: function(line) {
        var event = ClearReadModel.parseEvent(line)
        if (event.type === "doctor") root.applyDoctor(event)
        else if (event.type === "error" && event.valid && root.opened && !root.demoMode
            && event.requestId === root.activeDoctorRequestId) {
          root.doctorTerminalSeen = true
          root.activeDoctorRequestId = 0
          root.doctorReady = false
          root.doctorMessage = event.message
          root.errorMessage = ""
          root.phase = "setup"
          root.requestReaderFocus()
        }
      }
    }
    stderr: SplitParser {
      onRead: function(line) {
        if (root.opened && !root.doctorExpectedStop)
          root.doctorDiagnostic = ClearReadModel.cleanLine(line, 600)
      }
    }
    onStarted: root.doctorStartPending = false
    onRunningChanged: {
      if (running) return
      if (!root.doctorStartPending) {
        if (root.doctorTerminalSeen && root.opened && !root.pendingOpen
            && !root.demoMode && !root.doctorExpectedStop)
          Qt.callLater(function() { root.requestReaderFocus() })
        return
      }
      root.doctorStartPending = false
      if (root.doctorExpectedStop) root.doctorExpectedStop = false
      else if (root.opened && !root.pendingOpen && !root.demoMode) {
        root.doctorReady = false
        root.doctorTerminalSeen = true
        root.activeDoctorRequestId = 0
        root.doctorMessage = "Could not start the local ClearRead helper. Reinstall the plugin and check that bin/clearread is executable."
        root.phase = "setup"
        root.requestReaderFocus()
      }
      Qt.callLater(function() { root.resumePendingOpen() })
    }
    onExited: function(exitCode) {
      var finishedId = root.activeDoctorRequestId
      root.doctorStartPending = false
      if (root.doctorExpectedStop) {
        root.doctorExpectedStop = false
        Qt.callLater(function() { root.resumePendingOpen() })
        return
      }
      Qt.callLater(function() {
        if (!root.opened || root.pendingOpen || root.demoMode
            || finishedId !== root.activeDoctorRequestId || root.doctorTerminalSeen) return
        root.doctorReady = false
        root.doctorTerminalSeen = true
        root.activeDoctorRequestId = 0
        root.doctorMessage = ClearReadModel.safeProcessError(root.doctorDiagnostic, exitCode,
          "The local setup check returned no usable result.")
        root.phase = "setup"
        root.requestReaderFocus()
      })
    }
  }

  Process {
    id: captureProcess
    stdinEnabled: true
    command: [root.backendPath, "--shell-pid", root.shellProcessId,
      "capture", "--mode", root.activeMode,
      "--omarchy-path", root.omarchyPath, "--language", root.language,
      "--request-id", String(root.activeCaptureRequestId)]
    stdout: SplitParser {
      onRead: function(line) { root.applyCaptureEvent(ClearReadModel.parseEvent(line)) }
    }
    stderr: SplitParser {
      onRead: function(line) {
        if (root.opened && !root.captureExpectedStop)
          root.captureDiagnostic = ClearReadModel.cleanLine(line, 600)
      }
    }
    onStarted: root.captureStartPending = false
    onRunningChanged: {
      if (running) return
      if (!root.captureStartPending) {
        if (root.captureTerminalSeen && root.opened && !root.pendingOpen
            && !root.captureExpectedStop)
          Qt.callLater(function() { root.requestReaderFocus() })
        return
      }
      root.captureStartPending = false
      if (root.captureExpectedStop) root.captureExpectedStop = false
      else if (root.opened && !root.pendingOpen) {
        root.captureTerminalSeen = true
        root.activeCaptureRequestId = 0
        root.errorMessage = "Could not start the local ClearRead helper. Reinstall the plugin and check that bin/clearread is executable."
        root.phase = "error"
        root.showSurface()
      }
      Qt.callLater(function() { root.resumePendingOpen() })
    }
    onExited: function(exitCode) {
      var finishedId = root.activeCaptureRequestId
      root.captureStartPending = false
      sourceReleaseTimer.stop()
      if (root.captureExpectedStop) {
        root.captureExpectedStop = false
        if (root.opened && !root.pendingOpen) root.requestReaderFocus()
        Qt.callLater(function() { root.resumePendingOpen() })
        return
      }
      if (root.sourceHeld) {
        var wasViewingSource = root.sourceViewVisible
        root.discardSource()
        if (root.opened && !root.pendingOpen) {
          root.transientMessage = wasViewingSource
            ? "The temporary source view ended; your readable text remains."
            : "The temporary source was released."
          transientMessageTimer.restart()
          root.requestReaderFocus()
        }
      }
      Qt.callLater(function() {
        if (!root.opened || root.pendingOpen || finishedId !== root.activeCaptureRequestId
            || root.captureTerminalSeen) return
        root.captureTerminalSeen = true
        root.activeCaptureRequestId = 0
        root.errorMessage = ClearReadModel.safeProcessError(root.captureDiagnostic, exitCode,
          "The local reader stopped before returning text.")
        root.phase = "error"
        root.showSurface()
      })
    }
  }

  Process {
    id: copyProcess
    stdinEnabled: true
    command: [root.backendPath, "--shell-pid", root.shellProcessId, "copy"]
    stderr: SplitParser {
      onRead: function(line) {
        if (root.opened && !root.copyExpectedStop)
          root.copyDiagnostic = ClearReadModel.cleanLine(line, 600)
      }
    }
    onStarted: {
      root.copyStartPending = false
      var payload = root.copyPayload
      root.copyPayload = ""
      if (!root.opened || root.copyExpectedStop) return
      write(JSON.stringify({ text: payload }) + "\n")
    }
    onRunningChanged: {
      if (running || !root.copyStartPending) return
      root.copyStartPending = false
      root.copyPayload = ""
      if (root.copyExpectedStop) root.copyExpectedStop = false
      else if (root.opened) {
        root.transientMessage = "Could not start the local copy helper."
        transientMessageTimer.restart()
      }
      Qt.callLater(function() { root.resumePendingOpen() })
    }
    onExited: function(exitCode) {
      root.copyStartPending = false
      root.copyPayload = ""
      if (root.copyExpectedStop) {
        root.copyExpectedStop = false
        Qt.callLater(function() { root.resumePendingOpen() })
        return
      }
      if (!root.opened || root.pendingOpen) return
      root.transientMessage = exitCode === 0
        ? "Copied to the clipboard"
        : ClearReadModel.safeProcessError(root.copyDiagnostic, exitCode, "Could not copy the text.")
      transientMessageTimer.restart()
    }
  }

  IpcHandler {
    target: root.pluginId

    function open(payloadJson: string): string {
      root.open(payloadJson)
      return "ok"
    }
    function demo(): string {
      if (!root.opened) root.open(JSON.stringify({ demo: true }))
      else root.showDemo()
      return root.demoMode ? "ok" : "busy"
    }
    function close(): string {
      root.dismiss()
      return "ok"
    }
    function state(): string {
      return JSON.stringify({
        open: root.opened,
        visible: root.surfaceVisible,
        state: root.phase,
        demo: root.demoMode,
        running: root.processesRunning(),
        ready: root.doctorReady,
        mode: root.activeMode,
        hasText: root.documentText !== "",
        characters: root.documentCharacters,
        sourceHeld: root.sourceHeld,
        sourceView: root.sourceViewVisible
      })
    }
    function ping(): string { return "ok" }
  }

  PanelWindow {
    id: readerWindow
    screen: root.readerScreen
    visible: root.opened && root.surfaceVisible && root.readerScreen !== null
    anchors { top: true; right: true; bottom: true; left: true }
    color: root.colours.background
    exclusionMode: ExclusionMode.Ignore
    WlrLayershell.namespace: "clearread-reader"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: visible
      ? WlrKeyboardFocus.Exclusive
      : WlrKeyboardFocus.None

    onVisibleChanged: if (visible) root.requestReaderFocus()

    FocusScope {
      id: keyScope
      anchors.fill: parent
      focus: true
      Keys.priority: Keys.BeforeItem
      Keys.onPressed: function(event) {
        if (event.key === Qt.Key_Escape) {
          if (root.sourceViewVisible) root.showText()
          else root.dismiss()
          event.accepted = true
          return
        }
        if (root.sourceViewVisible) {
          if (event.key === Qt.Key_Plus || event.key === Qt.Key_Equal) {
            root.adjustSourceZoom(1)
            event.accepted = true
            return
          }
          if (event.key === Qt.Key_Minus) {
            root.adjustSourceZoom(-1)
            event.accepted = true
            return
          }
          if (event.key === Qt.Key_0) {
            root.setSourceZoom(0)
            event.accepted = true
            return
          }
          if (event.key === Qt.Key_Left || event.key === Qt.Key_Right
              || event.key === Qt.Key_Up || event.key === Qt.Key_Down) {
            if (event.modifiers !== Qt.NoModifier && event.modifiers !== Qt.ShiftModifier) return
            root.panSource(event.key === Qt.Key_Left ? -1 : event.key === Qt.Key_Right ? 1 : 0,
              event.key === Qt.Key_Up ? -1 : event.key === Qt.Key_Down ? 1 : 0,
              (event.modifiers & Qt.ShiftModifier) !== 0)
            event.accepted = true
            return
          }
        }
        if ((event.modifiers & Qt.ControlModifier)
            && (event.key === Qt.Key_Plus || event.key === Qt.Key_Equal)) {
          root.adjustFontSize(2)
          event.accepted = true
          return
        }
        if ((event.modifiers & Qt.ControlModifier) && event.key === Qt.Key_Minus) {
          root.adjustFontSize(-2)
          event.accepted = true
          return
        }
        if ((event.modifiers & Qt.ControlModifier) && event.key === Qt.Key_0) {
          root.setMagnification(100)
          event.accepted = true
          return
        }
        if (event.modifiers & Qt.ControlModifier) {
          var presetKeys = [Qt.Key_1, Qt.Key_2, Qt.Key_3, Qt.Key_4]
          var presetIndex = presetKeys.indexOf(event.key)
          if (presetIndex !== -1) {
            root.setMagnification(ClearReadModel.MAGNIFICATION_PRESETS[presetIndex])
            event.accepted = true
            return
          }
        }
        if (!root.readerVisible) return
        if (root.focusLines > 0 && event.modifiers === Qt.NoModifier
            && (event.key === Qt.Key_Up || event.key === Qt.Key_Down)) {
          root.scrollDocument((event.key === Qt.Key_Up ? -1 : 1) * root.readerLineStep)
          event.accepted = true
        } else if (event.modifiers === Qt.NoModifier && event.key === Qt.Key_PageUp) {
          root.scrollDocument(-docFlick.height * 0.86)
          event.accepted = true
        } else if (event.modifiers === Qt.NoModifier && event.key === Qt.Key_PageDown) {
          root.scrollDocument(docFlick.height * 0.86)
          event.accepted = true
        } else if (event.modifiers === Qt.NoModifier && event.key === Qt.Key_Home) {
          docFlick.contentY = 0
          event.accepted = true
        } else if (event.modifiers === Qt.NoModifier && event.key === Qt.Key_End) {
          docFlick.contentY = Math.max(0, docFlick.contentHeight - docFlick.height)
          event.accepted = true
        }
      }

      Rectangle {
        anchors.fill: parent
        color: root.colours.background
      }

      ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
          Layout.fillWidth: true
          Layout.preferredHeight: Math.max(Style.space(72), headerContent.implicitHeight + Style.space(24))
          color: root.colours.surface
          border.color: root.colours.border
          border.width: 1

          ColumnLayout {
            id: headerContent
            anchors.fill: parent
            anchors.leftMargin: Style.space(20)
            anchors.rightMargin: Style.space(16)
            anchors.topMargin: Style.space(12)
            anchors.bottomMargin: Style.space(12)
            spacing: Style.space(8)

            RowLayout {
              Layout.fillWidth: true
              spacing: Style.space(12)

              Rectangle {
                Layout.preferredWidth: Style.space(11)
                Layout.preferredHeight: width
                radius: width / 2
                color: root.colours.accent
              }

              Column {
                Layout.fillWidth: true
                spacing: Style.space(1)
                Text {
                  text: "ClearRead"
                  color: root.colours.text
                  font.family: Style.font.family
                  font.pixelSize: Style.font.subtitle
                  font.bold: true
                }
                Text {
                  width: parent.width
                  text: root.privacyStatus
                  textFormat: Text.PlainText
                  color: root.colours.muted
                  font.family: Style.font.family
                  font.pixelSize: Style.font.bodySmall
                  wrapMode: Text.WordWrap
                  Accessible.role: Accessible.StaticText
                  Accessible.name: text
                }
                Text {
                  visible: root.transientMessage !== ""
                  width: parent.width
                  text: root.transientMessage
                  textFormat: Text.PlainText
                  color: root.colours.accent
                  font.family: Style.font.family
                  font.pixelSize: Style.font.bodySmall
                  font.bold: true
                  wrapMode: Text.WordWrap
                }
              }

              AccessButton {
                id: closeButton
                text: "Close"
                focusable: true
                foreground: root.colours.text
                accent: root.colours.accent
                bordered: true
                tooltipText: "Close and clear the current text"
                Accessible.role: Accessible.Button
                Accessible.name: "Close ClearRead and clear its text"
                Accessible.onPressAction: clicked()
                onClicked: root.dismiss()
              }
            }

            Flow {
              id: headerActions
              Layout.fillWidth: true
              Layout.preferredHeight: visible ? childrenRect.height : 0
              visible: root.readerVisible
              spacing: Style.space(8)

              AccessButton {
                id: compareSourceButton
                visible: root.sourceAvailable && !root.sourceViewVisible
                text: "Compare source"
                focusable: true
                foreground: root.colours.text
                accent: root.colours.accent
                bordered: true
                tooltipText: "Magnify the temporary source image"
                Accessible.role: Accessible.Button
                Accessible.name: "Compare recognized text with the temporary source image"
                Accessible.description: "The source stays in memory and is released when you close or read another item"
                Accessible.onPressAction: clicked()
                onClicked: root.showSource()
              }
              AccessButton {
                id: sourceBackButton
                visible: root.sourceViewVisible
                text: "Readable text"
                focusable: true
                foreground: root.colours.text
                accent: root.colours.accent
                bordered: true
                tooltipText: "Return to the reflowed text"
                Accessible.role: Accessible.Button
                Accessible.name: "Return to readable text"
                Accessible.onPressAction: clicked()
                onClicked: root.showText()
              }
              AccessButton {
                id: copyButton
                text: "Copy"
                iconText: "⧉"
                focusable: true
                enabled: !copyProcess.running && !root.copyStartPending
                  && (!captureProcess.running || root.sourceHeld) && !root.captureStartPending
                  && (root.demoMode || root.doctorCapabilities.copy === true)
                foreground: root.colours.text
                accent: root.colours.accent
                bordered: true
                tooltipText: "Copy the displayed text"
                Accessible.role: Accessible.Button
                Accessible.name: "Copy displayed text"
                Accessible.onPressAction: clicked()
                onClicked: root.copyDocument()
              }
              AccessButton {
                id: readAnotherButton
                text: "Read another"
                focusable: true
                enabled: (!captureProcess.running || root.sourceHeld) && !root.captureStartPending
                foreground: root.colours.text
                accent: root.colours.accent
                bordered: true
                Accessible.role: Accessible.Button
                Accessible.name: "Read another item"
                Accessible.onPressAction: clicked()
                onClicked: root.readAnother()
              }
            }
          }
        }

        Item {
          Layout.fillWidth: true
          Layout.fillHeight: true

          Column {
            visible: !root.readerVisible
            width: Math.min(Style.space(760), parent.width - Style.space(48))
            anchors.centerIn: parent
            spacing: Style.space(18)

            Text {
              width: parent.width
              text: root.phase === "checking" ? "Checking local reading tools…"
                : root.phase === "recognizing" ? "Making this easier to read…"
                : root.clipboardCaptureActive ? "Reading clipboard text…"
                : root.phase === "setup" ? "Local setup needed"
                : root.phase === "error" ? "That content could not be read"
                : "Read anything on your screen"
              textFormat: Text.PlainText
              color: root.colours.text
              font.family: Style.font.family
              font.pixelSize: Style.font.displayLarge
              font.bold: true
              horizontalAlignment: Text.AlignHCenter
              wrapMode: Text.WordWrap
            }

            Text {
              visible: root.phase === "ready"
              width: parent.width
              text: "Choose exactly what to read. ClearRead captures only after your action, runs OCR locally, and keeps no reading history."
              color: root.colours.muted
              font.family: Style.font.family
              font.pixelSize: Style.font.body
              horizontalAlignment: Text.AlignHCenter
              wrapMode: Text.WordWrap
            }

            RowLayout {
              visible: root.phase === "ready"
              width: parent.width
              spacing: Style.space(10)

              AccessButton {
                id: windowButton
                Layout.fillWidth: true
                text: "Read active window"
                iconText: "▣"
                focusable: true
                enabled: root.modeAvailable("window") && !doctorProcess.running
                  && !root.doctorStartPending && !captureProcess.running && !root.captureStartPending
                foreground: root.colours.text
                accent: root.colours.accent
                background: root.colours.surface
                bordered: true
                horizontalPadding: Style.space(15)
                verticalPadding: Style.space(16)
                Accessible.role: Accessible.Button
                Accessible.name: "Read text from the active window"
                Accessible.onPressAction: clicked()
                onClicked: root.beginCapture("window")
              }
              AccessButton {
                id: regionButton
                Layout.fillWidth: true
                text: "Select screen area"
                iconText: "⌗"
                focusable: true
                enabled: root.modeAvailable("region") && !doctorProcess.running
                  && !root.doctorStartPending && !captureProcess.running && !root.captureStartPending
                foreground: root.colours.text
                accent: root.colours.accent
                background: root.colours.surface
                bordered: true
                horizontalPadding: Style.space(15)
                verticalPadding: Style.space(16)
                Accessible.role: Accessible.Button
                Accessible.name: "Select a screen area to read"
                Accessible.onPressAction: clicked()
                onClicked: root.beginCapture("region")
              }
              AccessButton {
                id: clipboardButton
                Layout.fillWidth: true
                text: "Read clipboard"
                iconText: "▤"
                focusable: true
                enabled: root.modeAvailable("clipboard") && !doctorProcess.running
                  && !root.doctorStartPending && !captureProcess.running && !root.captureStartPending
                foreground: root.colours.text
                accent: root.colours.accent
                background: root.colours.surface
                bordered: true
                horizontalPadding: Style.space(15)
                verticalPadding: Style.space(16)
                Accessible.role: Accessible.Button
                Accessible.name: "Read text currently on the clipboard"
                Accessible.onPressAction: clicked()
                onClicked: root.beginCapture("clipboard")
              }
            }

            Text {
              visible: root.phase === "recognizing" || root.clipboardCaptureActive
              width: parent.width
              text: root.clipboardCaptureActive
                ? "Reading only the clipboard text you requested. No screen capture or OCR is running."
                : "Local OCR is reflowing your " + ClearReadModel.modeLabel(root.activeMode) + "."
              textFormat: Text.PlainText
              color: root.colours.muted
              font.family: Style.font.family
              font.pixelSize: Style.font.body
              horizontalAlignment: Text.AlignHCenter
              wrapMode: Text.WordWrap
              Accessible.role: Accessible.StaticText
              Accessible.name: text
            }

            Text {
              visible: root.phase === "ready"
                && (!root.modeAvailable("window") || !root.modeAvailable("region")
                  || !root.modeAvailable("clipboard") || root.doctorCapabilities.copy !== true)
              width: parent.width
              text: "Unavailable actions stay disabled until their local tools are installed."
              color: root.colours.muted
              font.family: Style.font.family
              font.pixelSize: Style.font.bodySmall
              horizontalAlignment: Text.AlignHCenter
              wrapMode: Text.WordWrap
            }

            Text {
              visible: root.phase === "setup"
              width: parent.width
              text: root.setupDetails
              textFormat: Text.PlainText
              color: root.colours.text
              font.family: Style.font.family
              font.pixelSize: Style.font.body
              horizontalAlignment: Text.AlignHCenter
              wrapMode: Text.WordWrap
            }

            Text {
              visible: root.phase === "error"
              width: parent.width
              text: root.errorMessage
              textFormat: Text.PlainText
              color: root.colours.text
              font.family: Style.font.family
              font.pixelSize: Style.font.body
              horizontalAlignment: Text.AlignHCenter
              wrapMode: Text.WordWrap
            }

            Row {
              visible: root.phase === "setup" || root.phase === "error"
              anchors.horizontalCenter: parent.horizontalCenter
              spacing: Style.space(10)

              AccessButton {
                id: setupPrimaryButton
                text: root.phase === "setup" ? "Check again" : "Back"
                focusable: true
                foreground: root.colours.text
                accent: root.colours.accent
                bordered: true
                Accessible.role: Accessible.Button
                Accessible.name: text
                Accessible.onPressAction: clicked()
                onClicked: {
                  if (root.phase === "setup") root.retryDoctor()
                  else {
                    root.captureTerminalSeen = true
                    root.activeCaptureRequestId = 0
                    root.errorMessage = ""
                    root.phase = root.doctorReady ? "ready" : "setup"
                    root.requestReaderFocus()
                  }
                }
              }
              AccessButton {
                text: "Try safe demo"
                iconText: "▶"
                focusable: true
                enabled: !doctorProcess.running && !root.doctorStartPending
                  && !captureProcess.running && !root.captureStartPending
                foreground: root.colours.text
                accent: root.colours.accent
                bordered: true
                Accessible.role: Accessible.Button
                Accessible.name: "Try the synthetic ClearRead demo"
                Accessible.onPressAction: clicked()
                onClicked: root.showDemo()
              }
            }

            AccessButton {
              id: previewButton
              visible: root.phase === "ready"
              anchors.horizontalCenter: parent.horizontalCenter
              text: "Preview without capture"
              focusable: true
              enabled: !doctorProcess.running && !root.doctorStartPending
                && !captureProcess.running && !root.captureStartPending
              foreground: root.colours.muted
              accent: root.colours.accent
              bordered: true
              Accessible.role: Accessible.Button
              Accessible.name: "Preview ClearRead without accessing the screen or clipboard"
              Accessible.onPressAction: clicked()
              onClicked: root.showDemo()
            }

            Text {
              visible: root.phase === "ready" || root.phase === "setup"
              width: parent.width
              text: "On-device · no network · no screenshots or recognized text saved · Escape closes"
              color: root.colours.muted
              font.family: Style.font.family
              font.pixelSize: Style.font.bodySmall
              horizontalAlignment: Text.AlignHCenter
              wrapMode: Text.WordWrap
            }
          }

          RowLayout {
            id: readerLayout
            visible: root.readerVisible
            anchors.fill: parent
            anchors.margins: Style.space(16)
            spacing: Style.space(16)

            BorderSurface {
              visible: !root.sourceViewVisible
              Layout.preferredWidth: Math.min(Style.space(312), Math.max(Style.space(248), readerLayout.width * 0.29))
              Layout.fillHeight: true
              color: root.colours.surface
              borderSpec: Border.surfaceSpec("popups", "border", root.colours.border, 1)
              radius: Style.cornerRadius

              Flickable {
                id: settingsFlick
                anchors.fill: parent
                anchors.margins: Style.space(14)
                contentWidth: width
                contentHeight: settingsColumn.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                Controls.ScrollBar.vertical: Controls.ScrollBar {}

                Column {
                  id: settingsColumn
                  width: settingsFlick.width - Style.space(8)
                  spacing: Style.space(10)

                  Text {
                    text: "Reading preferences"
                    color: root.colours.text
                    font.family: Style.font.family
                    font.pixelSize: Style.font.subtitle
                    font.bold: true
                  }
                  Text {
                    width: parent.width
                    text: "Saved locally. Captured words are not."
                    color: root.colours.muted
                    font.family: Style.font.family
                    font.pixelSize: Style.font.caption
                    wrapMode: Text.WordWrap
                  }

                  Text {
                    text: "Reflow magnifier"
                    color: root.colours.text
                    font.family: Style.font.family
                    font.pixelSize: Style.font.bodySmall
                    font.bold: true
                  }
                  Text {
                    width: parent.width
                    text: "Enlarge text while it rewraps to fit the page."
                    color: root.colours.muted
                    font.family: Style.font.family
                    font.pixelSize: Style.font.caption
                    wrapMode: Text.WordWrap
                  }
                  Flow {
                    width: parent.width
                    spacing: Style.space(5)
                    Repeater {
                      model: ClearReadModel.MAGNIFICATION_PRESETS
                      delegate: AccessButton {
                        required property var modelData
                        text: modelData + "%"
                        focusable: true
                        selected: root.fontSize === ClearReadModel.fontSizeForMagnification(modelData)
                        foreground: root.colours.text
                        accent: root.colours.accent
                        bordered: true
                        Accessible.role: Accessible.RadioButton
                        Accessible.name: "Set text magnification to " + modelData + " percent"
                        Accessible.checkable: true
                        Accessible.checked: selected
                        Accessible.onPressAction: clicked()
                        Accessible.onToggleAction: clicked()
                        onActiveFocusChanged: root.revealSetting(this)
                        onClicked: root.setMagnification(modelData)
                      }
                    }
                  }

                  RowLayout {
                    width: parent.width
                    Text {
                      Layout.fillWidth: true
                      text: "Custom size"
                      color: root.colours.text
                      font.family: Style.font.family
                      font.pixelSize: Style.font.bodySmall
                      font.bold: true
                    }
                    AccessButton {
                      text: "A−"
                      focusable: true
                      enabled: root.fontSize > ClearReadModel.MIN_FONT_SIZE
                      foreground: root.colours.text
                      accent: root.colours.accent
                      bordered: true
                      Accessible.role: Accessible.Button
                      Accessible.name: "Decrease text size"
                      Accessible.onPressAction: clicked()
                      onActiveFocusChanged: root.revealSetting(this)
                      onClicked: root.adjustFontSize(-2)
                    }
                    Text {
                      text: root.fontSize + " px"
                      textFormat: Text.PlainText
                      color: root.colours.text
                      font.family: Style.font.family
                      font.pixelSize: Style.font.bodySmall
                    }
                    AccessButton {
                      text: "A+"
                      focusable: true
                      enabled: root.fontSize < ClearReadModel.MAX_FONT_SIZE
                      foreground: root.colours.text
                      accent: root.colours.accent
                      bordered: true
                      Accessible.role: Accessible.Button
                      Accessible.name: "Increase text size"
                      Accessible.onPressAction: clicked()
                      onActiveFocusChanged: root.revealSetting(this)
                      onClicked: root.adjustFontSize(2)
                    }
                  }

                  Text {
                    text: "Typeface"
                    color: root.colours.text
                    font.family: Style.font.family
                    font.pixelSize: Style.font.bodySmall
                    font.bold: true
                  }
                  Flow {
                    width: parent.width
                    spacing: Style.space(5)
                    Repeater {
                      model: [
                        { label: "System", value: "system" },
                        { label: "Serif", value: "serif" },
                        { label: "Mono", value: "mono" }
                      ]
                      delegate: AccessButton {
                        required property var modelData
                        text: modelData.label
                        focusable: true
                        selected: root.fontFamily === modelData.value
                        foreground: root.colours.text
                        accent: root.colours.accent
                        bordered: true
                        Accessible.role: Accessible.RadioButton
                        Accessible.name: modelData.label + " typeface"
                        Accessible.checkable: true
                        Accessible.checked: selected
                        Accessible.onPressAction: clicked()
                        Accessible.onToggleAction: clicked()
                        onActiveFocusChanged: root.revealSetting(this)
                        onClicked: root.applySetting("family", modelData.value)
                      }
                    }
                  }

                  Text {
                    text: "Weight"
                    color: root.colours.text
                    font.family: Style.font.family
                    font.pixelSize: Style.font.bodySmall
                    font.bold: true
                  }
                  Flow {
                    width: parent.width
                    spacing: Style.space(5)
                    Repeater {
                      model: [{ label: "Regular", value: "regular" }, { label: "Bold", value: "bold" }]
                      delegate: AccessButton {
                        required property var modelData
                        text: modelData.label
                        focusable: true
                        selected: root.fontWeight === modelData.value
                        foreground: root.colours.text
                        accent: root.colours.accent
                        bordered: true
                        Accessible.role: Accessible.RadioButton
                        Accessible.name: modelData.label + " text weight"
                        Accessible.checkable: true
                        Accessible.checked: selected
                        Accessible.onPressAction: clicked()
                        Accessible.onToggleAction: clicked()
                        onActiveFocusChanged: root.revealSetting(this)
                        onClicked: root.applySetting("weight", modelData.value)
                      }
                    }
                  }

                  Text {
                    text: "Line height"
                    color: root.colours.text
                    font.family: Style.font.family
                    font.pixelSize: Style.font.bodySmall
                    font.bold: true
                  }
                  Flow {
                    width: parent.width
                    spacing: Style.space(5)
                    Repeater {
                      model: [{ label: "1.25", value: 1.25 }, { label: "1.5", value: 1.5 }, { label: "2.0", value: 2 }]
                      delegate: AccessButton {
                        required property var modelData
                        text: modelData.label
                        focusable: true
                        selected: root.lineHeight === modelData.value
                        foreground: root.colours.text
                        accent: root.colours.accent
                        bordered: true
                        Accessible.role: Accessible.RadioButton
                        Accessible.name: modelData.label + " line height"
                        Accessible.checkable: true
                        Accessible.checked: selected
                        Accessible.onPressAction: clicked()
                        Accessible.onToggleAction: clicked()
                        onActiveFocusChanged: root.revealSetting(this)
                        onClicked: root.applySetting("line", modelData.value)
                      }
                    }
                  }

                  Text {
                    text: "Letter spacing"
                    color: root.colours.text
                    font.family: Style.font.family
                    font.pixelSize: Style.font.bodySmall
                    font.bold: true
                  }
                  Flow {
                    width: parent.width
                    spacing: Style.space(5)
                    Repeater {
                      model: [{ label: "Normal", value: 0 }, { label: "+1", value: 1 }, { label: "+2", value: 2 }]
                      delegate: AccessButton {
                        required property var modelData
                        text: modelData.label
                        focusable: true
                        selected: root.letterSpacing === modelData.value
                        foreground: root.colours.text
                        accent: root.colours.accent
                        bordered: true
                        Accessible.role: Accessible.RadioButton
                        Accessible.name: modelData.label + " letter spacing"
                        Accessible.checkable: true
                        Accessible.checked: selected
                        Accessible.onPressAction: clicked()
                        Accessible.onToggleAction: clicked()
                        onActiveFocusChanged: root.revealSetting(this)
                        onClicked: root.applySetting("letter", modelData.value)
                      }
                    }
                  }

                  Text {
                    text: "Word spacing"
                    color: root.colours.text
                    font.family: Style.font.family
                    font.pixelSize: Style.font.bodySmall
                    font.bold: true
                  }
                  Flow {
                    width: parent.width
                    spacing: Style.space(5)
                    Repeater {
                      model: [{ label: "Normal", value: 0 }, { label: "+4", value: 4 }, { label: "+8", value: 8 }]
                      delegate: AccessButton {
                        required property var modelData
                        text: modelData.label
                        focusable: true
                        selected: root.wordSpacing === modelData.value
                        foreground: root.colours.text
                        accent: root.colours.accent
                        bordered: true
                        Accessible.role: Accessible.RadioButton
                        Accessible.name: modelData.label + " word spacing"
                        Accessible.checkable: true
                        Accessible.checked: selected
                        Accessible.onPressAction: clicked()
                        Accessible.onToggleAction: clicked()
                        onActiveFocusChanged: root.revealSetting(this)
                        onClicked: root.applySetting("word", modelData.value)
                      }
                    }
                  }

                  Text {
                    text: "Text column"
                    color: root.colours.text
                    font.family: Style.font.family
                    font.pixelSize: Style.font.bodySmall
                    font.bold: true
                  }
                  Flow {
                    width: parent.width
                    spacing: Style.space(5)
                    Repeater {
                      model: [
                        { label: "Narrow", value: "narrow" },
                        { label: "Medium", value: "medium" },
                        { label: "Wide", value: "wide" }
                      ]
                      delegate: AccessButton {
                        required property var modelData
                        text: modelData.label
                        focusable: true
                        selected: root.columnWidth === modelData.value
                        foreground: root.colours.text
                        accent: root.colours.accent
                        bordered: true
                        Accessible.role: Accessible.RadioButton
                        Accessible.name: modelData.label + " text column"
                        Accessible.checkable: true
                        Accessible.checked: selected
                        Accessible.onPressAction: clicked()
                        Accessible.onToggleAction: clicked()
                        onActiveFocusChanged: root.revealSetting(this)
                        onClicked: root.applySetting("column", modelData.value)
                      }
                    }
                  }

                  Text {
                    text: "Colour palette"
                    color: root.colours.text
                    font.family: Style.font.family
                    font.pixelSize: Style.font.bodySmall
                    font.bold: true
                  }
                  Flow {
                    width: parent.width
                    spacing: Style.space(5)
                    Repeater {
                      model: [
                        { label: "Paper", value: "paper" },
                        { label: "Sepia", value: "sepia" },
                        { label: "Dark", value: "dark" },
                        { label: "Contrast", value: "contrast" }
                      ]
                      delegate: AccessButton {
                        required property var modelData
                        text: modelData.label
                        focusable: true
                        selected: root.paletteName === modelData.value
                        foreground: root.colours.text
                        accent: root.colours.accent
                        bordered: true
                        Accessible.role: Accessible.RadioButton
                        Accessible.name: modelData.label + " colour palette"
                        Accessible.checkable: true
                        Accessible.checked: selected
                        Accessible.onPressAction: clicked()
                        Accessible.onToggleAction: clicked()
                        onActiveFocusChanged: root.revealSetting(this)
                        onClicked: root.applySetting("palette", modelData.value)
                      }
                    }
                  }

                  Text {
                    text: "Line focus"
                    color: root.colours.text
                    font.family: Style.font.family
                    font.pixelSize: Style.font.bodySmall
                    font.bold: true
                  }
                  Flow {
                    width: parent.width
                    spacing: Style.space(5)
                    Repeater {
                      model: [
                        { label: "Off", value: 0 },
                        { label: "1 line", value: 1 },
                        { label: "3 lines", value: 3 },
                        { label: "5 lines", value: 5 }
                      ]
                      delegate: AccessButton {
                        required property var modelData
                        text: modelData.label
                        focusable: true
                        selected: root.focusLines === modelData.value
                        foreground: root.colours.text
                        accent: root.colours.accent
                        bordered: true
                        Accessible.role: Accessible.RadioButton
                        Accessible.name: modelData.label + " line focus"
                        Accessible.checkable: true
                        Accessible.checked: selected
                        Accessible.onPressAction: clicked()
                        Accessible.onToggleAction: clicked()
                        onActiveFocusChanged: root.revealSetting(this)
                        onClicked: root.applySetting("focus", modelData.value)
                      }
                    }
                  }

                  Text {
                    width: parent.width
                    text: "Ctrl 1–4 selects 100–400% · Ctrl +/− fine-tunes · Ctrl 0 resets · Page Up/Down scrolls"
                    color: root.colours.muted
                    font.family: Style.font.family
                    font.pixelSize: Style.font.caption
                    wrapMode: Text.WordWrap
                  }
                }
              }
            }

            ColumnLayout {
              id: sourceLens
              visible: root.sourceViewVisible
              Layout.fillWidth: true
              Layout.fillHeight: true
              spacing: Style.space(10)

              RowLayout {
                Layout.fillWidth: true
                spacing: Style.space(10)

                Column {
                  Layout.fillWidth: true
                  spacing: 2
                  Text {
                    text: "Source lens"
                    color: root.colours.text
                    font.family: Style.font.family
                    font.pixelSize: Style.font.subtitle
                    font.bold: true
                  }
                  Text {
                    width: parent.width
                    text: "A temporary view of the pixels used for this reading. It is never recaptured or saved by ClearRead."
                    textFormat: Text.PlainText
                    color: root.colours.muted
                    font.family: Style.font.family
                    font.pixelSize: Style.font.caption
                    wrapMode: Text.WordWrap
                  }
                }

                Repeater {
                  model: [
                    { label: "Fit", value: 0 },
                    { label: "2×", value: 2 },
                    { label: "4×", value: 4 }
                  ]
                  delegate: AccessButton {
                    required property var modelData
                    text: modelData.label
                    focusable: true
                    selected: root.sourceZoom === modelData.value
                    foreground: root.colours.text
                    accent: root.colours.accent
                    bordered: true
                    Accessible.role: Accessible.RadioButton
                    Accessible.name: modelData.value === 0
                      ? "Fit source image to the available space"
                      : "Magnify source image to " + modelData.value + " times"
                    Accessible.checkable: true
                    Accessible.checked: selected
                    Accessible.onPressAction: clicked()
                    Accessible.onToggleAction: clicked()
                    onClicked: root.setSourceZoom(modelData.value)
                  }
                }
              }

              Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                color: "#000000"
                radius: Style.cornerRadius
                border.color: root.colours.border
                border.width: root.paletteName === "contrast" ? 2 : 1
                clip: true

                Flickable {
                  id: sourceFlick
                  anchors.fill: parent
                  anchors.margins: 1
                  readonly property real fitScale: root.sourceWidth > 0 && root.sourceHeight > 0
                    ? Math.min(width / root.sourceWidth, height / root.sourceHeight) : 1
                  readonly property real imageScale: root.sourceZoom === 0 ? fitScale : root.sourceZoom
                  contentWidth: Math.max(width, root.sourceWidth * imageScale)
                  contentHeight: Math.max(height, root.sourceHeight * imageScale)
                  clip: true
                  interactive: true
                  boundsBehavior: Flickable.StopAtBounds
                  Controls.ScrollBar.horizontal: Controls.ScrollBar {}
                  Controls.ScrollBar.vertical: Controls.ScrollBar {}

                  Image {
                    id: sourceImage
                    x: Math.max(0, (sourceFlick.contentWidth - width) / 2)
                    y: Math.max(0, (sourceFlick.contentHeight - height) / 2)
                    width: root.sourceWidth * sourceFlick.imageScale
                    height: root.sourceHeight * sourceFlick.imageScale
                    source: root.sourceViewVisible ? root.sourceUri : ""
                    cache: false
                    asynchronous: true
                    fillMode: Image.PreserveAspectFit
                    smooth: true
                    Accessible.role: Accessible.Graphic
                    Accessible.name: "Temporary source image"
                    Accessible.description: "Drag to pan, use plus and minus to magnify, zero to fit, or Escape to return to readable text"
                  }
                }

                Text {
                  visible: sourceImage.status === Image.Loading
                  anchors.centerIn: parent
                  text: "Loading temporary source image…"
                  textFormat: Text.PlainText
                  color: "#ffffff"
                  font.family: Style.font.family
                  font.pixelSize: Style.font.body
                  Accessible.role: Accessible.StaticText
                  Accessible.name: text
                }

                Text {
                  visible: sourceImage.status === Image.Error
                  anchors.centerIn: parent
                  width: Math.min(parent.width - Style.space(32), Style.space(520))
                  text: "The temporary source image could not be displayed. Your readable text is still available."
                  textFormat: Text.PlainText
                  color: "#ffffff"
                  font.family: Style.font.family
                  font.pixelSize: Style.font.body
                  horizontalAlignment: Text.AlignHCenter
                  wrapMode: Text.WordWrap
                }
              }

              Text {
                Layout.fillWidth: true
                text: "+/− magnifies · 0 fits · arrows pan · Shift+arrows pan farther · drag with a pointer · Escape returns to text"
                textFormat: Text.PlainText
                color: root.colours.muted
                font.family: Style.font.family
                font.pixelSize: Style.font.caption
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
              }
            }

            Rectangle {
              id: documentFrame
              visible: !root.sourceViewVisible
              Layout.fillWidth: true
              Layout.fillHeight: true
              color: root.colours.surface
              radius: Style.cornerRadius
              border.color: root.colours.border
              border.width: root.paletteName === "contrast" ? 2 : 1
              clip: true
              readonly property real focusBandHeight: Math.min(height,
                root.readerLineStep * Math.max(1, root.focusLines) + Style.space(8))
              readonly property real readingTopPadding: root.focusLines > 0
                ? Math.max(Style.space(20), (height - focusBandHeight) / 2)
                : Style.space(38)

              Flickable {
                id: docFlick
                anchors.fill: parent
                contentWidth: width
                contentHeight: Math.max(height, documentBody.y + documentBody.height
                  + (root.focusLines > 0 ? documentFrame.readingTopPadding : Style.space(42)))
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                Controls.ScrollBar.vertical: Controls.ScrollBar {}

                Text {
                  id: documentBody
                  x: Math.max(Style.space(24), (docFlick.width - width) / 2)
                  y: documentFrame.readingTopPadding
                  width: ClearReadModel.columnPixels(root.columnWidth, docFlick.width - Style.space(48))
                  text: root.documentText
                  textFormat: Text.PlainText
                  wrapMode: Text.Wrap
                  color: root.colours.text
                  font.family: root.resolvedFontFamily
                  font.pixelSize: root.fontSize
                  font.weight: root.fontWeight === "bold" ? Font.Bold : Font.Normal
                  font.letterSpacing: root.letterSpacing
                  font.wordSpacing: root.wordSpacing
                  lineHeight: root.lineHeight
                  lineHeightMode: Text.ProportionalHeight
                  Accessible.role: Accessible.StaticText
                  Accessible.name: root.documentText
                  Accessible.multiLine: true
                  Accessible.description: "Recognized text in the ClearRead reader"
                }
              }

              Item {
                visible: root.focusLines > 0
                anchors.fill: parent
                anchors.rightMargin: Style.space(10)
                z: 3
                readonly property real bandHeight: documentFrame.focusBandHeight

                Rectangle {
                  anchors.top: parent.top
                  width: parent.width
                  height: Math.max(0, (parent.height - parent.bandHeight) / 2)
                  color: root.colours.focus
                  opacity: root.paletteName === "contrast" ? 0.82 : 0.62
                }
                Rectangle {
                  anchors.bottom: parent.bottom
                  width: parent.width
                  height: Math.max(0, (parent.height - parent.bandHeight) / 2)
                  color: root.colours.focus
                  opacity: root.paletteName === "contrast" ? 0.82 : 0.62
                }
              }

              Text {
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.margins: Style.space(10)
                z: 4
                text: ClearReadModel.formatCharacterCount(root.documentCharacters)
                textFormat: Text.PlainText
                color: root.colours.muted
                font.family: Style.font.family
                font.pixelSize: Style.font.caption
              }
            }
          }
        }
      }
    }
  }

  Component.onCompleted: settingsFile.reload()
}
