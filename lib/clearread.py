#!/usr/bin/env python3

import argparse
import fcntl
import json
import math
import os
from pathlib import Path
import re
import select
import selectors
import shutil
import signal
import struct
import subprocess
import sys
import time
import unicodedata
import zlib

from clearread_settings import (
  MAX_SETTINGS_BYTES,
  SettingsStoreError,
  load_settings,
  save_settings,
)


MAX_COMMAND_OUTPUT = 1024 * 1024
MAX_ERROR_OUTPUT = 64 * 1024
MAX_IMAGE_BYTES = 64 * 1024 * 1024
MAX_TEXT_BYTES = 1024 * 1024
MAX_TEXT_CHARACTERS = 120_000
MAX_COPY_INPUT_BYTES = 1024 * 1024
MAX_PARAGRAPHS = 512
MAX_SOURCE_PIXELS = 33_177_600
MAX_SOURCE_DIMENSION = 32_768

COMMAND_TIMEOUT = 5.0
CAPTURE_TIMEOUT = 10.0
RECOGNITION_TIMEOUT = 20.0
COPY_TIMEOUT = 5.0
TERMINATE_GRACE = 0.4

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_IHDR = b"IHDR"
SOURCE_RELEASE = b"release\n"
GEOMETRY_PATTERN = re.compile(r"^(-?\d+),(-?\d+) (\d+)x(\d+)$")
LANGUAGE_PATTERN = re.compile(r"^[A-Za-z0-9_]+(?:\+[A-Za-z0-9_]+)*$")
LIST_PATTERN = re.compile(r"^(?:[-*\u2022\u2023\u25aa\u25e6]|\d+[.)]|[A-Za-z][.)])\s+", re.UNICODE)


class ClearReadError(Exception):
  def __init__(self, code, message):
    super().__init__(message)
    self.code = code
    self.message = message


class Cancelled(Exception):
  pass


class CommandTimeout(Exception):
  pass


class OutputLimitExceeded(Exception):
  pass


class SourceLens:
  def __init__(self, descriptor, width, height):
    self.descriptor = descriptor
    self.width = width
    self.height = height
    self.closed = False

  def event(self):
    return {
      "uri": f"file:///proc/{os.getpid()}/fd/{self.descriptor}",
      "width": self.width,
      "height": self.height,
    }

  def close(self):
    if self.closed:
      return
    try:
      os.close(self.descriptor)
    except OSError:
      pass
    self.closed = True


class CancellationFlag:
  def __init__(self):
    self.value = False

  def set(self):
    self.value = True

  def clear(self):
    self.value = False

  def is_set(self):
    return self.value


class ChildProcesses:
  def __init__(self):
    self.cancelled = CancellationFlag()
    self.processes = set()

  def add(self, process):
    self.processes.add(process)

  def remove(self, process):
    self.processes.discard(process)

  def cancel(self):
    self.cancelled.set()
    for process in tuple(self.processes):
      _signal_process_group(process, signal.SIGTERM)


CHILDREN = ChildProcesses()
CURRENT_REQUEST_ID = None


class FrozenScreen:
  def __init__(self, pid, expected_pgid):
    self.pid = pid
    self.pidfd = None
    self.closed = False

    if pid <= 1 or expected_pgid <= 1:
      raise ClearReadError("selection_failed", "The region picker returned an invalid frozen-screen process.")

    if sys.platform.startswith("linux"):
      if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        raise ClearReadError(
          "process_ownership_failed",
          "ClearRead cannot safely own Omarchy's frozen-screen process.",
        )
      try:
        pidfd = os.pidfd_open(pid, 0)
      except OSError as error:
        raise ClearReadError(
          "selection_failed",
          "Omarchy's frozen-screen process ended before capture.",
        ) from error
      try:
        pid_pgid = os.getpgid(pid)
        exited = bool(select.select([pidfd], [], [], 0)[0])
      except OSError as error:
        os.close(pidfd)
        raise ClearReadError(
          "selection_failed",
          "Omarchy's frozen-screen process ended before capture.",
        ) from error
      if pid_pgid != expected_pgid or exited:
        os.close(pidfd)
        raise ClearReadError(
          "selection_failed",
          "The region picker returned an unrelated frozen-screen process.",
        )
      self.pidfd = pidfd
    else:
      try:
        if os.getpgid(pid) != expected_pgid:
          raise ClearReadError(
            "selection_failed",
            "The region picker returned an unrelated frozen-screen process.",
          )
      except (ProcessLookupError, PermissionError) as error:
        raise ClearReadError(
          "selection_failed",
          "Omarchy's frozen-screen process ended before capture.",
        ) from error

  def close(self):
    if self.closed:
      return

    try:
      self._signal(signal.SIGTERM)
      if not self._wait(TERMINATE_GRACE):
        self._signal(signal.SIGKILL)
        self._wait(TERMINATE_GRACE)
    finally:
      if self.pidfd is not None:
        os.close(self.pidfd)
      self.closed = True

  def _signal(self, sig):
    try:
      if self.pidfd is not None:
        signal.pidfd_send_signal(self.pidfd, sig)
      else:
        os.kill(self.pid, sig)
    except (ProcessLookupError, PermissionError):
      pass

  def _wait(self, timeout):
    deadline = time.monotonic() + timeout
    while self._alive() and time.monotonic() < deadline:
      time.sleep(0.01)
    return not self._alive()

  def _alive(self):
    if self.pidfd is not None:
      return not bool(select.select([self.pidfd], [], [], 0)[0])
    try:
      os.kill(self.pid, 0)
      return True
    except (ProcessLookupError, PermissionError):
      return False

