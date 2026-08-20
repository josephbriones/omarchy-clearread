import contextlib
import fcntl
import io
import json
import os
from pathlib import Path
import re
import signal
import struct
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from unittest import mock
import zlib


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import clearread


def png_chunk(chunk_type, data):
  return (
    struct.pack(">I", len(data))
    + chunk_type
    + data
    + struct.pack(">I", zlib.crc32(chunk_type + data) & 0xffffffff)
  )


def png_image(width=800, height=600, trailer=b"local-image-bytes"):
  data = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
  return (
    clearread.PNG_SIGNATURE
    + png_chunk(b"IHDR", data)
    + trailer
  )


MEMFD_SEALS_SUPPORTED = (
  sys.platform.startswith("linux")
  and hasattr(os, "memfd_create")
  and all(hasattr(os, name) for name in ("MFD_CLOEXEC", "MFD_ALLOW_SEALING"))
  and all(
    hasattr(fcntl, name)
    for name in (
      "F_ADD_SEALS", "F_GET_SEALS", "F_SEAL_WRITE", "F_SEAL_GROW",
      "F_SEAL_SHRINK", "F_SEAL_SEAL",
    )
  )
)


class ClearReadTests(unittest.TestCase):
  def setUp(self):
    self.temporary_directory = tempfile.TemporaryDirectory()
    self.sandbox = Path(self.temporary_directory.name)
    self.fake_bin = self.sandbox / "bin"
    self.omarchy_path = self.sandbox / "omarchy"
    self.fake_bin.mkdir()
    (self.omarchy_path / "bin").mkdir(parents=True)
    self._install_fake_commands()
    clearread.CHILDREN.cancelled.clear()

  def tearDown(self):
    clearread.CHILDREN.cancel()
    clearread.CHILDREN.processes.clear()
    clearread.CHILDREN.cancelled.clear()
    self.temporary_directory.cleanup()

  def script(self, path, body):
    path.write_text(
      f"#!{sys.executable}\n" + textwrap.dedent(body).lstrip(),
      encoding="utf-8",
    )
    path.chmod(0o755)

  def _install_fake_commands(self):
    self.script(self.fake_bin / "setpriv", """
      import json
      import os
      from pathlib import Path
      import sys

      arguments = sys.argv[1:]
      log = os.environ.get("FAKE_SETPRIV_LOG")
      if log:
        with Path(log).open("a", encoding="utf-8") as stream:
          stream.write(json.dumps(arguments) + "\\n")
      if arguments[:3] != ["--pdeathsig", "TERM", "--"] or len(arguments) < 4:
        raise SystemExit(64)
      os.execvp(arguments[3], arguments[3:])
    """)

    self.script(self.fake_bin / "hyprctl", """
      import os
      import sys

      arguments = sys.argv[1:]
      if arguments == ["activewindow", "-j"]:
        sys.stdout.write(os.environ["FAKE_WINDOW_JSON"])
      elif arguments == ["monitors", "-j"]:
        if os.environ.get("FAKE_MONITORS_FAIL") == "1":
          raise SystemExit(70)
        sys.stdout.write(os.environ["FAKE_MONITORS_JSON"])
      else:
        raise SystemExit(64)
    """)

    self.script(self.fake_bin / "grim", """
      import os
      from pathlib import Path
      import struct
      import sys
      import zlib

      expected = ["-g", os.environ.get("FAKE_EXPECT_GEOMETRY", "40,50 800x600"), "-"]
      if sys.argv[1:] != expected:
        raise SystemExit(64)
      freeze_file = os.environ.get("FAKE_FREEZE_PID_FILE")
      if os.environ.get("FAKE_REQUIRE_FREEZE") == "1":
        if not freeze_file or not Path(freeze_file).is_file():
          raise SystemExit(65)
        try:
          os.kill(int(Path(freeze_file).read_text(encoding="ascii")), 0)
        except (ProcessLookupError, ValueError):
          raise SystemExit(66)
        Path(os.environ["FAKE_GRIM_SAW_FREEZE"]).write_text("alive", encoding="ascii")
      image_file = os.environ.get("FAKE_IMAGE_FILE")
      if image_file:
        image = Path(image_file).read_bytes()
      else:
        width = int(os.environ.get("FAKE_PNG_WIDTH", "800"))
        height = int(os.environ.get("FAKE_PNG_HEIGHT", "600"))
        data = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
        crc = zlib.crc32(b"IHDR" + data) & 0xffffffff
        image = (
          b"\\x89PNG\\r\\n\\x1a\\n"
          + struct.pack(">I", len(data))
          + b"IHDR"
          + data
          + struct.pack(">I", crc)
          + b"local-image-bytes"
        )
      sys.stdout.buffer.write(image)
    """)

    self.script(self.fake_bin / "tesseract", """
      import os
      import sys

      if sys.argv[1:] == ["--list-langs"]:
        languages = os.environ.get("FAKE_LANGUAGES", "eng,spa").split(",")
        print("List of available languages in /fake (" + str(len(languages)) + "):")
        print("\\n".join(languages))
        raise SystemExit(0)

      expected = [
        "stdin", "stdout", "--oem", "1", "--psm", "6", "-l",
        os.environ.get("FAKE_EXPECT_LANGUAGE", "eng"), "--dpi", "300", "-c",
        "preserve_interword_spaces=1",
      ]
      if sys.argv[1:] != expected:
        raise SystemExit(64)
      image = sys.stdin.buffer.read()
      if not image.startswith(b"\\x89PNG\\r\\n\\x1a\\n"):
        raise SystemExit(65)
      sys.stdout.write(os.environ.get("FAKE_OCR_TEXT", "First wrapped\\nparagraph.\\n\\n• One\\ncontinued\\n• Two"))
    """)

    self.script(self.fake_bin / "wl-paste", """
      import os
      import sys

      if sys.argv[1:] != ["--no-newline", "--type", "text"]:
        raise SystemExit(64)
      sys.stdout.write(os.environ.get("FAKE_CLIPBOARD", "Clipboard\\nparagraph"))
    """)

    self.script(self.fake_bin / "wl-copy", """
      import json
      import os
      from pathlib import Path
      import sys
      import time

      Path(os.environ["FAKE_COPY_TEXT"]).write_bytes(sys.stdin.buffer.read())
      Path(os.environ["FAKE_COPY_ARGS"]).write_text(json.dumps(sys.argv[1:]), encoding="utf-8")
      provider_file = os.environ.get("FAKE_COPY_PROVIDER_PID")
      if provider_file:
        provider = os.fork()
        if provider == 0:
          Path(provider_file).write_text(str(os.getpid()), encoding="ascii")
          time.sleep(10)
          os._exit(0)
    """)

    self.script(self.omarchy_path / "bin" / "omarchy-capture-region", """
      import os
      from pathlib import Path
      import signal
      import subprocess
      import sys

      if sys.argv[1:] != ["smart", "--keep-freeze"]:
        raise SystemExit(64)
      if os.environ.get("FAKE_PICKER_CRASH") == "1":
        raise SystemExit(2)
      frozen = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        preexec_fn=(lambda: signal.signal(signal.SIGTERM, signal.SIG_IGN))
          if os.environ.get("FAKE_FREEZE_IGNORE_TERM") == "1" else None,
      )
      freeze_file = os.environ.get("FAKE_FREEZE_PID_FILE")
      if freeze_file:
        Path(freeze_file).write_text(str(frozen.pid), encoding="ascii")
      print(os.environ.get("FAKE_STALE_FREEZE_PID", str(frozen.pid)), flush=True)
      if os.environ.get("FAKE_PICKER_CANCEL") == "1":
        raise SystemExit(1)
      print(os.environ.get("FAKE_REGION_GEOMETRY", "40,50 800x600"))
    """)

  def environment(self):
    return {
      "PATH": str(self.fake_bin),
      "WAYLAND_DISPLAY": "wayland-1",
      "FAKE_WINDOW_JSON": json.dumps({"at": [40, 50], "size": [800, 600]}),
      "FAKE_MONITORS_JSON": json.dumps([
        {
          "name": "DP-1",
          "x": 0,
          "y": 0,
          "width": 1920,
          "height": 1080,
          "scale": 1,
          "transform": 0,
          "focused": True,
        }
      ]),
      "FAKE_EXPECT_GEOMETRY": "40,50 800x600",
      "FAKE_EXPECT_LANGUAGE": "eng",
      "FAKE_LANGUAGES": "eng,spa",
      "FAKE_OCR_TEXT": "First wrapped\nparagraph.\n\n• One\ncontinued\n• Two",
      "FAKE_CLIPBOARD": "Clipboard\nparagraph",
      "FAKE_FREEZE_PID_FILE": str(self.sandbox / "freeze-pid"),
      "PYTHONDONTWRITEBYTECODE": "1",
    }

  def launcher_command(self, *arguments):
    return [
      sys.executable,
      str(ROOT / "bin" / "clearread"),
      "--shell-pid",
      str(os.getpid()),
      *arguments,
    ]

  def run_cli(self, *arguments, input_bytes=None, environment=None, timeout=5):
    command_environment = self.environment()
    if environment:
      command_environment.update(environment)
    if input_bytes is None and "capture" in arguments:
      try:
        mode = arguments[arguments.index("--mode") + 1]
      except (ValueError, IndexError):
        mode = None
      if mode in ("window", "region"):
        input_bytes = clearread.SOURCE_RELEASE
    return subprocess.run(
      self.launcher_command(*arguments),
      input=input_bytes,
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
      cwd=self.sandbox,
      env=command_environment,
      timeout=timeout,
      check=False,
    )

  def events(self, process):
    return [json.loads(line) for line in process.stdout.decode("utf-8").splitlines()]

  def assert_error_code(self, expected, action):
    with self.assertRaises(clearread.ClearReadError) as caught:
      action()
    self.assertEqual(caught.exception.code, expected)

  def test_reflow_preserves_paragraphs_lists_and_unicode(self):
    source = "Wrapped\nprose\n\n1. First\ncontinued\n2) Second\n\nمی\u200cروم क्ष\u200dत्र e\u0301"
    text = clearread.reflow_text(source)

    self.assertEqual(text, "\n\n".join([
      "Wrapped prose",
      "1. First continued",
      "2) Second",
      "می\u200cروم क्ष\u200dत्र e\u0301",
    ]))
    self.assertIn("\u200c", text)
    self.assertIn("\u200d", text)
    self.assertIn("\u0301", text)

  def test_reflow_keeps_hyphens_without_inventing_or_deleting_characters(self):
    text = clearread.reflow_text(
      "long-\nterm\n\nAnne-\nMarie\n\nhttps://example.test/a-\nb"
    )

    self.assertEqual(text, "long-term\n\nAnne-Marie\n\nhttps://example.test/a-b")

  def test_reflow_strips_controls_but_keeps_joiners_and_marks(self):
    text = clearread.reflow_text("A\x00\u202eB\u200c\u200d\u0301\x85C")

    self.assertEqual(text, "AB\u200c\u200d\u0301C")

  def test_reflow_rejects_oversized_documents_and_paragraph_sets(self):
    with mock.patch.object(clearread, "MAX_TEXT_CHARACTERS", 3):
      with self.assertRaisesRegex(clearread.ClearReadError, "too much text"):
        clearread.reflow_text("four")
    with mock.patch.object(clearread, "MAX_PARAGRAPHS", 1):
      with self.assertRaisesRegex(clearread.ClearReadError, "too many paragraphs"):
        clearread.reflow_text("one\n\ntwo")

  def test_language_validation_matches_the_qml_boundary(self):
    for language in ("eng", "eng+spa", "chi_sim", "123"):
      self.assertEqual(clearread.validate_language(language), language)
    for language in ("", "eng;touch", "script/Latin", "eng-spa", "eng spa", "a" * 121):
      with self.assertRaises(clearread.ClearReadError, msg=language):
        clearread.validate_language(language)

  def test_geometry_validation_accepts_negative_desktops_and_rejects_bad_bounds(self):
    self.assertEqual(clearread.normalize_geometry("-1920,20 1920x1080"), "-1920,20 1920x1080")
    for geometry in (
      "0,0 0x10",
      "0,0 -1x10",
      "0,0 100001x1",
      "1000001,0 10x10",
      "0,0 20000x20000",
      "0,0 10x10 extra",
      "$(touch nope)",
    ):
      with self.assertRaises(clearread.ClearReadError, msg=geometry):
        clearread.parse_geometry(geometry)

  def test_monitor_matching_handles_scale_transform_and_overlap(self):
    monitors = [
      {
        "name": "LEFT",
        "x": -1080,
        "y": 0,
        "width": 1920,
        "height": 1080,
        "scale": 1,
        "transform": 1,
        "focused": False,
      },
      {
        "name": "MAIN",
        "x": 0,
        "y": 0,
        "width": 3840,
        "height": 2160,
        "scale": 2,
        "transform": 0,
        "focused": True,
      },
    ]

    self.assertEqual(clearread.monitor_for_geometry(monitors, "100,100 500x500"), "MAIN")
    self.assertEqual(clearread.monitor_for_geometry(monitors, "-1000,100 500x500"), "LEFT")

  def test_monitor_rectangle_covers_every_wayland_transform(self):
    for transform in range(8):
      with self.subTest(transform=transform):
        rectangle = clearread._monitor_rectangle({
          "x": -20,
          "y": 30,
          "width": 1200,
          "height": 800,
          "scale": 2,
          "transform": transform,
        })
        dimensions = (400, 600) if transform in (1, 3, 5, 7) else (600, 400)
        self.assertEqual(rectangle, (-20, 30, *dimensions))

  def test_monitor_rectangle_rejects_nonfinite_scaled_dimensions(self):
    for width, scale in ((1e308, 5e-324), (10**1000, 1), (1000, 10**1000)):
      with self.subTest(width=width, scale=scale):
        self.assertIsNone(clearread._monitor_rectangle({
          "x": 0,
          "y": 0,
          "width": width,
          "height": width,
          "scale": scale,
          "transform": 0,
        }))

  def test_window_capture_orders_visibility_sensitive_events_and_returns_text(self):
    process = self.run_cli(
      "capture", "--mode", "window",
      "--omarchy-path", str(self.omarchy_path),
      "--language", "eng",
    )

    self.assertEqual(process.returncode, 0, process.stderr.decode())
    events = self.events(process)
    self.assertEqual([(event["type"], event.get("state")) for event in events], [
      ("status", "capturing"),
      ("status", "recognizing"),
      ("result", None),
    ])
    self.assertEqual(set(events[0]), {"type", "state", "mode"})
    self.assertEqual(set(events[1]), {"type", "state", "mode", "monitor"})
    result = events[-1]
    self.assertEqual(result["mode"], "window")
    self.assertEqual(result["monitor"], "DP-1")
    self.assertEqual(result["text"], "First wrapped paragraph.\n\n• One continued\n\n• Two")
    self.assertEqual(
      set(result) - {"source"},
      {"type", "mode", "text", "monitor"},
    )

  @unittest.skipUnless(MEMFD_SEALS_SUPPORTED, "requires Linux sealed memfd support")
  def test_source_lens_retains_exact_sealed_capture_until_exact_release(self):
    pixels = b"\0\xff\x00\x00\xff\x00\x00\xff\xff"
    image = png_image(
      2,
      1,
      png_chunk(b"IDAT", zlib.compress(pixels)) + png_chunk(b"IEND", b""),
    )
    image_file = self.sandbox / "source.png"
    image_file.write_bytes(image)
    environment = self.environment()
    environment["FAKE_IMAGE_FILE"] = str(image_file)
    process = subprocess.Popen(
      self.launcher_command(
        "capture", "--mode", "window",
        "--omarchy-path", str(self.omarchy_path),
        "--language", "eng",
      ),
      stdin=subprocess.PIPE,
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
      cwd=self.sandbox,
      env=environment,
    )

    source_path = None
    try:
      events = [json.loads(process.stdout.readline()) for _ in range(3)]
      result = events[-1]
      self.assertEqual(result["type"], "result")
      source = result["source"]
      self.assertEqual(set(source), {"uri", "width", "height"})
      self.assertEqual((source["width"], source["height"]), (2, 1))

      match = re.fullmatch(r"file:///proc/([1-9]\d*)/fd/(\d+)", source["uri"])
      self.assertIsNotNone(match)
      self.assertNotEqual(int(match.group(1)), process.pid)
      source_path = Path(source["uri"][7:])
      self.assertEqual(source_path.read_bytes(), image)

      descriptor = os.open(source_path, os.O_RDONLY)
      try:
        expected_seals = (
          fcntl.F_SEAL_WRITE
          | fcntl.F_SEAL_GROW
          | fcntl.F_SEAL_SHRINK
          | fcntl.F_SEAL_SEAL
        )
        self.assertEqual(fcntl.fcntl(descriptor, fcntl.F_GET_SEALS), expected_seals)
      finally:
        os.close(descriptor)

      process.stdin.write(b"release\r\n")
      process.stdin.flush()
      time.sleep(0.15)
      self.assertIsNone(process.poll(), "an inexact release disposed the source")

      process.stdin.write(clearread.SOURCE_RELEASE)
      process.stdin.flush()
      process.stdin.close()
      process.wait(timeout=2)
      errors = process.stderr.read()
      self.assertEqual(process.returncode, 0, errors.decode())
      self.assertFalse(source_path.exists())
    finally:
      if process.poll() is None:
        try:
          process.stdin.write(clearread.SOURCE_RELEASE)
          process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
          pass
        try:
          process.wait(timeout=1)
        except subprocess.TimeoutExpired:
          process.kill()
          process.wait(timeout=2)
      for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None and not stream.closed:
          stream.close()

  @unittest.skipUnless(MEMFD_SEALS_SUPPORTED, "requires Linux sealed memfd support")
  def test_source_lens_cancellation_closes_the_descriptor_promptly(self):
    process = subprocess.Popen(
      self.launcher_command(
        "capture", "--mode", "window",
        "--omarchy-path", str(self.omarchy_path),
        "--language", "eng",
      ),
      stdin=subprocess.PIPE,
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
      cwd=self.sandbox,
      env=self.environment(),
    )

    source_path = None
    try:
      result = [json.loads(process.stdout.readline()) for _ in range(3)][-1]
      source_path = Path(result["source"]["uri"][7:])
      self.assertTrue(source_path.exists())

      started = time.monotonic()
      process.send_signal(signal.SIGTERM)
      process.wait(timeout=2)
      elapsed = time.monotonic() - started
      remaining_output = process.stdout.read()
      errors = process.stderr.read()

      self.assertEqual(process.returncode, 130, errors.decode())
      self.assertLess(elapsed, 0.75)
      self.assertEqual(json.loads(remaining_output), {
        "type": "cancelled",
        "mode": "window",
      })
      self.assertFalse(source_path.exists())
    finally:
      if process.poll() is None:
        process.kill()
        process.communicate(timeout=2)
      for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None and not stream.closed:
          stream.close()

  @unittest.skipUnless(MEMFD_SEALS_SUPPORTED, "requires Linux sealed memfd support")
  def test_launcher_sigkill_releases_a_held_source_descriptor(self):
    launcher = subprocess.Popen(
      self.launcher_command(
        "capture", "--mode", "window",
        "--omarchy-path", str(self.omarchy_path),
        "--language", "eng",
      ),
      stdin=subprocess.PIPE,
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
      cwd=self.sandbox,
      env=self.environment(),
    )

    try:
      result = [json.loads(launcher.stdout.readline()) for _ in range(3)][-1]
      source_path = Path(result["source"]["uri"][7:])
      worker_pid = int(source_path.parts[2])
      self.assertTrue(source_path.exists())
      self.assertIsNone(launcher.poll())

      launcher.kill()
      launcher.wait(timeout=2)

      self.assertEqual(launcher.returncode, -signal.SIGKILL)
      self.assert_pid_stopped(worker_pid, timeout=3)
      self.assertFalse(source_path.exists())
    finally:
      if launcher.poll() is None:
        launcher.kill()
        launcher.wait(timeout=2)
      for stream in (launcher.stdin, launcher.stdout, launcher.stderr):
        if stream is not None and not stream.closed:
          stream.close()

  @unittest.skipUnless(MEMFD_SEALS_SUPPORTED, "requires Linux sealed memfd support")
  def test_source_lens_stdin_eof_releases_the_descriptor(self):
    process = subprocess.Popen(
      self.launcher_command(
        "capture", "--mode", "window",
        "--omarchy-path", str(self.omarchy_path),
        "--language", "eng",
      ),
      stdin=subprocess.PIPE,
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
      cwd=self.sandbox,
      env=self.environment(),
    )

    try:
      result = [json.loads(process.stdout.readline()) for _ in range(3)][-1]
      source_path = Path(result["source"]["uri"][7:])
      self.assertTrue(source_path.exists())

      process.stdin.close()
      process.wait(timeout=2)

      errors = process.stderr.read()
      self.assertEqual(process.returncode, 0, errors.decode())
      self.assertFalse(source_path.exists())
    finally:
      if process.poll() is None:
        process.kill()
        process.wait(timeout=2)
      for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None and not stream.closed:
          stream.close()

  def test_source_lens_omits_oversized_images_and_clipboard_content(self):
    oversized = self.run_cli(
      "capture", "--mode", "window",
      "--omarchy-path", str(self.omarchy_path),
      "--language", "eng",
      environment={"FAKE_PNG_WIDTH": "7681", "FAKE_PNG_HEIGHT": "4320"},
    )
    clipboard = self.run_cli(
      "capture", "--mode", "clipboard",
      "--omarchy-path", str(self.omarchy_path),
      "--language", "eng",
    )

    self.assertEqual(oversized.returncode, 0, oversized.stderr.decode())
    self.assertNotIn("source", self.events(oversized)[-1])
    self.assertEqual(clipboard.returncode, 0, clipboard.stderr.decode())
    self.assertNotIn("source", self.events(clipboard)[-1])

  def test_region_capture_uses_the_absolute_native_smart_picker(self):
    freeze_pid_file = self.sandbox / "freeze-pid"
    grim_saw_freeze = self.sandbox / "grim-saw-freeze"
    process = self.run_cli(
      "capture", "--mode", "region",
      "--omarchy-path", str(self.omarchy_path),
      "--language", "eng",
      environment={
        "FAKE_REQUIRE_FREEZE": "1",
        "FAKE_FREEZE_IGNORE_TERM": "1",
        "FAKE_GRIM_SAW_FREEZE": str(grim_saw_freeze),
      },
    )

    self.assertEqual(process.returncode, 0, process.stderr.decode())
    events = self.events(process)
    self.assertEqual([event.get("state") for event in events[:-1]], [
      "selecting", "capturing", "recognizing",
    ])
    self.assertEqual(events[-1]["mode"], "region")
    self.assertEqual(grim_saw_freeze.read_text(encoding="ascii"), "alive")
    self.assert_pid_stopped(int(freeze_pid_file.read_text(encoding="ascii")))

  def test_region_picker_escape_is_a_cancellation_not_an_error(self):
    process = self.run_cli(
      "capture", "--mode", "region",
      "--omarchy-path", str(self.omarchy_path),
      "--language", "eng",
      environment={"FAKE_PICKER_CANCEL": "1"},
    )

    self.assertEqual(process.returncode, 130)
    self.assertEqual(self.events(process), [
      {"type": "status", "state": "selecting", "mode": "region"},
      {"type": "cancelled", "mode": "region"},
    ])
    freeze_pid = int((self.sandbox / "freeze-pid").read_text(encoding="ascii"))
    self.assert_pid_stopped(freeze_pid)

  def test_region_picker_crash_is_an_error_not_a_user_cancellation(self):
    process = self.run_cli(
      "capture", "--mode", "region",
      "--omarchy-path", str(self.omarchy_path),
      "--language", "eng",
      environment={"FAKE_PICKER_CRASH": "1"},
    )

    self.assertEqual(process.returncode, 1)
    self.assertEqual(self.events(process), [
      {"type": "status", "state": "selecting", "mode": "region"},
      {
        "type": "error",
        "code": "selection_failed",
        "message": "The region picker returned an invalid selection.",
      },
    ])

  def test_pidfd_open_failure_never_signals_an_unleased_pid(self):
    with mock.patch.object(clearread.sys, "platform", "linux"):
      with mock.patch.object(clearread.os, "pidfd_open", create=True, side_effect=OSError("failed")):
        with mock.patch.object(clearread.signal, "pidfd_send_signal", create=True):
          with mock.patch.object(clearread.os, "kill") as kill:
            with self.assertRaises(clearread.ClearReadError) as raised:
              clearread.FrozenScreen(12345, 54321)

    self.assertEqual(raised.exception.code, "selection_failed")
    kill.assert_not_called()

  def test_pidfd_group_mismatch_closes_lease_without_signalling(self):
    with mock.patch.object(clearread.sys, "platform", "linux"):
      with mock.patch.object(clearread.os, "pidfd_open", create=True, return_value=77):
        with mock.patch.object(clearread.os, "getpgid", return_value=999):
          with mock.patch.object(clearread.select, "select", return_value=([], [], [])):
            with mock.patch.object(clearread.os, "close") as close:
              with mock.patch.object(clearread.signal, "pidfd_send_signal", create=True) as send:
                with self.assertRaises(clearread.ClearReadError) as raised:
                  clearread.FrozenScreen(12345, 54321)

    self.assertEqual(raised.exception.code, "selection_failed")
    close.assert_called_once_with(77)
    send.assert_not_called()

  def test_pidfd_poll_failure_closes_lease_without_signalling(self):
    with mock.patch.object(clearread.sys, "platform", "linux"):
      with mock.patch.object(clearread.os, "pidfd_open", create=True, return_value=77):
        with mock.patch.object(clearread.os, "getpgid", return_value=54321):
          with mock.patch.object(clearread.select, "select", side_effect=OSError("failed")):
            with mock.patch.object(clearread.os, "close") as close:
              with mock.patch.object(clearread.signal, "pidfd_send_signal", create=True) as send:
                with self.assertRaises(clearread.ClearReadError) as raised:
                  clearread.FrozenScreen(12345, 54321)

    self.assertEqual(raised.exception.code, "selection_failed")
    close.assert_called_once_with(77)
    send.assert_not_called()

  def test_picker_reap_failure_releases_the_verified_freeze(self):
    picker_group = mock.Mock(pgid=54321)
    picker_group.reap.side_effect = OSError("failed")
    frozen_screen = mock.Mock()
    with mock.patch.object(
      clearread,
      "run_owned",
      return_value=(0, b"12345\n0,0 100x100\n", b"", picker_group),
    ):
      with mock.patch.object(clearread, "FrozenScreen", return_value=frozen_screen):
        with self.assertRaises(clearread.ClearReadError) as raised:
          clearread.region_geometry(str(self.omarchy_path))

    self.assertEqual(raised.exception.code, "selection_failed")
    frozen_screen.close.assert_called_once_with()
    picker_group.terminate.assert_called_once_with()

  def test_picker_rejects_stale_freeze_pid_without_signalling_it(self):
    unrelated = subprocess.Popen(
      [sys.executable, "-c", "import time; time.sleep(60)"],
      stdin=subprocess.DEVNULL,
      stdout=subprocess.DEVNULL,
      stderr=subprocess.DEVNULL,
      start_new_session=True,
    )
    try:
      process = self.run_cli(
        "capture", "--mode", "region",
        "--omarchy-path", str(self.omarchy_path),
        "--language", "eng",
        environment={"FAKE_STALE_FREEZE_PID": str(unrelated.pid)},
      )

      self.assertEqual(process.returncode, 1, process.stderr.decode())
      self.assertEqual(self.events(process)[-1]["code"], "selection_failed")
      self.assertIsNone(unrelated.poll(), "backend signalled an unrelated reused PID")
      actual_freeze = int((self.sandbox / "freeze-pid").read_text(encoding="ascii"))
      self.assert_pid_stopped(actual_freeze)
    finally:
      unrelated.terminate()
      unrelated.wait(timeout=2)

  def test_cancellation_during_grim_releases_the_native_freeze(self):
    grim_started = self.sandbox / "grim-started"
    freeze_pid_file = self.sandbox / "freeze-pid"
    self.script(self.fake_bin / "grim", """
      import os
      from pathlib import Path
      import time

      freeze_pid = int(Path(os.environ["FAKE_FREEZE_PID_FILE"]).read_text(encoding="ascii"))
      os.kill(freeze_pid, 0)
      Path(os.environ["FAKE_GRIM_STARTED"]).write_text("started", encoding="ascii")
      time.sleep(10)
    """)
    environment = self.environment()
    environment["FAKE_GRIM_STARTED"] = str(grim_started)
    process = subprocess.Popen(
      self.launcher_command(
        "capture", "--mode", "region",
        "--omarchy-path", str(self.omarchy_path),
        "--language", "eng",
      ),
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
      cwd=self.sandbox,
      env=environment,
    )

    self.assertEqual(json.loads(process.stdout.readline())["state"], "selecting")
    self.assertEqual(json.loads(process.stdout.readline())["state"], "capturing")
    deadline = time.monotonic() + 2
    while not grim_started.exists() and time.monotonic() < deadline:
      time.sleep(0.01)
    self.assertTrue(grim_started.exists())

    process.send_signal(signal.SIGTERM)
    remaining_output, errors = process.communicate(timeout=3)
    self.assertEqual(process.returncode, 130, errors.decode())
    self.assertEqual(json.loads(remaining_output.decode("utf-8").strip()), {
      "type": "cancelled",
      "mode": "region",
    })
    freeze_pid = int(freeze_pid_file.read_text(encoding="ascii"))
    self.assert_pid_stopped(freeze_pid)

  @unittest.skipUnless(sys.platform.startswith("linux"), "requires Linux parent-death signals")
  def test_launcher_sigkill_cleans_picker_group_during_selection(self):
    worker_pid = self.sandbox / "selection-worker-pid"
    picker_pid = self.sandbox / "selection-picker-pid"
    freeze_pid = self.sandbox / "selection-freeze-pid"
    survivor = self.sandbox / "selection-survivor"
    self.script(self.omarchy_path / "bin" / "omarchy-capture-region", """
      import os
      from pathlib import Path
      import signal
      import subprocess
      import sys
      import time

      Path(os.environ["FAKE_WORKER_PID"]).write_text(str(os.getppid()), encoding="ascii")
      Path(os.environ["FAKE_PICKER_PID"]).write_text(str(os.getpid()), encoding="ascii")
      frozen = subprocess.Popen(
        [
          sys.executable, "-c",
          "import os,signal,time; from pathlib import Path; "
          "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
          "Path(os.environ['FAKE_FREEZE_PID']).write_text(str(os.getpid()), encoding='ascii'); "
          "time.sleep(1); Path(os.environ['FAKE_SURVIVOR']).write_text('orphan'); time.sleep(10)",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
      )
      frozen.wait()
    """)
    environment = self.environment()
    environment.update({
      "FAKE_WORKER_PID": str(worker_pid),
      "FAKE_PICKER_PID": str(picker_pid),
      "FAKE_FREEZE_PID": str(freeze_pid),
      "FAKE_SURVIVOR": str(survivor),
    })
    launcher = subprocess.Popen(
      self.launcher_command(
        "capture", "--mode", "region",
        "--omarchy-path", str(self.omarchy_path),
        "--language", "eng",
      ),
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
      cwd=self.sandbox,
      env=environment,
    )

    self.assertEqual(json.loads(launcher.stdout.readline())["state"], "selecting")
    deadline = time.monotonic() + 2
    while not all(path.exists() for path in (worker_pid, picker_pid, freeze_pid)) \
        and time.monotonic() < deadline:
      time.sleep(0.01)
    self.assertTrue(all(path.exists() for path in (worker_pid, picker_pid, freeze_pid)))

    launcher.kill()
    launcher.communicate(timeout=5)
    self.assertEqual(launcher.returncode, -signal.SIGKILL)
    self.assert_pid_stopped(int(worker_pid.read_text(encoding="ascii")), timeout=3)
    self.assert_pid_stopped(int(picker_pid.read_text(encoding="ascii")), timeout=3)
    self.assert_pid_stopped(int(freeze_pid.read_text(encoding="ascii")), timeout=3)
    time.sleep(1)
    self.assertFalse(survivor.exists(), "frozen picker survived launcher destruction")

  @unittest.skipUnless(sys.platform.startswith("linux"), "requires Linux parent-death signals")
  def test_launcher_sigkill_releases_freeze_during_grim(self):
    worker_pid = self.sandbox / "grim-worker-pid"
    grim_pid = self.sandbox / "grim-child-pid"
    grim_started = self.sandbox / "grim-child-started"
    freeze_pid_file = self.sandbox / "freeze-pid"
    self.script(self.fake_bin / "grim", """
      import os
      from pathlib import Path
      import time

      Path(os.environ["FAKE_WORKER_PID"]).write_text(str(os.getppid()), encoding="ascii")
      Path(os.environ["FAKE_GRIM_PID"]).write_text(str(os.getpid()), encoding="ascii")
      Path(os.environ["FAKE_GRIM_STARTED"]).write_text("started", encoding="ascii")
      time.sleep(10)
    """)
    environment = self.environment()
    environment.update({
      "FAKE_FREEZE_IGNORE_TERM": "1",
      "FAKE_WORKER_PID": str(worker_pid),
      "FAKE_GRIM_PID": str(grim_pid),
      "FAKE_GRIM_STARTED": str(grim_started),
    })
    launcher = subprocess.Popen(
      self.launcher_command(
        "capture", "--mode", "region",
        "--omarchy-path", str(self.omarchy_path),
        "--language", "eng",
      ),
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
      cwd=self.sandbox,
      env=environment,
    )

    self.assertEqual(json.loads(launcher.stdout.readline())["state"], "selecting")
    self.assertEqual(json.loads(launcher.stdout.readline())["state"], "capturing")
    deadline = time.monotonic() + 2
    while not all(path.exists() for path in (worker_pid, grim_pid, grim_started, freeze_pid_file)) \
        and time.monotonic() < deadline:
      time.sleep(0.01)
    self.assertTrue(all(path.exists() for path in (worker_pid, grim_pid, grim_started, freeze_pid_file)))

    launcher.kill()
    launcher.communicate(timeout=5)
    self.assertEqual(launcher.returncode, -signal.SIGKILL)
    self.assert_pid_stopped(int(worker_pid.read_text(encoding="ascii")), timeout=3)
    self.assert_pid_stopped(int(grim_pid.read_text(encoding="ascii")), timeout=3)
    self.assert_pid_stopped(int(freeze_pid_file.read_text(encoding="ascii")), timeout=3)

  @unittest.skipUnless(sys.platform.startswith("linux"), "requires Linux parent-death signals")
  def test_launcher_sigkill_reaps_tesseract_during_recognition(self):
    worker_pid = self.sandbox / "recognition-worker-pid"
    tesseract_pid = self.sandbox / "recognition-child-pid"
    recognition_started = self.sandbox / "recognition-started"
    survivor = self.sandbox / "recognition-survivor"
    self.script(self.fake_bin / "tesseract", """
      import os
      from pathlib import Path
      import signal
      import sys
      import time

      Path(os.environ["FAKE_WORKER_PID"]).write_text(str(os.getppid()), encoding="ascii")
      Path(os.environ["FAKE_TESSERACT_PID"]).write_text(str(os.getpid()), encoding="ascii")
      signal.signal(signal.SIGTERM, signal.SIG_IGN)
      sys.stdin.buffer.read()
      Path(os.environ["FAKE_RECOGNITION_STARTED"]).write_text("started", encoding="ascii")
      time.sleep(1)
      Path(os.environ["FAKE_SURVIVOR"]).write_text("orphan", encoding="ascii")
      time.sleep(10)
    """)
    environment = self.environment()
    environment.update({
      "FAKE_WORKER_PID": str(worker_pid),
      "FAKE_TESSERACT_PID": str(tesseract_pid),
      "FAKE_RECOGNITION_STARTED": str(recognition_started),
      "FAKE_SURVIVOR": str(survivor),
    })
    launcher = subprocess.Popen(
      self.launcher_command(
        "capture", "--mode", "window",
        "--omarchy-path", str(self.omarchy_path),
        "--language", "eng",
      ),
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
      cwd=self.sandbox,
      env=environment,
    )

    self.assertEqual(json.loads(launcher.stdout.readline())["state"], "capturing")
    self.assertEqual(json.loads(launcher.stdout.readline())["state"], "recognizing")
    deadline = time.monotonic() + 2
    while not all(path.exists() for path in (
      worker_pid, tesseract_pid, recognition_started,
    )) and time.monotonic() < deadline:
      time.sleep(0.01)
    self.assertTrue(all(path.exists() for path in (
      worker_pid, tesseract_pid, recognition_started,
    )))

    launcher.kill()
    launcher.communicate(timeout=5)
    self.assertEqual(launcher.returncode, -signal.SIGKILL)
    self.assert_pid_stopped(int(worker_pid.read_text(encoding="ascii")), timeout=3)
    self.assert_pid_stopped(int(tesseract_pid.read_text(encoding="ascii")), timeout=3)
    time.sleep(1)
    self.assertFalse(survivor.exists(), "Tesseract survived launcher destruction")

  def test_request_id_is_echoed_on_every_capture_event(self):
    process = self.run_cli(
      "capture", "--mode", "window",
      "--omarchy-path", str(self.omarchy_path),
      "--language", "eng",
      "--request-id", "42",
    )

    self.assertEqual(process.returncode, 0, process.stderr.decode())
    self.assertTrue(self.events(process))
    self.assertTrue(all(event.get("requestId") == 42 for event in self.events(process)))

  def test_request_id_rejects_noncanonical_or_unbounded_values(self):
    for value in ("0", "-1", "+1", "01", "2147483648", "not-a-number"):
      process = self.run_cli(
        "capture", "--mode", "window",
        "--omarchy-path", str(self.omarchy_path),
        "--language", "eng",
        "--request-id", value,
      )
      self.assertEqual(process.returncode, 2, value)

  def test_clipboard_capture_skips_grim_and_tesseract(self):
    process = self.run_cli(
      "capture", "--mode", "clipboard",
      "--omarchy-path", str(self.omarchy_path),
      "--language", "eng",
      environment={"FAKE_CLIPBOARD": "Existing\nclipboard\n\n• Item"},
    )

    self.assertEqual(process.returncode, 0, process.stderr.decode())
    events = self.events(process)
    self.assertEqual([event["type"] for event in events], ["status", "result"])
    self.assertEqual(events[0]["state"], "capturing")
    self.assertEqual(events[-1]["text"], "Existing clipboard\n\n• Item")
    self.assertEqual(set(events[-1]), {"type", "mode", "text"})

  def test_monitor_metadata_never_blocks_valid_text(self):
    for mode in ("window", "clipboard"):
      with self.subTest(mode=mode):
        process = self.run_cli(
          "capture", "--mode", mode,
          "--omarchy-path", str(self.omarchy_path),
          "--language", "eng",
          environment={"FAKE_MONITORS_FAIL": "1"},
        )

        self.assertEqual(process.returncode, 0, process.stderr.decode())
        result = self.events(process)[-1]
        self.assertEqual(result["type"], "result")
        self.assertNotEqual(result["text"], "")
        self.assertNotIn("monitor", result)

  def test_copy_reads_one_bounded_json_line_and_uses_sensitive_plain_text(self):
    copied_text = self.sandbox / "copied-text"
    copied_args = self.sandbox / "copied-args"
    process = self.run_cli(
      "copy",
      input_bytes=json.dumps({"text": "Visible text\nonly"}).encode("utf-8") + b"\n",
      environment={
        "FAKE_COPY_TEXT": str(copied_text),
        "FAKE_COPY_ARGS": str(copied_args),
      },
    )

    self.assertEqual(process.returncode, 0, process.stderr.decode())
    self.assertEqual(copied_text.read_text(encoding="utf-8"), "Visible text\nonly")
    self.assertEqual(json.loads(copied_args.read_text(encoding="utf-8")), [
      "--type", "text/plain", "--sensitive",
    ])
    self.assertEqual(self.events(process), [])

  def test_copy_returns_after_wl_copy_backgrounds_its_selection_provider(self):
    copied_text = self.sandbox / "provider-copy-text"
    copied_args = self.sandbox / "provider-copy-args"
    provider_pid_file = self.sandbox / "provider-pid"
    provider_pid = None
    started = time.monotonic()

    try:
      process = self.run_cli(
        "copy",
        input_bytes=b'{"text":"Pasteable"}\n',
        environment={
          "FAKE_COPY_TEXT": str(copied_text),
          "FAKE_COPY_ARGS": str(copied_args),
          "FAKE_COPY_PROVIDER_PID": str(provider_pid_file),
        },
      )
      elapsed = time.monotonic() - started

      deadline = time.monotonic() + 2
      while not provider_pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
      self.assertTrue(provider_pid_file.exists(), "clipboard provider did not start")
      provider_pid = int(provider_pid_file.read_text(encoding="ascii"))
      self.assertEqual(process.returncode, 0, process.stderr.decode())
      self.assertLess(elapsed, clearread.COPY_TIMEOUT)
      self.assertTrue(self.pid_is_running(provider_pid))
    finally:
      if provider_pid is not None:
        try:
          os.kill(provider_pid, signal.SIGKILL)
        except ProcessLookupError:
          pass
        self.assert_pid_stopped(provider_pid)

  def test_copy_waiting_for_input_stops_on_launcher_termination(self):
    environment = self.environment()
    process = subprocess.Popen(
      self.launcher_command("copy"),
      stdin=subprocess.PIPE,
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
      cwd=self.sandbox,
      env=environment,
    )

    try:
      time.sleep(0.2)
      process.send_signal(signal.SIGTERM)
      process.wait(timeout=2)
    finally:
      if process.poll() is None:
        process.kill()
        process.wait(timeout=2)
      process.stdin.close()
    output = process.stdout.read()
    errors = process.stderr.read()
    process.stdout.close()
    process.stderr.close()

    self.assertEqual(process.returncode, 130, errors.decode())
    self.assertEqual(json.loads(output.decode("utf-8")), {
      "type": "cancelled",
      "mode": None,
    })

  def test_copy_rejects_invalid_and_oversized_requests_before_wl_copy(self):
    for request in (b"not-json\n", b"[]\n", b'{"other":"text"}\n'):
      process = self.run_cli("copy", input_bytes=request)
      self.assertEqual(process.returncode, 1)
      self.assertEqual(self.events(process)[-1]["code"], "invalid_copy_request")

    oversized = b'{"text":"' + b"a" * clearread.MAX_COPY_INPUT_BYTES + b'"}\n'
    process = self.run_cli("copy", input_bytes=oversized)
    self.assertEqual(process.returncode, 1)
    self.assertEqual(self.events(process)[-1]["code"], "copy_too_large")

  def test_png_dimensions_validates_the_complete_ihdr(self):
    self.assertEqual(clearread.png_dimensions(png_image(3840, 2160)), (3840, 2160))

    invalid = [
      clearread.PNG_SIGNATURE,
      png_image(0, 1),
      png_image(1, 0),
      png_image(1, 1)[:29] + b"\0\0\0\0" + png_image(1, 1)[33:],
    ]
    bad_colour = bytearray(png_image(1, 1))
    bad_colour[25] = 5
    bad_colour[29:33] = struct.pack(
      ">I", zlib.crc32(bytes(bad_colour[12:29])) & 0xffffffff,
    )
    invalid.append(bytes(bad_colour))

    for image in invalid:
      with self.subTest(length=len(image)):
        self.assert_error_code("capture_failed", lambda: clearread.png_dimensions(image))

  def test_source_lens_size_limits_precede_memfd_creation(self):
    for image in (png_image(7681, 4320), png_image(32769, 1), png_image(1, 32769)):
      with self.subTest(dimensions=clearread.png_dimensions(image)):
        with mock.patch.object(clearread.os, "memfd_create", create=True) as create:
          self.assertIsNone(clearread.retain_source_image(image))
        create.assert_not_called()

  @unittest.skipUnless(MEMFD_SEALS_SUPPORTED, "requires Linux sealed memfd support")
  def test_source_lens_memfd_failure_is_optional_and_leak_free(self):
    image = png_image(1, 1)
    with mock.patch.object(clearread.os, "memfd_create", side_effect=OSError("unsupported")):
      self.assertIsNone(clearread.retain_source_image(image))

    created = []
    create_memfd = clearread.os.memfd_create

    def remember_memfd(name, flags):
      descriptor = create_memfd(name, flags)
      created.append(descriptor)
      return descriptor

    with mock.patch.object(clearread.os, "memfd_create", side_effect=remember_memfd):
      with mock.patch.object(clearread.fcntl, "fcntl", side_effect=OSError("failed")):
        self.assertIsNone(clearread.retain_source_image(image))

    self.assertEqual(len(created), 1)
    with self.assertRaises(OSError):
      os.fstat(created[0])

  @unittest.skipUnless(MEMFD_SEALS_SUPPORTED, "requires Linux sealed memfd support")
  def test_source_lens_close_is_idempotent_and_does_not_leak_fds(self):
    before = len(os.listdir("/proc/self/fd"))
    for _ in range(8):
      source = clearread.retain_source_image(png_image(1, 1))
      self.assertIsNotNone(source)
      self.assertEqual(os.pread(source.descriptor, 4096, 0), png_image(1, 1))
      descriptor_flags = fcntl.fcntl(source.descriptor, fcntl.F_GETFD)
      self.assertTrue(descriptor_flags & fcntl.FD_CLOEXEC)
      descriptor = source.descriptor
      source.close()
      source.close()
      with self.assertRaises(OSError):
        os.fstat(descriptor)
    after = len(os.listdir("/proc/self/fd"))

    self.assertEqual(after, before)

  def test_capture_failure_family_has_stable_error_codes(self):
    failures = (
      (clearread.CommandTimeout(), "capture_timeout"),
      (clearread.OutputLimitExceeded(), "capture_too_large"),
    )
    for failure, code in failures:
      with self.subTest(code=code):
        with mock.patch.object(clearread, "run_owned", side_effect=failure):
          self.assert_error_code(code, lambda: clearread.capture_png("0,0 10x10"))

    for response in (
      (1, b"", b"failed"),
      (0, b"not-a-png", b""),
      (0, clearread.PNG_SIGNATURE + b"not-an-ihdr", b""),
    ):
      with self.subTest(response=response[0:2]):
        with mock.patch.object(clearread, "run_owned", return_value=response):
          self.assert_error_code(
            "capture_failed", lambda: clearread.capture_png("0,0 10x10"),
          )

  def test_recognition_failure_family_has_stable_error_codes(self):
    failures = (
      (clearread.CommandTimeout(), "recognition_timeout"),
      (clearread.OutputLimitExceeded(), "text_too_large"),
    )
    for failure, code in failures:
      with self.subTest(code=code):
        with mock.patch.object(clearread, "run_owned", side_effect=failure):
          self.assert_error_code(
            code, lambda: clearread.recognize_image(clearread.PNG_SIGNATURE, "eng"),
          )

    responses = (
      ((1, b"", b"failed"), "recognition_failed"),
      ((0, b" \n\t", b""), "no_text"),
      ((0, "\u202e".encode("utf-8"), b""), "no_text"),
      ((0, b"\xff", b""), "invalid_text"),
    )
    for response, code in responses:
      with self.subTest(code=code):
        with mock.patch.object(clearread, "run_owned", return_value=response):
          self.assert_error_code(
            code, lambda: clearread.recognize_image(clearread.PNG_SIGNATURE, "eng"),
          )

  def test_clipboard_failure_family_has_stable_error_codes(self):
    failures = (
      (clearread.CommandTimeout(), "clipboard_timeout"),
      (clearread.OutputLimitExceeded(), "text_too_large"),
    )
    for failure, code in failures:
      with self.subTest(code=code):
        with mock.patch.object(clearread, "run_owned", side_effect=failure):
          self.assert_error_code(code, clearread.capture_clipboard)

    responses = (
      ((1, b"", b"failed"), "clipboard_unavailable"),
      ((0, b" \n\t", b""), "no_text"),
      ((0, "\u202e".encode("utf-8"), b""), "no_text"),
      ((0, b"\xff", b""), "invalid_text"),
    )
    for response, code in responses:
      with self.subTest(code=code):
        with mock.patch.object(clearread, "run_owned", return_value=response):
          self.assert_error_code(code, clearread.capture_clipboard)

  def test_copy_failure_family_has_stable_error_codes(self):
    request = json.dumps({"text": "Copy me"}).encode("utf-8") + b"\n"
    failures = (
      (clearread.CommandTimeout(), "copy_timeout"),
      ((1, b"", b"failed"), "copy_failed"),
    )
    for failure, code in failures:
      with self.subTest(code=code, failure=type(failure).__name__):
        stdin = mock.Mock(buffer=io.BytesIO(request))
        patch_arguments = {"side_effect": failure} if isinstance(failure, Exception) \
          else {"return_value": failure}
        with mock.patch.object(clearread.sys, "stdin", stdin):
          with mock.patch.object(clearread, "run_owned", **patch_arguments):
            self.assert_error_code(code, clearread.copy_text)

  def test_dependency_and_input_failures_have_stable_error_codes(self):
    with mock.patch.object(clearread.shutil, "which", return_value=None):
      self.assert_error_code(
        "dependency_missing", lambda: clearread.run_owned(["not-installed"]),
      )

    with mock.patch.object(clearread, "_json_command", return_value={}):
      self.assert_error_code("window_unavailable", clearread.active_window_geometry)
    with mock.patch.object(clearread, "_json_command", return_value={}):
      self.assert_error_code("monitor_unavailable", clearread.monitor_data)
    self.assert_error_code("invalid_omarchy_path", lambda: clearread.region_geometry("relative"))
    self.assert_error_code(
      "picker_unavailable", lambda: clearread.region_geometry(str(self.sandbox / "missing")),
    )

  def test_pathological_json_maps_to_stable_errors(self):
    with mock.patch.object(clearread, "run_owned", return_value=(0, b"{}", b"")):
      with mock.patch.object(clearread.json, "loads", side_effect=RecursionError()):
        self.assert_error_code(
          "monitor_unavailable",
          lambda: clearread._json_command(
            ["hyprctl", "monitors", "-j"],
            "monitor_unavailable",
            "ClearRead could not inspect the connected monitors.",
          ),
        )

    request = mock.Mock(buffer=io.BytesIO(b'{"text":"safe"}\n'))
    with mock.patch.object(clearread.sys, "stdin", request):
      with mock.patch.object(clearread.json, "loads", side_effect=RecursionError()):
        self.assert_error_code("invalid_copy_request", clearread.copy_text)

  def test_doctor_reports_bounded_language_aware_capabilities(self):
    environment = self.environment()
    output = io.StringIO()
    with mock.patch.object(clearread.sys, "platform", "linux"):
      with mock.patch.object(clearread.os, "pidfd_open", create=True):
        with mock.patch.object(clearread.signal, "pidfd_send_signal", create=True):
          with mock.patch.dict(os.environ, environment, clear=True):
            with contextlib.redirect_stdout(output):
              return_code = clearread.doctor(str(self.omarchy_path), "eng+spa")

    self.assertEqual(return_code, 0)
    event = json.loads(output.getvalue())
    self.assertTrue(event["ready"])
    self.assertEqual(event["capabilities"], {
      "window": True,
      "region": True,
      "clipboard": True,
      "copy": True,
    })
    self.assertEqual(event["missing"], [])
    self.assertNotIn("checks", event)
    self.assertEqual(set(event), {"type", "ready", "capabilities", "missing", "issues"})

  def test_doctor_keeps_clipboard_available_when_ocr_language_is_missing(self):
    environment = self.environment()
    environment["FAKE_LANGUAGES"] = "eng"
    output = io.StringIO()
    with mock.patch.object(clearread.sys, "platform", "linux"):
      with mock.patch.object(clearread.os, "pidfd_open", create=True):
        with mock.patch.object(clearread.signal, "pidfd_send_signal", create=True):
          with mock.patch.dict(os.environ, environment, clear=True):
            with contextlib.redirect_stdout(output):
              return_code = clearread.doctor(str(self.omarchy_path), "spa")

    event = json.loads(output.getvalue())
    self.assertEqual(return_code, 0)
    self.assertTrue(event["ready"])
    self.assertFalse(event["capabilities"]["window"])
    self.assertFalse(event["capabilities"]["region"])
    self.assertTrue(event["capabilities"]["clipboard"])
    self.assertIn("tesseract-language:spa", event["missing"])

  def test_doctor_does_not_require_hyprctl_for_clipboard_reading(self):
    (self.fake_bin / "hyprctl").chmod(0o644)
    environment = self.environment()
    output = io.StringIO()
    with mock.patch.object(clearread.sys, "platform", "linux"):
      with mock.patch.object(clearread.os, "pidfd_open", create=True):
        with mock.patch.object(clearread.signal, "pidfd_send_signal", create=True):
          with mock.patch.dict(os.environ, environment, clear=True):
            with contextlib.redirect_stdout(output):
              return_code = clearread.doctor(str(self.omarchy_path), "eng")

    event = json.loads(output.getvalue())
    self.assertEqual(return_code, 0)
    self.assertFalse(event["capabilities"]["window"])
    self.assertFalse(event["capabilities"]["region"])
    self.assertTrue(event["capabilities"]["clipboard"])

  def test_owned_commands_use_parent_death_signal_wrapper_on_linux(self):
    log = self.sandbox / "setpriv-log"
    environment = self.environment()
    environment["FAKE_SETPRIV_LOG"] = str(log)
    with mock.patch.object(clearread.sys, "platform", "linux"):
      with mock.patch.dict(os.environ, environment, clear=True):
        return_code, _, _ = clearread.run_owned(
          ["hyprctl", "monitors", "-j"], timeout=1,
        )

    self.assertEqual(return_code, 0)
    arguments = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    self.assertEqual(arguments[:3], ["--pdeathsig", "TERM", "--"])
    self.assertEqual(arguments[3:], ["hyprctl", "monitors", "-j"])

  def test_worker_rejects_an_unexpected_parent_before_arming(self):
    with mock.patch.object(clearread.sys, "platform", "linux"):
      with mock.patch.object(clearread.os, "getppid", return_value=222):
        with self.assertRaises(clearread.Cancelled):
          clearread.arm_parent_death_signal(expected_parent=333)

  def test_launcher_validates_the_declared_shell_parent(self):
    for invalid in ("0", "01", "+1", "-1", "not-a-pid", "2147483648"):
      with self.subTest(invalid=invalid):
        process = subprocess.run(
          [sys.executable, str(ROOT / "bin" / "clearread"), "--shell-pid", invalid],
          stdout=subprocess.PIPE,
          stderr=subprocess.PIPE,
          cwd=self.sandbox,
          env=self.environment(),
          timeout=2,
          check=False,
        )
        self.assertEqual(process.returncode, 2)
        self.assertIn(b"invalid shell process ID", process.stderr)

    if sys.platform.startswith("linux"):
      process = subprocess.run(
        [
          sys.executable,
          str(ROOT / "bin" / "clearread"),
          "--shell-pid",
          "2147483647",
          "doctor",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=self.sandbox,
        env=self.environment(),
        timeout=2,
        check=False,
      )
      self.assertEqual(process.returncode, 130)
      self.assertEqual(process.stdout, b"")

  def test_recognition_timeout_terminates_the_worker(self):
    pid_file = self.sandbox / "ocr-pid"
    self.script(self.fake_bin / "tesseract", """
      import os
      from pathlib import Path
      import sys
      import time

      Path(os.environ["FAKE_OCR_PID"]).write_text(str(os.getpid()), encoding="ascii")
      sys.stdin.buffer.read()
      time.sleep(10)
    """)
    environment = self.environment()
    environment["FAKE_OCR_PID"] = str(pid_file)

    with mock.patch.dict(os.environ, environment, clear=True):
      with mock.patch.object(clearread, "RECOGNITION_TIMEOUT", 0.5):
        with self.assertRaises(clearread.ClearReadError) as raised:
          clearread.recognize_image(clearread.PNG_SIGNATURE + b"image", "eng")

    self.assertEqual(raised.exception.code, "recognition_timeout")
    self.assertTrue(pid_file.is_file())
    self.assert_pid_stopped(int(pid_file.read_text(encoding="ascii")))
    self.assertEqual(clearread.CHILDREN.processes, set())

  def test_signal_cancellation_reaps_the_picker_process_group(self):
    picker_pid = self.sandbox / "picker-pid"
    survivor = self.sandbox / "survivor"
    self.script(self.omarchy_path / "bin" / "omarchy-capture-region", """
      import os
      from pathlib import Path
      import subprocess
      import sys
      import time

      Path(os.environ["FAKE_PICKER_PID"]).write_text(str(os.getpid()), encoding="ascii")
      subprocess.Popen([
        sys.executable, "-c",
        "import pathlib,time; time.sleep(0.7); pathlib.Path(" + repr(os.environ["FAKE_SURVIVOR"]) + ").write_text('orphan')",
      ])
      time.sleep(10)
    """)
    environment = self.environment()
    environment.update({
      "FAKE_PICKER_PID": str(picker_pid),
      "FAKE_SURVIVOR": str(survivor),
    })
    process = subprocess.Popen(
      self.launcher_command(
        "capture", "--mode", "region",
        "--omarchy-path", str(self.omarchy_path),
        "--language", "eng",
      ),
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
      cwd=self.sandbox,
      env=environment,
    )

    first_event = json.loads(process.stdout.readline().decode("utf-8"))
    self.assertEqual(first_event["state"], "selecting")
    deadline = time.monotonic() + 2
    while not picker_pid.exists() and time.monotonic() < deadline:
      time.sleep(0.01)
    self.assertTrue(picker_pid.exists())

    process.send_signal(signal.SIGTERM)
    remaining_output, errors = process.communicate(timeout=3)
    self.assertEqual(process.returncode, 130, errors.decode())
    events = [json.loads(line) for line in remaining_output.decode("utf-8").splitlines()]
    self.assertEqual(events[-1], {"type": "cancelled", "mode": "region"})
    self.assert_pid_stopped(int(picker_pid.read_text(encoding="ascii")))
    time.sleep(0.8)
    self.assertFalse(survivor.exists(), "picker grandchild survived cancellation")

  def test_cancellation_kills_term_ignoring_grandchild_after_leader_exits(self):
    picker_pid = self.sandbox / "picker-leader-pid"
    grandchild_pid = self.sandbox / "ignoring-grandchild-pid"
    survivor = self.sandbox / "ignoring-grandchild-survivor"
    self.script(self.omarchy_path / "bin" / "omarchy-capture-region", """
      import os
      from pathlib import Path
      import subprocess
      import sys
      import time

      Path(os.environ["FAKE_PICKER_PID"]).write_text(str(os.getpid()), encoding="ascii")
      subprocess.Popen([
        sys.executable, "-c",
        "import os,signal,time; from pathlib import Path; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "Path(os.environ['FAKE_GRANDCHILD_PID']).write_text(str(os.getpid()), encoding='ascii'); "
        "time.sleep(0.9); Path(os.environ['FAKE_SURVIVOR']).write_text('orphan'); time.sleep(10)",
      ])
      time.sleep(10)
    """)
    environment = self.environment()
    environment.update({
      "FAKE_PICKER_PID": str(picker_pid),
      "FAKE_GRANDCHILD_PID": str(grandchild_pid),
      "FAKE_SURVIVOR": str(survivor),
    })
    process = subprocess.Popen(
      self.launcher_command(
        "capture", "--mode", "region",
        "--omarchy-path", str(self.omarchy_path),
        "--language", "eng",
      ),
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
      cwd=self.sandbox,
      env=environment,
    )

    first_event = json.loads(process.stdout.readline().decode("utf-8"))
    self.assertEqual(first_event["state"], "selecting")
    deadline = time.monotonic() + 2
    while not grandchild_pid.exists() and time.monotonic() < deadline:
      time.sleep(0.01)
    self.assertTrue(picker_pid.exists())
    self.assertTrue(grandchild_pid.exists(), "grandchild did not arm SIGTERM ignore")

    process.send_signal(signal.SIGTERM)
    remaining_output, errors = process.communicate(timeout=3)
    self.assertEqual(process.returncode, 130, errors.decode())
    events = [json.loads(line) for line in remaining_output.decode("utf-8").splitlines()]
    self.assertEqual(events[-1], {"type": "cancelled", "mode": "region"})
    self.assert_pid_stopped(int(picker_pid.read_text(encoding="ascii")))
    self.assert_pid_stopped(int(grandchild_pid.read_text(encoding="ascii")))
    time.sleep(1)
    self.assertFalse(survivor.exists(), "TERM-ignoring grandchild survived bounded KILL")

  def test_cleanup_never_signals_a_reaped_process_group(self):
    process = mock.Mock()
    process.pid = 424242
    process.returncode = 0

    with mock.patch.object(clearread.os, "killpg") as kill_group:
      clearread._stop_process(process)

    kill_group.assert_not_called()
    process.wait.assert_not_called()

  def test_timeout_kills_pipe_inheriting_grandchild_after_leader_exits(self):
    grandchild_pid = self.sandbox / "orphan-grandchild-pid"
    survivor = self.sandbox / "orphan-grandchild-survivor"
    self.script(self.fake_bin / "leader-exits", """
      import os
      import signal
      import subprocess
      import sys

      subprocess.Popen(
        [
          sys.executable, "-c",
          "import os,time; from pathlib import Path; "
          "Path(os.environ['FAKE_GRANDCHILD_PID']).write_text(str(os.getpid()), encoding='ascii'); "
          "time.sleep(1); Path(os.environ['FAKE_SURVIVOR']).write_text('orphan'); time.sleep(10)",
        ],
        preexec_fn=lambda: signal.signal(signal.SIGTERM, signal.SIG_IGN),
      )
    """)
    environment = self.environment()
    environment.update({
      "FAKE_GRANDCHILD_PID": str(grandchild_pid),
      "FAKE_SURVIVOR": str(survivor),
    })

    with mock.patch.dict(os.environ, environment, clear=True):
      with self.assertRaises(clearread.CommandTimeout):
        clearread.run_owned(["leader-exits"], timeout=0.3)

    self.assertTrue(grandchild_pid.exists(), "grandchild did not start before timeout")
    self.assert_pid_stopped(int(grandchild_pid.read_text(encoding="ascii")))
    time.sleep(0.4)
    self.assertFalse(survivor.exists(), "pipe-inheriting grandchild escaped its owned PGID")
    self.assertEqual(clearread.CHILDREN.processes, set())

  def test_main_cannot_clear_a_signal_latched_during_handler_install(self):
    output = io.StringIO()

    def install_handler(signum, handler):
      if signum == signal.SIGTERM and handler is clearread._cancel:
        handler(signum, None)
      return signal.SIG_DFL

    def observe_cancellation(_mode, _omarchy_path, _language):
      if clearread.CHILDREN.cancelled.is_set():
        raise clearread.Cancelled()
      self.fail("signal installed before a later clear was lost")

    with mock.patch.object(clearread.signal, "signal", side_effect=install_handler):
      with mock.patch.object(clearread, "arm_parent_death_signal"):
        with mock.patch.object(clearread, "capture", side_effect=observe_cancellation):
          with contextlib.redirect_stdout(output):
            return_code = clearread.main([
              "capture", "--mode", "window", "--language", "eng",
              "--request-id", "17",
            ])

    self.assertEqual(return_code, 130)
    self.assertEqual(json.loads(output.getvalue()), {
      "type": "cancelled",
      "requestId": 17,
      "mode": "window",
    })

  def test_signal_cancellation_interrupts_a_child_after_its_pipes_close(self):
    child_pid = self.sandbox / "quiet-child-pid"
    self.script(self.fake_bin / "quiet-hang", """
      import os
      from pathlib import Path
      import time

      Path(os.environ["FAKE_QUIET_PID"]).write_text(str(os.getpid()), encoding="ascii")
      os.close(1)
      os.close(2)
      time.sleep(10)
    """)
    environment = self.environment()
    environment["FAKE_QUIET_PID"] = str(child_pid)
    previous = signal.signal(signal.SIGTERM, clearread._cancel)
    def cancel_after_child_starts():
      deadline = time.monotonic() + 2
      while not child_pid.is_file() and time.monotonic() < deadline:
        time.sleep(0.01)
      if child_pid.is_file():
        os.kill(os.getpid(), signal.SIGTERM)

    cancellation = threading.Thread(target=cancel_after_child_starts, daemon=True)

    try:
      with mock.patch.dict(os.environ, environment, clear=True):
        cancellation.start()
        started = time.monotonic()
        with self.assertRaises(clearread.Cancelled):
          clearread.run_owned(["quiet-hang"], timeout=5)
        elapsed = time.monotonic() - started
    finally:
      cancellation.join(timeout=2.5)
      signal.signal(signal.SIGTERM, previous)
      clearread.CHILDREN.cancelled.clear()

    self.assertFalse(cancellation.is_alive(), "cancellation thread did not settle")
    self.assertLess(elapsed, 1.5)
    self.assertTrue(child_pid.is_file())
    self.assert_pid_stopped(int(child_pid.read_text(encoding="ascii")))
    self.assertEqual(clearread.CHILDREN.processes, set())

  def test_output_limits_stop_unbounded_children(self):
    self.script(self.fake_bin / "spam", """
      import sys
      sys.stdout.buffer.write(b"x" * 4096)
    """)

    with mock.patch.dict(os.environ, self.environment(), clear=True):
      with self.assertRaises(clearread.OutputLimitExceeded):
        clearread.run_owned(["spam"], timeout=1, stdout_limit=32)
    self.assertEqual(clearread.CHILDREN.processes, set())

  def test_selector_setup_failure_stops_the_spawned_child(self):
    self.script(self.fake_bin / "quiet-hang", """
      import time
      time.sleep(10)
    """)

    with mock.patch.dict(os.environ, self.environment(), clear=True):
      with mock.patch.object(clearread.selectors, "DefaultSelector", side_effect=OSError("failed")):
        with self.assertRaises(clearread.ClearReadError) as raised:
          clearread.run_owned(["quiet-hang"], timeout=1)

    self.assertEqual(raised.exception.code, "process_failed")
    self.assertEqual(clearread.CHILDREN.processes, set())

  def test_capture_creates_no_image_text_or_history_artifact(self):
    before = self.snapshot()
    process = self.run_cli(
      "capture", "--mode", "window",
      "--omarchy-path", str(self.omarchy_path),
      "--language", "eng",
    )
    after = self.snapshot()

    self.assertEqual(process.returncode, 0, process.stderr.decode())
    self.assertEqual(after, before)

  def snapshot(self):
    return sorted(
      str(path.relative_to(self.sandbox))
      for path in self.sandbox.rglob("*")
    )

  def pid_is_running(self, pid):
    try:
      os.kill(pid, 0)
    except ProcessLookupError:
      return False

    proc_stat = Path(f"/proc/{pid}/stat")
    if Path("/proc").is_dir():
      try:
        fields = proc_stat.read_text(encoding="ascii", errors="replace").split()
      except (FileNotFoundError, ProcessLookupError):
        return False
      return len(fields) < 3 or fields[2] != "Z"
    try:
      status = subprocess.run(
        ["/bin/ps", "-o", "stat=", "-p", str(pid)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=1,
        check=False,
      ).stdout.decode("ascii", errors="replace").strip()
      return bool(status) and not status.startswith("Z")
    except (OSError, subprocess.TimeoutExpired):
      pass
    return True

  def assert_pid_stopped(self, pid, timeout=1.5):
    deadline = time.monotonic() + timeout
    while self.pid_is_running(pid) and time.monotonic() < deadline:
      time.sleep(0.01)
    self.assertFalse(self.pid_is_running(pid), f"process {pid} is still running")


if __name__ == "__main__":
  unittest.main()
