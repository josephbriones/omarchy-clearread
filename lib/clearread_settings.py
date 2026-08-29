#!/usr/bin/env python3

import errno
import json
import os
import secrets
import stat


SETTINGS_DIRECTORY_NAME = "io.github.josephbriones.clearread"
SETTINGS_FILE_NAME = "settings.json"
MAX_SETTINGS_BYTES = 4096
MAX_CONFIG_PATH_BYTES = 4096

SETTING_KEYS = (
  "version",
  "fontSize",
  "fontFamily",
  "fontWeight",
  "lineHeight",
  "letterSpacing",
  "wordSpacing",
  "columnWidth",
  "palette",
  "focusLines",
)

SETTING_VALUES = {
  "version": (1,),
  "fontFamily": ("system", "serif", "mono"),
  "fontWeight": ("regular", "bold"),
  "lineHeight": (1.25, 1.5, 2),
  "letterSpacing": (0, 1, 2),
  "wordSpacing": (0, 4, 8),
  "columnWidth": ("narrow", "medium", "wide"),
  "palette": ("paper", "sepia", "dark", "contrast"),
  "focusLines": (0, 1, 3, 5),
}


class SettingsStoreError(Exception):
  pass


def _open_flags(*names):
  flags = 0
  for name in names:
    value = getattr(os, name, None)
    if value is None:
      raise SettingsStoreError("This system cannot safely access ClearRead settings.")
    flags |= value
  return flags


def _config_home(environ):
  configured = environ.get("XDG_CONFIG_HOME", "")
  if configured:
    path = configured
  else:
    home = environ.get("HOME", "")
    if not home:
      raise SettingsStoreError("ClearRead could not locate the user configuration directory.")
    path = os.path.join(home, ".config")

  if not os.path.isabs(path):
    raise SettingsStoreError("ClearRead requires an absolute user configuration directory.")
  try:
    encoded = os.fsencode(path)
  except UnicodeError as error:
    raise SettingsStoreError("ClearRead refused an unsafe user configuration path.") from error
  if b"\0" in encoded or len(encoded) > MAX_CONFIG_PATH_BYTES:
    raise SettingsStoreError("ClearRead refused an unsafe user configuration path.")
  return path


def _path_components(path):
  components = []
  for component in path.split(os.sep):
    if component == "":
      continue
    if component in (".", ".."):
      raise SettingsStoreError("ClearRead refused an unsafe user configuration path.")
    components.append(component)
  if not components:
    raise SettingsStoreError("ClearRead refused an unsafe user configuration path.")
  return components


def _validate_owner(file_stat, message):
  if file_stat.st_uid != os.geteuid():
    raise SettingsStoreError(message)


def _open_config_home(environ, create):
  components = _path_components(_config_home(environ))
  directory_flags = _open_flags("O_RDONLY", "O_DIRECTORY", "O_CLOEXEC", "O_NOFOLLOW")
  try:
    current_fd = os.open(os.sep, directory_flags)
  except OSError as error:
    raise SettingsStoreError("ClearRead could not open the filesystem root safely.") from error

  try:
    for component in components:
      try:
        next_fd = os.open(component, directory_flags, dir_fd=current_fd)
      except FileNotFoundError:
        if not create:
          return None
        try:
          os.mkdir(component, 0o700, dir_fd=current_fd)
          next_fd = os.open(component, directory_flags, dir_fd=current_fd)
        except FileExistsError:
          try:
            next_fd = os.open(component, directory_flags, dir_fd=current_fd)
          except OSError as error:
            raise SettingsStoreError("ClearRead refused an unsafe user configuration path.") from error
        except OSError as error:
          raise SettingsStoreError("ClearRead could not create the user configuration directory safely.") from error
      except OSError as error:
        raise SettingsStoreError("ClearRead refused an unsafe user configuration path.") from error

      os.close(current_fd)
      current_fd = next_fd

    config_stat = os.fstat(current_fd)
    if not stat.S_ISDIR(config_stat.st_mode):
      raise SettingsStoreError("ClearRead requires a real user configuration directory.")
    _validate_owner(config_stat, "ClearRead requires a user-owned configuration directory.")
    result_fd = current_fd
    current_fd = None
    return result_fd
  except SettingsStoreError:
    raise
  except OSError as error:
    raise SettingsStoreError("ClearRead could not verify the user configuration directory.") from error
  finally:
    if current_fd is not None:
      os.close(current_fd)