class OwnedProcessGroup:
  def __init__(self, process):
    self.process = process
    self.pgid = process.pid
    self.closed = False

  def reap(self):
    if self.closed:
      return
    self.process.wait()
    self.closed = True

  def terminate(self):
    if self.closed:
      return
    _stop_process(self.process)
    self.closed = True


def emit(event_type, **fields):
  event = {"type": event_type}
  if CURRENT_REQUEST_ID is not None:
    event["requestId"] = CURRENT_REQUEST_ID
  event.update(fields)
  line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
  sys.stdout.write(line + "\n")
  sys.stdout.flush()


def _signal_process_group(process, sig):
  # returncode changes only after wait()/poll() reaps the group leader. A
  # reaped PID can be reused, so never signal its former process group.
  if process.returncode is not None:
    return

  try:
    os.killpg(process.pid, sig)
  except (ProcessLookupError, PermissionError):
    # Darwin reports EPERM for a group containing only unsignalable zombies;
    # Linux reports ESRCH. In either case there is no live owned member this
    # process can signal.
    pass


def _stop_process(process):
  # Keep the leader unreaped through escalation. Its reserved PID makes the
  # process-group ID safe to signal even when the leader exits on TERM while
  # a TERM-ignoring grandchild remains in the group.
  if process.returncode is not None:
    return

  _signal_process_group(process, signal.SIGTERM)
  deadline = time.monotonic() + TERMINATE_GRACE

  while time.monotonic() < deadline:
    time.sleep(0.01)

  _signal_process_group(process, signal.SIGKILL)

  try:
    process.wait(timeout=TERMINATE_GRACE)
  except subprocess.TimeoutExpired:
    pass


def _owned_argv(argv):
  if sys.platform.startswith("linux"):
    return ["setpriv", "--pdeathsig", "TERM", "--", *argv]
  return argv


def arm_parent_death_signal(expected_parent=None):
  if not sys.platform.startswith("linux"):
    return

  import ctypes

  parent = os.getppid() if expected_parent is None else expected_parent
  if parent <= 1 or os.getppid() != parent:
    raise Cancelled()
  libc = ctypes.CDLL(None, use_errno=True)
  if libc.prctl(1, signal.SIGTERM, 0, 0, 0) != 0:
    error_number = ctypes.get_errno()
    raise ClearReadError(
      "process_ownership_failed",
      f"ClearRead could not bind itself to the Omarchy shell: errno {error_number}.",
    )
  if os.getppid() != parent:
    raise Cancelled()


