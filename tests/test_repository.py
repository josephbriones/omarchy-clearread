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
        self.assertGreaterEqual(qml.count("Text.PlainText"), 5)
        self.assertIn("keepLoaded", (ROOT / "manifest.json").read_text(encoding="utf-8"))

    def test_qml_accessibility_controls_keep_native_focus_and_target_size(self):
        qml = (ROOT / "ClearRead.qml").read_text(encoding="utf-8")
        self.assertEqual(qml.count("AccessButton {"), 19)
        self.assertIn("component AccessButton: Button", qml)
        self.assertIn("(44 - fontSize) / 2", qml)
        self.assertIn("target.forceActiveFocus()", qml)
        self.assertIn("readerFontMetrics.lineSpacing * lineHeight", qml)
        self.assertIn("String(Quickshell.processId)", qml)
        self.assertEqual(qml.count('"--shell-pid", root.shellProcessId'), 3)

    def test_safe_demo_cannot_overlap_a_workflow_process(self):
        qml = (ROOT / "ClearRead.qml").read_text(encoding="utf-8")
        start = qml.index("function showDemo()")
        end = qml.index("function retryDoctor()", start)
        demo_function = qml[start:end]
        self.assertIn("pendingOpen", demo_function)
        self.assertIn("processesBusy()", demo_function)
        self.assertIn("copyStartPending", demo_function)

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


if __name__ == "__main__":
    unittest.main()