def _open_settings_directory(environ, create):
  config_fd = _open_config_home(environ, create)
  if config_fd is None:
    return None

  try:
    if create:
      try:
        os.mkdir(SETTINGS_DIRECTORY_NAME, 0o700, dir_fd=config_fd)
      except FileExistsError:
        pass
      except OSError as error:
        raise SettingsStoreError("ClearRead could not create its private settings directory.") from error

    settings_flags = _open_flags("O_RDONLY", "O_DIRECTORY", "O_CLOEXEC", "O_NOFOLLOW")
    try:
      settings_fd = os.open(SETTINGS_DIRECTORY_NAME, settings_flags, dir_fd=config_fd)
    except FileNotFoundError:
      return None
    except OSError as error:
      raise SettingsStoreError("ClearRead refused an unsafe settings directory.") from error
  finally:
    os.close(config_fd)

  try:
    settings_stat = os.fstat(settings_fd)
    if not stat.S_ISDIR(settings_stat.st_mode):
      raise SettingsStoreError("ClearRead requires a real settings directory.")
    _validate_owner(settings_stat, "ClearRead requires a user-owned settings directory.")
    if stat.S_IMODE(settings_stat.st_mode) != 0o700:
      raise SettingsStoreError("ClearRead requires its settings directory to have mode 0700.")
  except SettingsStoreError:
    os.close(settings_fd)
    raise
  except OSError as error:
    os.close(settings_fd)
    raise SettingsStoreError("ClearRead could not verify its settings directory.") from error

  return settings_fd


def _validate_settings_file(file_stat):
  if not stat.S_ISREG(file_stat.st_mode):
    raise SettingsStoreError("ClearRead refused a non-regular settings file.")
  _validate_owner(file_stat, "ClearRead requires a user-owned settings file.")
  if file_stat.st_nlink != 1:
    raise SettingsStoreError("ClearRead refused a multiply linked settings file.")


def _open_existing_settings(directory_fd):
  flags = _open_flags("O_RDONLY", "O_NONBLOCK", "O_CLOEXEC", "O_NOFOLLOW")
  try:
    file_fd = os.open(SETTINGS_FILE_NAME, flags, dir_fd=directory_fd)
  except FileNotFoundError:
    return None
  except OSError as error:
    raise SettingsStoreError("ClearRead refused an unsafe settings file.") from error

  try:
    _validate_settings_file(os.fstat(file_fd))
  except SettingsStoreError:
    os.close(file_fd)
    raise
  except OSError as error:
    os.close(file_fd)
    raise SettingsStoreError("ClearRead could not verify its settings file.") from error
  return file_fd


def _canonical_settings(raw):
  if len(raw) > MAX_SETTINGS_BYTES:
    raise SettingsStoreError("ClearRead settings exceed the 4096-byte limit.")
  try:
    decoded = raw.decode("utf-8")
    settings = json.loads(decoded)
  except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
    raise SettingsStoreError("ClearRead settings are not valid UTF-8 JSON.") from error

  if not isinstance(settings, dict) or set(settings) != set(SETTING_KEYS):
    raise SettingsStoreError("ClearRead settings do not match the supported schema.")
  if type(settings["fontSize"]) is not int or not 18 <= settings["fontSize"] <= 112:
    raise SettingsStoreError("ClearRead settings contain an unsupported font size.")

  for key in ("version", "letterSpacing", "wordSpacing", "focusLines"):
    value = settings[key]
    if type(value) is not int or value not in SETTING_VALUES[key]:
      raise SettingsStoreError("ClearRead settings contain an unsupported value.")
  for key in ("fontFamily", "fontWeight", "columnWidth", "palette"):
    value = settings[key]
    if type(value) is not str or value not in SETTING_VALUES[key]:
      raise SettingsStoreError("ClearRead settings contain an unsupported value.")
  line_height = settings["lineHeight"]
  if type(line_height) not in (int, float) or line_height not in SETTING_VALUES["lineHeight"]:
    raise SettingsStoreError("ClearRead settings contain an unsupported value.")

  canonical = {key: settings[key] for key in SETTING_KEYS}
  encoded = json.dumps(canonical, ensure_ascii=True, separators=(",", ":")).encode("ascii")
  if len(encoded) > MAX_SETTINGS_BYTES:
    raise SettingsStoreError("ClearRead settings exceed the 4096-byte limit.")
  return encoded