def run_owned(argv, *, input_bytes=None, timeout=None, stdout_limit=MAX_COMMAND_OUTPUT,
              stderr_limit=MAX_ERROR_OUTPUT, return_process_group=False,
              capture_output=True):
  if CHILDREN.cancelled.is_set():
    raise Cancelled()

  if shutil.which(argv[0]) is None:
    raise ClearReadError("dependency_missing", f"Required command is unavailable: {argv[0]}")
  if sys.platform.startswith("linux") and shutil.which("setpriv") is None:
    raise ClearReadError("dependency_missing", "Required command is unavailable: setpriv")

  stdin = subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL

  try:
    process = subprocess.Popen(
      _owned_argv(argv),
      stdin=stdin,
      stdout=subprocess.PIPE if capture_output else subprocess.DEVNULL,
      stderr=subprocess.PIPE if capture_output else subprocess.DEVNULL,
      start_new_session=True,
    )
  except FileNotFoundError as error:
    raise ClearReadError("dependency_missing", f"Required command is unavailable: {error.filename}") from error

  CHILDREN.add(process)
  selector = None
  output = bytearray()
  errors = bytearray()
  started = time.monotonic()
  input_view = memoryview(input_bytes) if input_bytes is not None else None
  input_offset = 0
  stopped = False
  deferred_group = False

  try:
    selector = selectors.DefaultSelector()
    for stream, label in ((process.stdout, "stdout"), (process.stderr, "stderr")):
      if stream is None:
        continue
      os.set_blocking(stream.fileno(), False)
      selector.register(stream, selectors.EVENT_READ, label)

    if process.stdin is not None:
      os.set_blocking(process.stdin.fileno(), False)
      selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")

    while selector.get_map():
      if CHILDREN.cancelled.is_set():
        raise Cancelled()

      if timeout is not None:
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
          raise CommandTimeout()
        wait = min(0.1, remaining)
      else:
        wait = 0.1

      events = selector.select(wait)

      for key, _ in events:
        stream = key.fileobj

        if key.data == "stdin":
          try:
            if input_offset < len(input_view):
              input_offset += os.write(stream.fileno(), input_view[input_offset:input_offset + 64 * 1024])
            if input_offset >= len(input_view):
              selector.unregister(stream)
              stream.close()
          except BrokenPipeError:
            selector.unregister(stream)
            stream.close()
          continue

        target = output if key.data == "stdout" else errors
        limit = stdout_limit if key.data == "stdout" else stderr_limit

        try:
          chunk = os.read(stream.fileno(), min(64 * 1024, limit - len(target) + 1))
        except BlockingIOError:
          continue

        if not chunk:
          selector.unregister(stream)
          stream.close()
          continue

        target.extend(chunk)
        if len(target) > limit:
          raise OutputLimitExceeded()

    wait_result = None
    while True:
      if return_process_group:
        wait_result = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        if wait_result is not None:
          break
      elif process.poll() is not None:
        break
      if CHILDREN.cancelled.is_set():
        raise Cancelled()
      if timeout is not None and time.monotonic() - started >= timeout:
        raise CommandTimeout()
      time.sleep(0.01)

    if return_process_group:
      return_code = wait_result.si_status if wait_result.si_code == os.CLD_EXITED else -wait_result.si_status
      deferred_group = True
      return return_code, bytes(output), bytes(errors), OwnedProcessGroup(process)

    return_code = process.wait()

    return return_code, bytes(output), bytes(errors)
  except (Cancelled, CommandTimeout, OutputLimitExceeded):
    _stop_process(process)
    stopped = True
    raise
  except OSError as error:
    _stop_process(process)
    stopped = True
    raise ClearReadError("process_failed", "A local ClearRead helper failed.") from error
  finally:
    if selector is not None:
      selector.close()
    for stream in (process.stdin, process.stdout, process.stderr):
      if stream is not None and not stream.closed:
        stream.close()
    if not stopped and not deferred_group and process.returncode is None:
      _stop_process(process)
    elif process.returncode is not None:
      process.wait()
    CHILDREN.remove(process)


def validate_language(language):
  if (
    not isinstance(language, str)
    or len(language) > 120
    or not LANGUAGE_PATTERN.fullmatch(language)
  ):
    raise ClearReadError(
      "invalid_language",
      "OCR language must use Tesseract language codes joined with +, such as eng or eng+spa.",
    )
  return language


def parse_geometry(value):
  if not isinstance(value, str):
    raise ClearReadError("invalid_geometry", "The selected area has an invalid geometry.")

  match = GEOMETRY_PATTERN.fullmatch(value.strip())
  if not match:
    raise ClearReadError("invalid_geometry", "The selected area has an invalid geometry.")

  x, y, width, height = (int(part) for part in match.groups())
  if abs(x) > 1_000_000 or abs(y) > 1_000_000:
    raise ClearReadError("invalid_geometry", "The selected area is outside the supported desktop bounds.")
  if width < 1 or height < 1 or width > 100_000 or height > 100_000:
    raise ClearReadError("invalid_geometry", "The selected area has unsupported dimensions.")
  if width * height > 200_000_000:
    raise ClearReadError("invalid_geometry", "The selected area is too large to read safely.")

  return x, y, width, height


def normalize_geometry(value):
  x, y, width, height = parse_geometry(value)
  return f"{x},{y} {width}x{height}"


def _clean_line(line):
  return line.strip(" \t\f\v")


def reflow_text(value):
  if not isinstance(value, str):
    raise ClearReadError("invalid_text", "Recognized text is invalid.")

  value = value.replace("\r\n", "\n").replace("\r", "\n")
  value = "".join(
    character
    for character in value
    if character in "\n\t"
    or (
      ord(character) >= 32
      and not 127 <= ord(character) <= 159
      and (unicodedata.category(character) != "Cf" or character in "\u200c\u200d")
    )
  )

  paragraphs = []
  current = []

  def finish():
    nonlocal current
    if current:
      paragraph = current[0]
      for line in current[1:]:
        paragraph += ("" if paragraph.endswith("-") else " ") + line
      paragraphs.append(paragraph)
    current = []

  for source_line in value.split("\n"):
    line = _clean_line(source_line)
    if not line:
      finish()
      continue

    is_list = bool(LIST_PATTERN.match(line))
    if is_list:
      finish()
      current = [line]
      continue

    current.append(line)

  finish()

  if len(paragraphs) > MAX_PARAGRAPHS:
    raise ClearReadError("text_too_large", "The capture contains too many paragraphs to read safely.")

  text = "\n\n".join(paragraphs)
  if len(text) > MAX_TEXT_CHARACTERS:
    raise ClearReadError("text_too_large", "The capture contains too much text to read safely.")

  return text


