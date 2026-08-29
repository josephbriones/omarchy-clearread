import errno
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import clearread_settings as settings


DEFAULTS = {
  "version": 1,
  "fontSize": 28,
  "fontFamily": "system",
  "fontWeight": "regular",
  "lineHeight": 1.5,
  "letterSpacing": 0,
  "wordSpacing": 4,
  "columnWidth": "medium",
  "palette": "paper",
  "focusLines": 0,
}


class SettingsStoreTests(unittest.TestCase):
  def setUp(self):
    self.temporary_directory = tempfile.TemporaryDirectory()
    self.sandbox = Path(self.temporary_directory.name).resolve()
    self.config_home = self.sandbox / "config"
    self.config_home.mkdir(mode=0o700)
    self.environment = {"XDG_CONFIG_HOME": str(self.config_home)}
    self.settings_directory = self.config_home / settings.SETTINGS_DIRECTORY_NAME
    self.settings_file = self.settings_directory / settings.SETTINGS_FILE_NAME

  def tearDown(self):
    self.temporary_directory.cleanup()

  def encoded(self, updates=None):
    value = dict(DEFAULTS)
    value.update(updates or {})
    return json.dumps(value, separators=(",", ":")).encode("ascii")

  def create_directory(self, mode=0o700):
    self.settings_directory.mkdir(mode=mode)

  def test_missing_settings_are_defaults_without_creating_state(self):
    self.assertEqual(settings.load_settings(self.environment), b"{}")
    self.assertFalse(self.settings_directory.exists())

  def test_save_creates_private_state_and_loads_canonical_json(self):
    expected = self.encoded({"fontSize": 56, "palette": "contrast"})
    self.assertEqual(settings.save_settings(expected, self.environment), expected)
    self.assertEqual(settings.load_settings(self.environment), expected)
    self.assertEqual(stat.S_IMODE(self.settings_directory.stat().st_mode), 0o700)
    self.assertEqual(stat.S_IMODE(self.settings_file.stat().st_mode), 0o600)
    self.assertEqual(self.settings_file.read_bytes(), expected + b"\n")
    self.assertEqual(list(self.settings_directory.glob(".settings.*.tmp")), [])

  def test_symlinked_settings_directory_is_rejected(self):
    target = self.config_home / "other"
    target.mkdir(mode=0o700)
    self.settings_directory.symlink_to(target, target_is_directory=True)
    with self.assertRaises(settings.SettingsStoreError):
      settings.load_settings(self.environment)
    with self.assertRaises(settings.SettingsStoreError):
      settings.save_settings(self.encoded(), self.environment)

  def test_symlinked_config_home_and_ancestor_are_rejected(self):
    real_config = self.sandbox / "real-config"
    real_config.mkdir(mode=0o700)
    config_link = self.sandbox / "config-link"
    config_link.symlink_to(real_config, target_is_directory=True)
    with self.assertRaises(settings.SettingsStoreError):
      settings.load_settings({"XDG_CONFIG_HOME": str(config_link)})
    with self.assertRaises(settings.SettingsStoreError):
      settings.save_settings(self.encoded(), {"XDG_CONFIG_HOME": str(config_link)})

    real_ancestor = self.sandbox / "real-ancestor"
    (real_ancestor / "config").mkdir(parents=True, mode=0o700)
    ancestor_link = self.sandbox / "ancestor-link"
    ancestor_link.symlink_to(real_ancestor, target_is_directory=True)
    linked_path = ancestor_link / "config"
    with self.assertRaises(settings.SettingsStoreError):
      settings.load_settings({"XDG_CONFIG_HOME": str(linked_path)})
    with self.assertRaises(settings.SettingsStoreError):
      settings.save_settings(self.encoded(), {"XDG_CONFIG_HOME": str(linked_path)})

  def test_save_safely_creates_missing_config_home_components(self):
    config_home = self.sandbox / "missing" / "nested" / "config"
    environment = {"XDG_CONFIG_HOME": str(config_home)}
    expected = self.encoded({"fontSize": 56})
    settings.save_settings(expected, environment)
    self.assertEqual(
      (config_home / settings.SETTINGS_DIRECTORY_NAME / settings.SETTINGS_FILE_NAME).read_bytes(),
      expected + b"\n",
    )
    for path in (self.sandbox / "missing", self.sandbox / "missing" / "nested", config_home):
      self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)

  def test_symlinked_settings_file_is_rejected_without_touching_target(self):
    self.create_directory()
    target = self.config_home / "target.json"
    original = self.encoded({"fontSize": 32}) + b"\n"
    target.write_bytes(original)
    self.settings_file.symlink_to(target)
    with self.assertRaises(settings.SettingsStoreError):
      settings.load_settings(self.environment)
    with self.assertRaises(settings.SettingsStoreError):
      settings.save_settings(self.encoded({"fontSize": 40}), self.environment)
    self.assertEqual(target.read_bytes(), original)

  @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO support is required")
  def test_fifo_is_rejected_without_blocking_read_or_write(self):
    self.create_directory()
    os.mkfifo(self.settings_file, 0o600)
    started = time.monotonic()
    with self.assertRaises(settings.SettingsStoreError):
      settings.load_settings(self.environment)
    self.assertLess(time.monotonic() - started, 1.0)

    started = time.monotonic()
    with self.assertRaises(settings.SettingsStoreError):
      settings.save_settings(self.encoded(), self.environment)
    self.assertLess(time.monotonic() - started, 1.0)

  def test_oversized_regular_file_is_rejected_before_read(self):
    self.create_directory()
    self.settings_file.write_bytes(b"x" * (settings.MAX_SETTINGS_BYTES + 1))
    with mock.patch.object(settings.os, "read") as read:
      with self.assertRaises(settings.SettingsStoreError):
        settings.load_settings(self.environment)
    read.assert_not_called()

  def test_wrong_file_type_and_multiply_linked_file_are_rejected(self):
    self.create_directory()
    self.settings_file.mkdir()
    with self.assertRaises(settings.SettingsStoreError):
      settings.load_settings(self.environment)
    self.settings_file.rmdir()

    self.settings_file.write_bytes(self.encoded())
    hardlink = self.settings_directory / "linked.json"
    os.link(self.settings_file, hardlink)
    with self.assertRaises(settings.SettingsStoreError):
      settings.load_settings(self.environment)

  def test_wrong_file_owner_is_rejected(self):
    self.create_directory()
    self.settings_file.write_bytes(self.encoded())
    real_fstat = os.fstat

    def mismatched_file_owner(descriptor):
      result = real_fstat(descriptor)
      if not stat.S_ISREG(result.st_mode):
        return result
      return types.SimpleNamespace(
        st_mode=result.st_mode,
        st_uid=result.st_uid + 1,
        st_nlink=result.st_nlink,
        st_size=result.st_size,
      )

    with mock.patch.object(settings.os, "fstat", side_effect=mismatched_file_owner):
      with self.assertRaises(settings.SettingsStoreError):
        settings.load_settings(self.environment)

  def test_wrong_settings_directory_owner_is_rejected(self):
    self.create_directory()
    real_fstat = os.fstat
    directory_count = 0

    def mismatched_settings_directory_owner(descriptor):
      nonlocal directory_count
      result = real_fstat(descriptor)
      if not stat.S_ISDIR(result.st_mode):
        return result
      directory_count += 1
      if directory_count == 1:
        return result
      return types.SimpleNamespace(st_mode=result.st_mode, st_uid=result.st_uid + 1)

    with mock.patch.object(settings.os, "fstat", side_effect=mismatched_settings_directory_owner):
      with self.assertRaises(settings.SettingsStoreError):
        settings.load_settings(self.environment)

  def test_non_private_settings_directory_is_rejected(self):
    self.create_directory(mode=0o755)
    with self.assertRaises(settings.SettingsStoreError):
      settings.load_settings(self.environment)
    with self.assertRaises(settings.SettingsStoreError):
      settings.save_settings(self.encoded(), self.environment)

  def test_atomic_replace_changes_inode_and_leaves_no_temporary_file(self):
    first = self.encoded({"fontSize": 32})
    second = self.encoded({"fontSize": 48})
    settings.save_settings(first, self.environment)
    first_inode = self.settings_file.stat().st_ino
    settings.save_settings(second, self.environment)
    self.assertNotEqual(self.settings_file.stat().st_ino, first_inode)
    self.assertEqual(self.settings_file.read_bytes(), second + b"\n")
    self.assertEqual(list(self.settings_directory.glob(".settings.*.tmp")), [])

  def test_failed_replace_preserves_old_file_and_cleans_temporary_file(self):
    first = self.encoded({"fontSize": 32})
    second = self.encoded({"fontSize": 48})
    settings.save_settings(first, self.environment)
    with mock.patch.object(settings.os, "replace", side_effect=OSError("test failure")):
      with self.assertRaises(settings.SettingsStoreError):
        settings.save_settings(second, self.environment)
    self.assertEqual(self.settings_file.read_bytes(), first + b"\n")
    self.assertEqual(list(self.settings_directory.glob(".settings.*.tmp")), [])

  def test_unsupported_directory_fsync_does_not_misreport_atomic_replace(self):
    expected = self.encoded({"fontSize": 48})
    real_fsync = os.fsync

    def unsupported_for_directories(descriptor):
      if stat.S_ISDIR(os.fstat(descriptor).st_mode):
        raise OSError(errno.EINVAL, "test filesystem does not fsync directories")
      return real_fsync(descriptor)

    with mock.patch.object(settings.os, "fsync", side_effect=unsupported_for_directories):
      self.assertEqual(settings.save_settings(expected, self.environment), expected)
    self.assertEqual(settings.load_settings(self.environment), expected)

  def test_schema_and_absolute_config_path_fail_closed(self):
    with self.assertRaises(settings.SettingsStoreError):
      settings.save_settings(b"{}", self.environment)
    with self.assertRaises(settings.SettingsStoreError):
      settings.save_settings(self.encoded({"fontSize": True}), self.environment)
    with self.assertRaises(settings.SettingsStoreError):
      settings.save_settings(self.encoded({"version": 1.0}), self.environment)
    with self.assertRaises(settings.SettingsStoreError):
      settings.save_settings(self.encoded({"letterSpacing": 1.0}), self.environment)
    with self.assertRaises(settings.SettingsStoreError):
      settings.load_settings({"XDG_CONFIG_HOME": "relative"})
    with self.assertRaises(settings.SettingsStoreError):
      settings.load_settings({"XDG_CONFIG_HOME": str(self.config_home / "." / "nested") + "/./more"})
    with self.assertRaises(settings.SettingsStoreError):
      settings.load_settings({"XDG_CONFIG_HOME": "/" + "x" * 4097})

  def test_executable_launcher_round_trip_matches_manifest_identity(self):
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    self.assertEqual(manifest["id"], settings.SETTINGS_DIRECTORY_NAME)
    environment = dict(os.environ, XDG_CONFIG_HOME=str(self.config_home))
    write = subprocess.run(
      [str(ROOT / "bin" / "clearread"), "settings-write"],
      input=self.encoded({"fontSize": 84}) + b"\n",
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
      env=environment,
      timeout=5,
      check=False,
    )
    self.assertEqual(write.returncode, 0, write.stderr.decode("utf-8", errors="replace"))
    read = subprocess.run(
      [str(ROOT / "bin" / "clearread"), "settings-read"],
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
      env=environment,
      timeout=5,
      check=False,
    )
    self.assertEqual(read.returncode, 0, read.stderr.decode("utf-8", errors="replace"))
    self.assertEqual(json.loads(read.stdout), {**DEFAULTS, "fontSize": 84})

  def test_executable_launcher_rejects_oversized_input_before_creating_state(self):
    environment = dict(os.environ, XDG_CONFIG_HOME=str(self.config_home))
    result = subprocess.run(
      [str(ROOT / "bin" / "clearread"), "settings-write"],
      input=b"x" * (settings.MAX_SETTINGS_BYTES + 1),
      stdout=subprocess.PIPE,
      stderr=subprocess.PIPE,
      env=environment,
      timeout=5,
      check=False,
    )
    self.assertEqual(result.returncode, 1)
    self.assertEqual(result.stdout, b"")
    self.assertIn(b"4096-byte limit", result.stderr)
    self.assertFalse(self.settings_directory.exists())


if __name__ == "__main__":
  unittest.main()