def load_settings(environ=None):
  environment = os.environ if environ is None else environ
  directory_fd = _open_settings_directory(environment, create=False)
  if directory_fd is None:
    return b"{}"

  try:
    file_fd = _open_existing_settings(directory_fd)
    if file_fd is None:
      return b"{}"
    try:
      file_stat = os.fstat(file_fd)
      if file_stat.st_size > MAX_SETTINGS_BYTES:
        raise SettingsStoreError("ClearRead settings exceed the 4096-byte limit.")

      chunks = []
      remaining = MAX_SETTINGS_BYTES + 1
      while remaining:
        try:
          chunk = os.read(file_fd, min(1024, remaining))
        except OSError as error:
          raise SettingsStoreError("ClearRead could not read its settings safely.") from error
        if not chunk:
          break
        chunks.append(chunk)
        remaining -= len(chunk)
      raw = b"".join(chunks)
      if len(raw) > MAX_SETTINGS_BYTES:
        raise SettingsStoreError("ClearRead settings exceed the 4096-byte limit.")
      return _canonical_settings(raw)
    finally:
      os.close(file_fd)
  finally:
    os.close(directory_fd)


def _write_all(file_fd, content):
  view = memoryview(content)
  written = 0
  while written < len(view):
    try:
      count = os.write(file_fd, view[written:])
    except OSError as error:
      raise SettingsStoreError("ClearRead could not write its settings safely.") from error
    if count <= 0:
      raise SettingsStoreError("ClearRead could not write its settings safely.")
    written += count


def _sync_directory(directory_fd):
  try:
    os.fsync(directory_fd)
  except OSError as error:
    unsupported = {
      errno.EINVAL,
      getattr(errno, "ENOTSUP", errno.EINVAL),
      getattr(errno, "EOPNOTSUPP", errno.EINVAL),
    }
    if error.errno not in unsupported:
      raise


def save_settings(raw, environ=None):
  canonical = _canonical_settings(raw) + b"\n"
  environment = os.environ if environ is None else environ
  directory_fd = _open_settings_directory(environment, create=True)
  if directory_fd is None:
    raise SettingsStoreError("ClearRead could not open its settings directory.")

  temporary_name = None
  try:
    existing_fd = _open_existing_settings(directory_fd)
    if existing_fd is not None:
      os.close(existing_fd)

    write_flags = _open_flags("O_WRONLY", "O_CREAT", "O_EXCL", "O_CLOEXEC", "O_NOFOLLOW")
    for _ in range(16):
      candidate = f".settings.{secrets.token_hex(8)}.tmp"
      try:
        temporary_fd = os.open(candidate, write_flags, 0o600, dir_fd=directory_fd)
        temporary_name = candidate
        break
      except FileExistsError:
        continue
      except OSError as error:
        raise SettingsStoreError("ClearRead could not create a private settings file.") from error
    else:
      raise SettingsStoreError("ClearRead could not allocate a private settings file.")

    try:
      _write_all(temporary_fd, canonical)
      os.fchmod(temporary_fd, 0o600)
      os.fsync(temporary_fd)
    except OSError as error:
      raise SettingsStoreError("ClearRead could not write its settings safely.") from error
    finally:
      os.close(temporary_fd)

    try:
      os.replace(
        temporary_name,
        SETTINGS_FILE_NAME,
        src_dir_fd=directory_fd,
        dst_dir_fd=directory_fd,
      )
      temporary_name = None
      _sync_directory(directory_fd)
    except OSError as error:
      raise SettingsStoreError("ClearRead could not commit its settings atomically.") from error
  finally:
    if temporary_name is not None:
      try:
        os.unlink(temporary_name, dir_fd=directory_fd)
      except OSError:
        pass
    os.close(directory_fd)

  return canonical.rstrip(b"\n")