def decode_text(data, source):
  try:
    value = data.decode("utf-8")
  except UnicodeDecodeError as error:
    raise ClearReadError("invalid_text", f"{source} returned text that is not valid UTF-8.") from error
  return reflow_text(value)


def _json_command(argv, code, message):
  try:
    return_code, output, _ = run_owned(argv, timeout=COMMAND_TIMEOUT)
  except CommandTimeout as error:
    raise ClearReadError(code, message) from error
  except OutputLimitExceeded as error:
    raise ClearReadError(code, message) from error

  if return_code != 0:
    raise ClearReadError(code, message)

  try:
    return json.loads(output.decode("utf-8"))
  except (UnicodeDecodeError, ValueError, RecursionError) as error:
    raise ClearReadError(code, message) from error


def active_window_geometry():
  window = _json_command(
    ["hyprctl", "activewindow", "-j"],
    "window_unavailable",
    "ClearRead could not inspect the active window.",
  )

  at = window.get("at") if isinstance(window, dict) else None
  size = window.get("size") if isinstance(window, dict) else None
  if not _integer_pair(at) or not _integer_pair(size):
    raise ClearReadError("window_unavailable", "There is no readable active window.")

  return normalize_geometry(f"{at[0]},{at[1]} {size[0]}x{size[1]}")


def _integer_pair(value):
  return (
    isinstance(value, list)
    and len(value) == 2
    and all(isinstance(item, int) and not isinstance(item, bool) for item in value)
  )


def region_geometry(omarchy_path):
  if not omarchy_path or not os.path.isabs(omarchy_path):
    raise ClearReadError("invalid_omarchy_path", "Omarchy did not provide an absolute runtime path.")

  picker = Path(omarchy_path) / "bin" / "omarchy-capture-region"
  if not picker.is_file() or not os.access(picker, os.X_OK):
    raise ClearReadError("picker_unavailable", "Omarchy's region picker is unavailable.")

  picker_group = None
  try:
    return_code, output, _, picker_group = run_owned(
      [str(picker), "smart", "--keep-freeze"],
      timeout=None,
      stdout_limit=4096,
      return_process_group=True,
    )
  except OutputLimitExceeded as error:
    raise ClearReadError("selection_failed", "The region picker returned an invalid selection.") from error

  try:
    lines = output.decode("utf-8", errors="replace").splitlines()
    frozen_screen = None

    if lines:
      freeze_pid = lines[0]
      if not re.fullmatch(r"[1-9]\d{0,9}", freeze_pid):
        raise ClearReadError("selection_failed", "The region picker returned an invalid frozen-screen process.")
      freeze_pid = int(freeze_pid)
      if freeze_pid <= 1 or freeze_pid > 2_147_483_647 or freeze_pid == os.getpid():
        raise ClearReadError("selection_failed", "The region picker returned an invalid frozen-screen process.")
      frozen_screen = FrozenScreen(freeze_pid, picker_group.pgid)

    if frozen_screen is None:
      raise ClearReadError("selection_failed", "The region picker returned an invalid selection.")

    try:
      picker_group.reap()
    except OSError as error:
      frozen_screen.close()
      raise ClearReadError(
        "selection_failed",
        "Omarchy's frozen-screen process ended before capture.",
      ) from error
    picker_group = None

    if return_code != 0:
      if frozen_screen is not None:
        frozen_screen.close()
      if len(lines) <= 1:
        raise Cancelled()
      raise ClearReadError("selection_failed", "ClearRead could not select a region.")
    if len(lines) != 2:
      frozen_screen.close()
      raise ClearReadError("selection_failed", "The region picker returned an invalid selection.")

    try:
      geometry = normalize_geometry(lines[1])
    except ClearReadError:
      frozen_screen.close()
      raise

    return geometry, frozen_screen
  finally:
    if picker_group is not None:
      picker_group.terminate()


def monitor_data():
  monitors = _json_command(
    ["hyprctl", "monitors", "-j"],
    "monitor_unavailable",
    "ClearRead could not inspect the connected monitors.",
  )
  if not isinstance(monitors, list):
    raise ClearReadError("monitor_unavailable", "ClearRead received invalid monitor information.")
  return monitors


def monitor_for_geometry(monitors, geometry):
  x, y, width, height = parse_geometry(geometry)
  center_x = x + width / 2
  center_y = y + height / 2
  best_name = None
  best_overlap = -1

  for monitor in monitors:
    rectangle = _monitor_rectangle(monitor)
    name = monitor.get("name") if isinstance(monitor, dict) else None
    if rectangle is None or not isinstance(name, str) or not name:
      continue
    name = name[:160]

    mx, my, mw, mh = rectangle
    overlap_width = max(0, min(x + width, mx + mw) - max(x, mx))
    overlap_height = max(0, min(y + height, my + mh) - max(y, my))
    overlap = overlap_width * overlap_height

    if mx <= center_x < mx + mw and my <= center_y < my + mh:
      return name
    if overlap > best_overlap:
      best_overlap = overlap
      best_name = name

  return best_name if best_overlap > 0 else focused_monitor(monitors)


