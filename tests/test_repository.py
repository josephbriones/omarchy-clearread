import json
import os
import pathlib
import re
import stat
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class RepositoryTests(unittest.TestCase):
    def test_manifest_contract(self):
        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["schemaVersion"], 1)
        self.assertEqual(manifest["id"], "io.github.josephbriones.clearread")
        self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+$")
        self.assertEqual(manifest["kinds"], ["overlay"])
        self.assertEqual(manifest["entryPoints"], {"overlay": "ClearRead.qml"})
        self.assertIs(manifest["keepLoaded"], True)
        self.assertTrue((ROOT / manifest["entryPoints"]["overlay"]).is_file())

    def test_repository_has_one_root_manifest_and_no_symlinks(self):
        self.assertEqual(list(ROOT.glob("manifest.json")), [ROOT / "manifest.json"])
        symlinks = [path for path in ROOT.rglob("*") if path.is_symlink()]
        self.assertEqual(symlinks, [])

    def test_required_release_files_exist(self):
        required = [
            "README.md",
            "LICENSE",
            "PRIVACY.md",
            "SECURITY.md",
            "CHANGELOG.md",
            "ClearRead.qml",
            "ClearReadModel.js",
            "bin/clearread",
            "lib/clearread.py",
        ]
        for relative in required:
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_launcher_is_executable(self):
        mode = (ROOT / "bin/clearread").stat().st_mode
        self.assertTrue(mode & stat.S_IXUSR)

    def test_readme_covers_install_removal_dependencies_and_license(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for phrase in [
            "omarchy plugin add",
            "omarchy plugin remove",
            "Local requirements",
            "Tesseract",
            "License",
        ]:
            self.assertIn(phrase, readme)

    def test_language_docs_match_the_supported_identifier_grammar(self):
        setup = (ROOT / "docs/SETUP.md").read_text(encoding="utf-8")
        self.assertRegex(setup, r"lowercase Tesseract\s+language codes")
        for phrase in (
            "ASCII letters, digits, and underscores",
            "complete value may be at most 120 characters",
            "`script/Latin` are unsupported",
        ):
            self.assertIn(phrase, setup)

    def test_preview_shows_the_current_reflow_and_source_controls(self):
        svg = (ROOT / "assets/preview.svg").read_text(encoding="utf-8")
        for label in (
            "Reflow magnifier",
            "100%",
            "200%",
            "300%",
            "400%",
            "Compare source",
            "Fit, 2×, or 4×",
        ):
            self.assertIn(label, svg)
        self.assertNotIn("READING VIEW", svg)

        png = (ROOT / "preview.png").read_bytes()
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(int.from_bytes(png[16:20], "big"), 1600)
        self.assertEqual(int.from_bytes(png[20:24], "big"), 900)
        self.assertLess(len(png), 2 * 1024 * 1024)

    def test_root_scanner_text_avoids_privileged_or_remote_install_patterns(self):
        scanned = "\n".join(
            (ROOT / name).read_text(encoding="utf-8")
            for name in ["README.md", "manifest.json"]
        ).lower()
        for forbidden in ["curl |", "curl|", "wget |", "wget|", "sudo", "pkexec", "systemctl", "pacman -"]:
            self.assertNotIn(forbidden, scanned)

    def test_qml_declares_plain_text_for_dynamic_surfaces(self):
        qml = (ROOT / "ClearRead.qml").read_text(encoding="utf-8")
        self.assertNotIn("Text.RichText", qml)
        self.assertNotIn("Text.AutoText", qml)
        protected_bindings = (
            "text: root.privacyStatus",
            "text: root.transientMessage",
            "text: root.setupDetails",
            "text: root.errorMessage",
            "text: root.documentText",
        )
        for binding in protected_bindings:
            start = qml.index(binding)
            self.assertIn("textFormat: Text.PlainText", qml[start : start + 240], binding)
        self.assertIn("keepLoaded", (ROOT / "manifest.json").read_text(encoding="utf-8"))

    def test_clipboard_capture_has_truthful_plain_text_accessibility_status(self):
        qml = (ROOT / "ClearRead.qml").read_text(encoding="utf-8")
        self.assertIn(
            'readonly property bool clipboardCaptureActive: phase === "capturing" && activeMode === "clipboard"',
            qml,
        )
        self.assertIn(
            'if (clipboardCaptureActive) return "Reading clipboard text · no screen capture or OCR"',
            qml,
        )
        self.assertIn(
            ': root.clipboardCaptureActive ? "Reading clipboard text…"',
            qml,
        )

        start = qml.index('visible: root.phase === "recognizing" || root.clipboardCaptureActive')
        status = qml[start : start + 750]
        for contract in (
            "Reading only the clipboard text you requested. No screen capture or OCR is running.",
            "textFormat: Text.PlainText",
            "Accessible.role: Accessible.StaticText",
            "Accessible.name: text",
        ):
            self.assertIn(contract, status)

    def test_qml_host_lifecycle_and_ipc_contract_are_explicit(self):
        qml = (ROOT / "ClearRead.qml").read_text(encoding="utf-8")
        self.assertIn("Item {\n  id: root", qml)
        for host_property in ("omarchyPath", "shell", "manifest"):
            self.assertNotRegex(qml, rf"required property\s+\w+\s+{host_property}\b")
        self.assertIn("target: root.pluginId", qml)
        for signature in (
            "function open(payloadJson: string): string",
            "function demo(): string",
            "function close(): string",
            "function state(): string",
            "function ping(): string",
        ):
            self.assertIn(signature, qml)

    def test_close_stops_every_workflow_and_discards_document_content(self):
        qml = (ROOT / "ClearRead.qml").read_text(encoding="utf-8")
        start = qml.index("function close()")
        close_body = qml[start : qml.index("function dismiss()", start)]
        for statement in (
            'documentText = ""',
            'copyPayload = ""',
            "documentCharacters = 0",
            "activeDoctorRequestId = 0",
            "activeCaptureRequestId = 0",
            "doctorProcess.running = false",
            "captureProcess.running = false",
            "copyProcess.running = false",
        ):
            self.assertIn(statement, close_body)

        dismiss_start = qml.index("function dismiss()")
        dismiss_end = qml.index("function resumePendingOpen()", dismiss_start)
        dismiss_body = qml[dismiss_start:dismiss_end]
        self.assertIn('shell.hide(pluginId)', dismiss_body)
        self.assertIn('else close()', dismiss_body)
        self.assertNotIn("close()\n    if", dismiss_body)

    def test_qml_process_start_failures_and_stale_events_fail_closed(self):
        qml = (ROOT / "ClearRead.qml").read_text(encoding="utf-8")
        self.assertGreaterEqual(qml.count("onRunningChanged:"), 4)
        self.assertEqual(qml.count("Could not start the local ClearRead helper"), 2)
        self.assertIn("Could not start the local copy helper", qml)
        self.assertIn("event.requestId !== activeDoctorRequestId", qml)
        self.assertIn("event.requestId !== activeCaptureRequestId", qml)
        self.assertIn("finishedId !== root.activeDoctorRequestId", qml)
        self.assertIn("finishedId !== root.activeCaptureRequestId", qml)
        self.assertIn("event.mode !== activeMode", qml)

    def test_qml_accessibility_controls_keep_native_focus_and_target_size(self):
        qml = (ROOT / "ClearRead.qml").read_text(encoding="utf-8")
        self.assertEqual(qml.count("AccessButton {"), 23)
        self.assertIn("component AccessButton: Button", qml)
        self.assertIn("(44 - fontSize) / 2", qml)
        self.assertIn("target.forceActiveFocus()", qml)
        self.assertIn("WlrKeyboardFocus.Exclusive", qml)
        self.assertNotIn("focusPrime", qml)
        self.assertIn("readerFontMetrics.lineSpacing * lineHeight", qml)
        self.assertIn("Accessible.multiLine: true", qml)
        self.assertEqual(qml.count("Accessible.role: Accessible.RadioButton"), 10)
        self.assertEqual(qml.count("Accessible.onToggleAction: clicked()"), 10)
        self.assertIn("String(Quickshell.processId)", qml)
        self.assertEqual(qml.count('"--shell-pid", root.shellProcessId'), 3)

    def test_reflow_magnifier_is_visible_keyboard_accessible_and_horizontal_scroll_free(self):
        qml = (ROOT / "ClearRead.qml").read_text(encoding="utf-8")
        start = qml.index('text: "Reflow magnifier"')
        end = qml.index('text: "Typeface"', start)
        controls = qml[start:end]
        self.assertIn("model: ClearReadModel.MAGNIFICATION_PRESETS", controls)
        self.assertIn('text: modelData + "%"', controls)
        self.assertIn("Accessible.role: Accessible.RadioButton", controls)
        self.assertIn("Accessible.checkable: true", controls)
        self.assertIn("Accessible.checked: selected", controls)
        self.assertIn("Accessible.onToggleAction: clicked()", controls)
        self.assertIn('Accessible.name: "Set text magnification to " + modelData + " percent"', controls)
        self.assertIn("onClicked: root.setMagnification(modelData)", controls)
        keys_start = qml.index("Keys.onPressed: function(event)")
        keys_end = qml.index("if (!root.readerVisible) return", keys_start)
        keys = qml[keys_start:keys_end]
        self.assertIn("root.setMagnification(100)", keys)
        self.assertIn("Qt.Key_1, Qt.Key_2, Qt.Key_3, Qt.Key_4", keys)
        self.assertIn("ClearReadModel.MAGNIFICATION_PRESETS[presetIndex]", keys)
        viewport_start = qml.index("id: docFlick")
        document_start = qml.index("id: documentBody")
        self.assertIn("contentWidth: width", qml[viewport_start:document_start])
        self.assertIn("wrapMode: Text.Wrap", qml[document_start : document_start + 500])

    def test_source_lens_holds_one_bounded_source_and_releases_it_explicitly(self):
        qml = (ROOT / "ClearRead.qml").read_text(encoding="utf-8")
        capture_start = qml.index("id: captureProcess")
        capture_end = qml.index("id: copyProcess", capture_start)
        self.assertIn("stdinEnabled: true", qml[capture_start:capture_end])
        self.assertIn("property bool sourceHeld: false", qml)
        self.assertIn("property var sourceDescriptor: null", qml)
        self.assertIn("replaceSource(event.source)", qml)

        release_start = qml.index("function releaseSource()")
        release_end = qml.index("function replaceSource", release_start)
        release = qml[release_start:release_end]
        self.assertIn('captureProcess.write("release\\n")', release)
        self.assertIn("sourceDescriptor = null", release)
        for owner in ("function close()", "function readAnother()", "function replaceSource"):
            start = qml.index(owner)
            self.assertIn("releaseSource()", qml[start : start + 500], owner)
        self.assertIn("(!captureProcess.running || root.sourceHeld)", qml)

    def test_source_lens_is_an_explicit_accessible_non_recapturing_view(self):
        qml = (ROOT / "ClearRead.qml").read_text(encoding="utf-8")
        compare_start = qml.index("id: compareSourceButton")
        compare = qml[compare_start : qml.index("id: sourceBackButton", compare_start)]
        self.assertIn("root.sourceAvailable", compare)
        self.assertIn("!root.sourceViewVisible", compare)
        self.assertIn('text: "Compare source"', compare)
        self.assertIn("!demoMode", qml[qml.index("readonly property bool sourceAvailable") : compare_start])

        lens_start = qml.index("id: sourceLens")
        lens_end = qml.index("id: documentFrame", lens_start)
        lens = qml[lens_start:lens_end]
        for contract in (
            '{ label: "Fit", value: 0 }',
            '{ label: "2×", value: 2 }',
            '{ label: "4×", value: 4 }',
            "id: sourceFlick",
            "interactive: true",
            "id: sourceImage",
            'source: root.sourceViewVisible ? root.sourceUri : ""',
            "cache: false",
            "asynchronous: true",
            "sourceImage.status === Image.Loading",
            "sourceImage.status === Image.Error",
            "Accessible.name: \"Temporary source image\"",
        ):
            self.assertIn(contract, lens)
        self.assertNotIn("Process {", lens)
        self.assertNotIn("grim", lens)

        keys_start = qml.index("Keys.onPressed: function(event)")
        keys_end = qml.index("if (!root.readerVisible) return", keys_start)
        keys = qml[keys_start:keys_end]
        self.assertIn("if (root.sourceViewVisible) root.showText()", keys)
        self.assertIn("root.adjustSourceZoom(1)", keys)
        self.assertIn("root.adjustSourceZoom(-1)", keys)
        self.assertIn("root.setSourceZoom(0)", keys)
        self.assertIn("root.panSource", keys)
        self.assertIn("Qt.ShiftModifier", keys)

    def test_safe_demo_cannot_overlap_a_workflow_process(self):
        qml = (ROOT / "ClearRead.qml").read_text(encoding="utf-8")
        start = qml.index("function showDemo()")
        end = qml.index("function retryDoctor()", start)
        demo_function = qml[start:end]
        self.assertIn("pendingOpen", demo_function)
        self.assertIn("processesBusy()", demo_function)
        self.assertIn("copyStartPending", demo_function)
        self.assertIn("sourceHeld", demo_function)
        self.assertIn("captureProcess.running", demo_function)
        self.assertNotIn("releaseSource()", demo_function)

    def test_ipc_distinguishes_blocking_work_from_live_holder_processes(self):
        qml = (ROOT / "ClearRead.qml").read_text(encoding="utf-8")
        running_start = qml.index("function processesRunning()")
        running_end = qml.index("function discardSource()", running_start)
        running = qml[running_start:running_end]
        self.assertIn("captureProcess.running", running)
        self.assertNotIn("sourceHeld", running)
        state_start = qml.index("function state(): string")
        state_end = qml.index("function ping(): string", state_start)
        state = qml[state_start:state_end]
        self.assertIn("running: root.processesRunning()", state)
        self.assertIn("sourceHeld: root.sourceHeld", state)

    def test_pending_reopen_has_one_synchronous_owner(self):
        qml = (ROOT / "ClearRead.qml").read_text(encoding="utf-8")
        open_start = qml.index("function open(payloadJson)")
        open_end = qml.index("function close()", open_start)
        resume_start = qml.index("function resumePendingOpen()")
        resume_end = qml.index("function requestReaderFocus()", resume_start)
        self.assertLess(qml[open_start:open_end].index("if (pendingOpen)"), qml[open_start:open_end].index("if (opened"))
        self.assertIn("beginOpen(payload)", qml[resume_start:resume_end])
        self.assertNotIn("Qt.callLater", qml[resume_start:resume_end])

    def test_source_has_no_network_client_or_shell_interpolation(self):
        code = "\n".join(
            path.read_text(encoding="utf-8", errors="replace")
            for path in [ROOT / "bin/clearread", ROOT / "lib/clearread.py", ROOT / "ClearRead.qml"]
        )
        for forbidden in ["urllib", "requests.", "HTTPConnection", "shell=True", "Qt.openUrlExternally"]:
            self.assertNotIn(forbidden, code)

    def test_bash_uses_current_omarchy_style(self):
        for script in (ROOT / "scripts").glob("*.sh"):
            source = script.read_text(encoding="utf-8")
            self.assertTrue(source.startswith("#!/bin/bash"), script.name)
            self.assertIsNone(re.search(r"(^|[; ])\[ ", source, re.MULTILINE), script.name)

    def test_acceptance_runner_fails_closed_and_exercises_both_ocr_paths(self):
        source = (ROOT / "scripts/acceptance-test.sh").read_text(encoding="utf-8")
        for contract in (
            'bash "$ROOT/scripts/validate.sh"',
            'XDG_SESSION_TYPE:-',
            'HYPRLAND_INSTANCE_SIGNATURE:-',
            'trap cleanup EXIT',
            "trap 'exit 130' INT",
            "trap 'exit 143' TERM",
            'if [[ ! -t 0 ]]',
            'run_real_capture window',
            'run_real_capture region',
            'state.get("mode") == expected_mode',
            'state.get("sourceHeld") is True',
            'state.get("sourceView") is True',
            'state.get("sourceHeld") is False',
            'state.get("sourceView") is False',
            'inspect Fit, 2x, and 4x',
        ):
            self.assertIn(contract, source)


if __name__ == "__main__":
    unittest.main()
