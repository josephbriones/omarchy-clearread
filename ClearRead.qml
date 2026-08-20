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
    verticalPadding: Math.max(Style.spacing.controlPaddingY, (44 - fontSize) / 2)
    horizontalPadding: Math.max(Style.spacing.controlPaddingX, (44 - fontSize) / 2)
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
    if (phase === "selecting") return "Waiting for your selection"
    if (phase === "capturing") return "Capturing only what you requested"
    if (phase === "recognizing") return "Recognizing locally · nothing is uploaded"
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
    return doctorProcess.running || captureProcess.running || copyProcess.running
      || doctorExpectedStop || captureExpectedStop || copyExpectedStop
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
    captureProcess.running = false
    copyProcess.running = false
    phase = "idle"
    demoMode = false
  }

  function dismiss() {
    close()
    if (shell && typeof shell.hide === "function") shell.hide(pluginId)
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
        if (copyButton.visible && copyButton.enabled) target = copyButton
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
        || captureStartPending || copyStartPending) return
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
    if (!opened || captureProcess.running || captureStartPending) return
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
    if (!opened || documentText === "" || captureProcess.running || captureStartPending
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
    fontSize = Math.round(ClearReadModel.clamp(fontSize + amount, 18, 72))
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
      if (root.captureExpectedStop) {
        root.captureExpectedStop = false
        Qt.callLater(function() { root.resumePendingOpen() })
        return
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
        running: root.processesBusy(),
        ready: root.doctorReady,
        mode: root.activeMode,
        hasText: root.documentText !== "",
        characters: root.documentCharacters
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
          root.dismiss()
          event.accepted = true
          return
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
          root.fontSize = ClearReadModel.DEFAULT_SETTINGS.fontSize
          event.accepted = true
          return
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
          Layout.preferredHeight: Math.max(72, Style.space(64))
          color: root.colours.surface
          border.color: root.colours.border
          border.width: 1

          RowLayout {
            anchors.fill: parent
            anchors.leftMargin: Style.space(20)
            anchors.rightMargin: Style.space(16)
            spacing: Style.space(12)

            Rectangle {
              Layout.preferredWidth: Style.space(11)
              Layout.preferredHeight: width
              radius: width / 2
              color: root.colours.accent
            }

            Column {
              Layout.fillWidth: true
              spacing: 1
              Text {
                text: "ClearRead"
                color: root.colours.text
                font.family: Style.font.family
                font.pixelSize: Style.font.subtitle
                font.bold: true
              }
              Text {
                text: root.privacyStatus
                textFormat: Text.PlainText
                color: root.colours.muted
                font.family: Style.font.family
                font.pixelSize: Style.font.bodySmall
              }
            }

            Text {
              visible: root.transientMessage !== ""
              text: root.transientMessage
              textFormat: Text.PlainText
              color: root.colours.accent
              font.family: Style.font.family
              font.pixelSize: Style.font.bodySmall
              font.bold: true
            }

            AccessButton {
              id: copyButton
              visible: root.readerVisible
              text: "Copy"
              iconText: "⧉"
              focusable: true
              enabled: !copyProcess.running && !root.copyStartPending
                && !captureProcess.running && !root.captureStartPending
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
              visible: root.readerVisible
              text: "Read another"
              focusable: true
              enabled: !captureProcess.running && !root.captureStartPending
              foreground: root.colours.text
              accent: root.colours.accent
              bordered: true
              Accessible.role: Accessible.Button
              Accessible.name: "Read another item"
              Accessible.onPressAction: clicked()
              onClicked: root.readAnother()
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
        }

        Item {
          Layout.fillWidth: true
          Layout.fillHeight: true

          Column {
            visible: !root.readerVisible
            width: Math.min(760, parent.width - Style.space(48))
            anchors.centerIn: parent
            spacing: Style.space(18)

            Text {
              width: parent.width
              text: root.phase === "checking" ? "Checking local reading tools…"
                : root.phase === "recognizing" ? "Making this easier to read…"
                : root.phase === "setup" ? "Local setup needed"
                : root.phase === "error" ? "That content could not be read"
                : "Read anything on your screen"
              textFormat: Text.PlainText
              color: root.colours.text
              font.family: Style.font.family
              font.pixelSize: Math.max(28, Style.font.title * 1.35)
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
              visible: root.phase === "recognizing"
              width: parent.width
              text: "Local OCR is reflowing your " + ClearReadModel.modeLabel(root.activeMode) + "."
              textFormat: Text.PlainText
              color: root.colours.muted
              font.family: Style.font.family
              font.pixelSize: Style.font.body
              horizontalAlignment: Text.AlignHCenter
              wrapMode: Text.WordWrap
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
              Layout.preferredWidth: Math.min(312, Math.max(248, readerLayout.width * 0.29))
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

                  RowLayout {
                    width: parent.width
                    Text {
                      Layout.fillWidth: true
                      text: "Text size"
                      color: root.colours.text
                      font.family: Style.font.family
                      font.pixelSize: Style.font.bodySmall
                      font.bold: true
                    }
                    AccessButton {
                      text: "A−"
                      focusable: true
                      enabled: root.fontSize > 18
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
                      enabled: root.fontSize < 72
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
                    text: "Ctrl +/− changes size · Ctrl 0 resets size · Page Up/Down scrolls"
                    color: root.colours.muted
                    font.family: Style.font.family
                    font.pixelSize: Style.font.caption
                    wrapMode: Text.WordWrap
                  }
                }
              }
            }

            Rectangle {
              id: documentFrame
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
                  wrapMode: Text.WordWrap
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