def focused_monitor(monitors):
  for monitor in monitors:
    if isinstance(monitor, dict) and monitor.get("focused") is True:
      name = monitor.get("name")
      if isinstance(name, str) and name:
        return name[:160]
  return None


def _monitor_rectangle(monitor):
  if not isinstance(monitor, dict):
    return None

  values = [monitor.get(key) for key in ("x", "y", "width", "height")]
  if not all(
    isinstance(value, (int, float))
    and not isinstance(value, bool)
    and value == value
    and value not in (math.inf, -math.inf)
    for value in values
  ):
    return None

  scale = monitor.get("scale", 1)
  transform = monitor.get("transform", 0)
  if (
    not isinstance(scale, (int, float))
    or isinstance(scale, bool)
    or scale != scale
    or scale in (math.inf, -math.inf)
    or scale <= 0
  ):
    return None

  x, y, width, height = values
  try:
    scaled_width = width / scale
    scaled_height = height / scale
  except OverflowError:
    return None
  if (
    scaled_width != scaled_width
    or scaled_height != scaled_height
    or scaled_width in (math.inf, -math.inf)
    or scaled_height in (math.inf, -math.inf)
  ):
    return None

  logical_width = int(scaled_width)
  logical_height = int(scaled_height)
  if transform in (1, 3, 5, 7):
    logical_width, logical_height = logical_height, logical_width
  if logical_width < 1 or logical_height < 1:
    return None

  return int(x), int(y), logical_width, logical_height


def png_dimensions(image):
  if not isinstance(image, (bytes, bytearray, memoryview)) or len(image) < 33:
    raise ClearReadError("capture_failed", "The screen capture did not return a valid image.")
  if bytes(image[:8]) != PNG_SIGNATURE:
    raise ClearReadError("capture_failed", "The screen capture did not return a valid image.")

  chunk_length = struct.unpack(">I", image[8:12])[0]
  chunk_type = bytes(image[12:16])
  chunk_data = bytes(image[16:29])
  chunk_crc = struct.unpack(">I", image[29:33])[0]
  if (
    chunk_length != 13
    or chunk_type != PNG_IHDR
    or zlib.crc32(chunk_type + chunk_data) & 0xffffffff != chunk_crc
  ):
    raise ClearReadError("capture_failed", "The screen capture did not return a valid image.")

  width, height, bit_depth, colour_type, compression, filtering, interlace = struct.unpack(
    ">IIBBBBB", chunk_data,
  )
  valid_depths = {
    0: (1, 2, 4, 8, 16),
    2: (8, 16),
    3: (1, 2, 4, 8),
    4: (8, 16),
    6: (8, 16),
  }
  if (
    width < 1
    or height < 1
    or width > 2_147_483_647
    or height > 2_147_483_647
    or bit_depth not in valid_depths.get(colour_type, ())
    or compression != 0
    or filtering != 0
    or interlace not in (0, 1)
  ):
    raise ClearReadError("capture_failed", "The screen capture did not return a valid image.")

  return width, height


def validate_recognition_image(image):
  width, height = png_dimensions(image)
  if (
    width > MAX_SOURCE_DIMENSION
    or height > MAX_SOURCE_DIMENSION
    or width * height > MAX_SOURCE_PIXELS
  ):
    raise ClearReadError(
      "capture_too_large",
      "The captured image is too large to recognize safely. Choose a smaller window or screen area and try again.",
    )

  return width, height


def retain_source_image(image):
  width, height = png_dimensions(image)
  if (
    width > MAX_SOURCE_DIMENSION
    or height > MAX_SOURCE_DIMENSION
    or width * height > MAX_SOURCE_PIXELS
    or not sys.platform.startswith("linux")
  ):
    return None

  constants = (
    "MFD_CLOEXEC", "MFD_ALLOW_SEALING",
  )
  seal_constants = (
    "F_ADD_SEALS", "F_GET_SEALS", "F_SEAL_WRITE", "F_SEAL_GROW",
    "F_SEAL_SHRINK", "F_SEAL_SEAL",
  )
  if not hasattr(os, "memfd_create") or not all(hasattr(os, name) for name in constants):
    return None
  if not all(hasattr(fcntl, name) for name in seal_constants):
    return None

  descriptor = None
  try:
    flags = os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING
    descriptor = os.memfd_create("clearread-source", flags)
    view = memoryview(image)
    offset = 0
    while offset < len(view):
      written = os.write(descriptor, view[offset:offset + 1024 * 1024])
      if written < 1:
        raise OSError("memfd write made no progress")
      offset += written
    os.lseek(descriptor, 0, os.SEEK_SET)

    seals = (
      fcntl.F_SEAL_WRITE
      | fcntl.F_SEAL_GROW
      | fcntl.F_SEAL_SHRINK
      | fcntl.F_SEAL_SEAL
    )
    fcntl.fcntl(descriptor, fcntl.F_ADD_SEALS, seals)
    installed_seals = fcntl.fcntl(descriptor, fcntl.F_GET_SEALS)
    descriptor_flags = fcntl.fcntl(descriptor, fcntl.F_GETFD)
    if installed_seals & seals != seals or not descriptor_flags & fcntl.FD_CLOEXEC:
      raise OSError("memfd protections were not installed")

    source = SourceLens(descriptor, width, height)
    descriptor = None
    return source
  except OSError:
    return None
  finally:
    if descriptor is not None:
      try:
        os.close(descriptor)
      except OSError:
        pass


def wait_for_source_release(stream):
  try:
    descriptor = stream.fileno()
  except (AttributeError, OSError):
    while True:
      if CHILDREN.cancelled.is_set():
        raise Cancelled()
      line = stream.readline(4096)
      if not line or line == SOURCE_RELEASE:
        return

  candidate = bytearray()
  discard_line = False
  release_word = SOURCE_RELEASE[:-1]

  while True:
    if CHILDREN.cancelled.is_set():
      raise Cancelled()
    try:
      ready, _, _ = select.select([descriptor], [], [], 0.1)
    except (OSError, ValueError):
      return
    if not ready:
      continue
    try:
      chunk = os.read(descriptor, 4096)
    except OSError:
      return
    if not chunk:
      return

    for character in chunk:
      if character == ord("\n"):
        if not discard_line and candidate == release_word:
          return
        candidate.clear()
        discard_line = False
      elif not discard_line:
        if len(candidate) < len(release_word):
          candidate.append(character)
        else:
          discard_line = True


def capture_png(geometry):
  try:
    return_code, image, _ = run_owned(
      ["grim", "-g", geometry, "-"],
      timeout=CAPTURE_TIMEOUT,
      stdout_limit=MAX_IMAGE_BYTES,
    )
  except CommandTimeout as error:
    raise ClearReadError("capture_timeout", "The screen capture did not finish in time.") from error
  except OutputLimitExceeded as error:
    raise ClearReadError("capture_too_large", "The selected image is too large to read safely.") from error

  if return_code != 0:
    raise ClearReadError("capture_failed", "ClearRead could not capture the selected area.")
  png_dimensions(image)

  return image


def recognize_image(image, language):
  try:
    return_code, text, _ = run_owned(
      [
        "tesseract", "stdin", "stdout",
        "--oem", "1",
        "--psm", "6",
        "-l", language,
        "--dpi", "300",
        "-c", "preserve_interword_spaces=1",
      ],
      input_bytes=image,
      timeout=RECOGNITION_TIMEOUT,
      stdout_limit=MAX_TEXT_BYTES,
    )
  except CommandTimeout as error:
    raise ClearReadError("recognition_timeout", "Text recognition did not finish within 20 seconds.") from error
  except OutputLimitExceeded as error:
    raise ClearReadError("text_too_large", "The capture contains too much text to read safely.") from error

  if return_code != 0:
    raise ClearReadError("recognition_failed", "ClearRead could not recognize text in the capture.")
  if not text.strip():
    raise ClearReadError("no_text", "No readable text was found in the selected area.")

  decoded = decode_text(text, "Tesseract")
  if not decoded:
    raise ClearReadError("no_text", "No readable text was found in the selected area.")
  return decoded


def capture_clipboard():
  try:
    return_code, text, _ = run_owned(
      ["wl-paste", "--no-newline", "--type", "text"],
      timeout=COMMAND_TIMEOUT,
      stdout_limit=MAX_TEXT_BYTES,
    )
  except CommandTimeout as error:
    raise ClearReadError("clipboard_timeout", "Reading the clipboard did not finish in time.") from error
  except OutputLimitExceeded as error:
    raise ClearReadError("text_too_large", "The clipboard contains too much text to read safely.") from error

  if return_code != 0:
    raise ClearReadError("clipboard_unavailable", "The clipboard does not contain readable text.")
  if not text.strip():
    raise ClearReadError("no_text", "The clipboard does not contain readable text.")

  decoded = decode_text(text, "The clipboard")
  if not decoded:
    raise ClearReadError("no_text", "The clipboard does not contain readable text.")
  return decoded


def capture(mode, omarchy_path, language):
  validate_language(language)
  geometry = None
  frozen_screen = None
  source = None

  try:
    if mode == "region":
      emit("status", state="selecting", mode=mode)
      geometry, frozen_screen = region_geometry(omarchy_path)
    elif mode == "window":
      geometry = active_window_geometry()
    elif mode != "clipboard":
      raise ClearReadError("invalid_mode", "ClearRead received an unsupported capture mode.")

    emit("status", state="capturing", mode=mode)

    if mode == "clipboard":
      monitor = None
      text = capture_clipboard()
    else:
      image = capture_png(geometry)
      validate_recognition_image(image)
      if frozen_screen is not None:
        frozen_screen.close()
        frozen_screen = None
      try:
        monitor = monitor_for_geometry(monitor_data(), geometry)
      except ClearReadError:
        monitor = None
      status = {"state": "recognizing", "mode": mode}
      if monitor:
        status["monitor"] = monitor
      emit("status", **status)
      text = recognize_image(image, language)
      source = retain_source_image(image)
      del image

    result = {"mode": mode, "text": text}
    if monitor:
      result["monitor"] = monitor
    if source is not None:
      result["source"] = source.event()
    emit("result", **result)

    if source is not None:
      wait_for_source_release(sys.stdin.buffer)
  finally:
    if frozen_screen is not None:
      frozen_screen.close()
    if source is not None:
      source.close()


def read_bounded_request(stream, maximum_bytes, error_code, error_message):
  try:
    descriptor = stream.fileno()
  except (AttributeError, OSError):
    return stream.readline(maximum_bytes + 1)

  data = bytearray()
  deadline = time.monotonic() + COMMAND_TIMEOUT
  while True:
    if CHILDREN.cancelled.is_set():
      raise Cancelled()

    remaining = deadline - time.monotonic()
    if remaining <= 0:
      raise ClearReadError(error_code, error_message)
    ready, _, _ = select.select([descriptor], [], [], min(0.1, remaining))
    if not ready:
      continue

    chunk = os.read(descriptor, min(64 * 1024, maximum_bytes - len(data) + 1))
    if not chunk:
      return bytes(data)

    newline = chunk.find(b"\n")
    data.extend(chunk if newline == -1 else chunk[:newline + 1])
    if len(data) > maximum_bytes:
      return bytes(data)
    if newline != -1:
      return bytes(data)


def copy_text():
  line = read_bounded_request(
    sys.stdin.buffer,
    MAX_COPY_INPUT_BYTES,
    "invalid_copy_request",
    "ClearRead did not receive text to copy.",
  )
  if len(line) > MAX_COPY_INPUT_BYTES:
    raise ClearReadError("copy_too_large", "The text is too large to copy safely.")
  if not line:
    raise ClearReadError("invalid_copy_request", "ClearRead did not receive text to copy.")

  try:
    request = json.loads(line.decode("utf-8"))
  except (UnicodeDecodeError, ValueError, RecursionError) as error:
    raise ClearReadError("invalid_copy_request", "ClearRead received an invalid copy request.") from error

  text = request.get("text") if isinstance(request, dict) else None
  if not isinstance(text, str):
    raise ClearReadError("invalid_copy_request", "The copy request must contain text.")

  encoded = text.encode("utf-8")
  if len(encoded) > MAX_TEXT_BYTES:
    raise ClearReadError("copy_too_large", "The text is too large to copy safely.")

  try:
    return_code, _, _ = run_owned(
      ["wl-copy", "--type", "text/plain", "--sensitive"],
      input_bytes=encoded,
      timeout=COPY_TIMEOUT,
      capture_output=False,
    )
  except CommandTimeout as error:
    raise ClearReadError("copy_timeout", "Copying did not finish in time.") from error

  if return_code != 0:
    raise ClearReadError("copy_failed", "ClearRead could not copy the text.")


def read_presentation_settings():
  try:
    content = load_settings()
  except SettingsStoreError as error:
    raise ClearReadError("settings_read_failed", str(error)) from error
  sys.stdout.buffer.write(content + b"\n")
  sys.stdout.buffer.flush()


def write_presentation_settings():
  line = read_bounded_request(
    sys.stdin.buffer,
    MAX_SETTINGS_BYTES,
    "invalid_settings_request",
    "ClearRead did not receive presentation settings.",
  )
  if len(line) > MAX_SETTINGS_BYTES:
    raise ClearReadError("settings_too_large", "ClearRead settings exceed the 4096-byte limit.")
  if not line:
    raise ClearReadError("invalid_settings_request", "ClearRead did not receive presentation settings.")
  try:
    save_settings(line)
  except SettingsStoreError as error:
    raise ClearReadError("settings_write_failed", str(error)) from error


def doctor(omarchy_path, language):
  missing = []
  issues = []

  linux = sys.platform.startswith("linux")
  wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
  if not linux:
    issues.append("ClearRead requires Linux.")
  if not wayland:
    issues.append("ClearRead requires an active Wayland session.")

  commands = {}
  for command in ("setpriv", "hyprctl", "grim", "tesseract", "wl-paste", "wl-copy"):
    commands[command] = shutil.which(command) is not None
    if not commands[command]:
      missing.append(command)

  picker = False
  if omarchy_path and os.path.isabs(omarchy_path):
    picker_path = Path(omarchy_path) / "bin" / "omarchy-capture-region"
    picker = picker_path.is_file() and os.access(picker_path, os.X_OK)
  else:
    issues.append("Omarchy did not provide an absolute runtime path.")
  if not picker:
    missing.append("omarchy-capture-region")

  language_ok = True
  try:
    validate_language(language)
  except ClearReadError as error:
    language_ok = False
    issues.append(error.message)

  if language_ok and commands["tesseract"] and (commands["setpriv"] or not linux):
    try:
      return_code, output, _ = run_owned(
        ["tesseract", "--list-langs"],
        timeout=COMMAND_TIMEOUT,
        stdout_limit=MAX_COMMAND_OUTPUT,
      )
      installed = {
        line.strip()
        for line in output.decode("utf-8", errors="replace").splitlines()[1:]
        if LANGUAGE_PATTERN.fullmatch(line.strip())
      }
      unavailable = [code for code in language.split("+") if code not in installed]
      if return_code != 0 or unavailable:
        language_ok = False
        for code in unavailable[:8]:
          missing.append(f"tesseract-language:{code}")
        issues.append("Tesseract does not have the requested OCR language data.")
    except (ClearReadError, CommandTimeout, OutputLimitExceeded):
      language_ok = False
      issues.append("ClearRead could not inspect the installed Tesseract languages.")

  session = linux and wayland
  pidfd = not linux or (hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"))
  if not pidfd:
    missing.append("python-pidfd")
    issues.append("Python cannot safely own Omarchy's frozen-screen process.")
  capabilities = {
    "window": session and commands["setpriv"] and commands["hyprctl"] and commands["grim"] and commands["tesseract"] and language_ok,
    "region": session and pidfd and commands["setpriv"] and commands["hyprctl"] and commands["grim"] and commands["tesseract"] and picker and language_ok,
    "clipboard": session and commands["setpriv"] and commands["wl-paste"],
    "copy": session and commands["setpriv"] and commands["wl-copy"],
  }
  ready = capabilities["window"] or capabilities["region"] or capabilities["clipboard"]

  emit(
    "doctor",
    ready=ready,
    capabilities=capabilities,
    missing=missing[:16],
    issues=issues[:16],
  )
  return 0 if ready else 1


def default_language():
  return os.environ.get("OMARCHY_OCR_LANGS", "eng")


def request_id(value):
  try:
    number = int(value)
  except (TypeError, ValueError) as error:
    raise argparse.ArgumentTypeError("request ID must be a positive integer") from error
  if number < 1 or number > 2_147_483_647 or str(number) != value:
    raise argparse.ArgumentTypeError("request ID must be a positive integer")
  return number


def parser():
  argument_parser = argparse.ArgumentParser(prog="clearread")
  argument_parser.add_argument("--launcher-pid", type=request_id, help=argparse.SUPPRESS)
  commands = argument_parser.add_subparsers(dest="command", required=True)

  doctor_parser = commands.add_parser("doctor", help="check ClearRead's runtime")
  doctor_parser.add_argument("--omarchy-path", default=os.environ.get("OMARCHY_PATH"))
  doctor_parser.add_argument("--language", default=default_language())
  doctor_parser.add_argument("--request-id", type=request_id)

  capture_parser = commands.add_parser("capture", help="capture text for the reader")
  capture_parser.add_argument("--mode", choices=("window", "region", "clipboard"), required=True)
  capture_parser.add_argument("--omarchy-path", default=os.environ.get("OMARCHY_PATH"))
  capture_parser.add_argument("--language", default=default_language())
  capture_parser.add_argument("--request-id", type=request_id)

  commands.add_parser("copy", help="copy one JSON text request")
  commands.add_parser("settings-read", help="read bounded presentation settings")
  commands.add_parser("settings-write", help="write bounded presentation settings")
  return argument_parser


def _cancel(_signum, _frame):
  # Python delivers signals on the main thread and may interrupt Popen while
  # it holds an internal lock. Latch only here; the bounded selector loop owns
  # termination and reaping outside signal-handler context.
  CHILDREN.cancelled.set()


def main(argv=None):
  global CURRENT_REQUEST_ID

  arguments = parser().parse_args(argv)
  CURRENT_REQUEST_ID = getattr(arguments, "request_id", None)
  CHILDREN.cancelled.clear()
  previous_sigterm = signal.signal(signal.SIGTERM, _cancel)
  previous_sigint = signal.signal(signal.SIGINT, _cancel)

  try:
    arm_parent_death_signal(arguments.launcher_pid)
    if arguments.command == "doctor":
      return doctor(arguments.omarchy_path, arguments.language)
    if arguments.command == "capture":
      capture(arguments.mode, arguments.omarchy_path, arguments.language)
      return 0
    if arguments.command == "copy":
      copy_text()
      return 0
    if arguments.command == "settings-read":
      read_presentation_settings()
      return 0
    if arguments.command == "settings-write":
      write_presentation_settings()
      return 0
  except Cancelled:
    mode = getattr(arguments, "mode", None)
    emit("cancelled", mode=mode)
    return 130
  except ClearReadError as error:
    if arguments.command.startswith("settings-"):
      sys.stderr.write(error.message + "\n")
    else:
      emit("error", code=error.code, message=error.message)
    return 1
  finally:
    CHILDREN.cancel()
    CURRENT_REQUEST_ID = None
    signal.signal(signal.SIGTERM, previous_sigterm)
    signal.signal(signal.SIGINT, previous_sigint)

  return 1


if __name__ == "__main__":
  raise SystemExit(main())
