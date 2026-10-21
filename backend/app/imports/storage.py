"""Immutable local content-addressed storage for uploaded source files.

This module deliberately has no database dependency.  It owns only the local
filesystem boundary; database leases and references are coordinated by the
ingest service.
"""

from __future__ import annotations

import csv
import ctypes
import errno
import hashlib
import io
import os
import re
import stat
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Never, Protocol, cast
from uuid import UUID

STREAM_CHUNK_BYTES = 1024 * 1024

_DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_PREFIX_PATTERN = re.compile(r"[0-9a-f]{2}\Z", re.ASCII)
_STORAGE_KEY_PATTERN = re.compile(
    r"sha256/([0-9a-f]{2})/([0-9a-f]{64})\Z",
    re.ASCII,
)
_TEMPORARY_KEY_PATTERN = re.compile(
    r"\.ingest/(?P<token>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12})\.part\Z",
    re.ASCII,
)
_REPARSE_POINT_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_BUSY_ERRNOS = frozenset(
    value
    for value in (
        getattr(errno, "EACCES", None),
        getattr(errno, "EBUSY", None),
        getattr(errno, "EPERM", None),
        getattr(errno, "ETXTBSY", None),
    )
    if value is not None
)
_BUSY_WINDOWS_ERRORS = frozenset({5, 32, 33})
_CROSS_DEVICE_WINDOWS_ERROR = 17


class ContentStoreError(RuntimeError):
    """Base class for local content-store failures."""


class StorageConfigurationError(ContentStoreError):
    """The configured storage boundary is unsafe or unsupported."""


class InvalidStorageKeyError(StorageConfigurationError):
    """A storage key is not in the canonical content-addressed form."""


class StorageOperationError(ContentStoreError):
    """A filesystem operation failed for an otherwise valid store."""


class CrossDeviceStorageError(StorageOperationError):
    """A hard-link operation crossed a filesystem boundary."""


class StorageBusyError(StorageOperationError):
    """A storage path was locked, busy, or inaccessible."""


class TemporaryContentExistsError(StorageOperationError):
    """A lease token already has a temporary upload object."""


class UploadTooLargeError(ContentStoreError):
    """A streamed upload exceeded the configured byte limit."""


class ContentIntegrityError(ContentStoreError):
    """Stored or staged bytes do not match their immutable identity."""


class ContentNotFoundError(ContentIntegrityError):
    """An expected content object is missing."""


class ContentSizeMismatchError(ContentIntegrityError):
    """A content object has a different byte length from its database record."""


class ContentHashMismatchError(ContentIntegrityError):
    """A content object has a different digest from its database record."""


class ContentPreviewError(ContentStoreError):
    """A bounded text preview could not be decoded or parsed safely."""


class BinaryReadStream(Protocol):
    """Minimal pull interface accepted by streaming storage writes."""

    def read(self, size: int = -1) -> bytes: ...


class _WindowsCtypesAPI(Protocol):
    """Windows-only ctypes names omitted from non-Windows type stubs."""

    WinDLL: type[ctypes.CDLL]

    def WinError(
        self,
        code: int | None = None,
        descr: str | None = None,
    ) -> OSError: ...

    def get_last_error(self) -> int: ...


def _windows_ctypes_api() -> _WindowsCtypesAPI:
    """Return the native ctypes module through its Windows-only surface."""

    return cast(_WindowsCtypesAPI, ctypes)


@dataclass(frozen=True, slots=True)
class StagedContent:
    """A fully written and synchronised object in the ingest directory."""

    lease_token: UUID
    temporary_key: str
    path: Path
    sha256_hex: str
    size_bytes: int

    @property
    def token(self) -> UUID:
        """Compatibility alias for orchestration code."""

        return self.lease_token

    @property
    def temp_key(self) -> str:
        """Compatibility alias for orchestration code."""

        return self.temporary_key


@dataclass(frozen=True, slots=True)
class StoredContent:
    """A published immutable content object."""

    storage_key: str
    sha256_hex: str
    size_bytes: int
    reused: bool


@dataclass(frozen=True, slots=True)
class ContentObject:
    """A canonical object discovered during local reconciliation."""

    storage_key: str
    path: Path
    size_bytes: int
    modified_at: datetime


@dataclass(frozen=True, slots=True)
class CsvPreview:
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    truncated: bool


@dataclass(frozen=True, slots=True)
class TemporaryObject:
    """A canonical private upload object discovered during reconciliation."""

    lease_token: UUID
    temporary_key: str
    path: Path
    size_bytes: int
    modified_at: datetime


@dataclass(frozen=True, slots=True)
class QuarantinedContent:
    """A content object moved outside the live content namespace."""

    storage_key: str
    quarantine_key: str
    path: Path
    size_bytes: int


@dataclass(frozen=True, slots=True)
class QuarantinedTemporary:
    """An abandoned private upload moved out of the live ingest namespace."""

    lease_token: UUID
    temporary_key: str
    quarantine_key: str
    path: Path
    size_bytes: int


def _stat_is_reparse_point(path_stat: os.stat_result) -> bool:
    """Return whether a stat result represents a symlink or Windows reparse point."""

    file_attributes = int(getattr(path_stat, "st_file_attributes", 0))
    return stat.S_ISLNK(path_stat.st_mode) or bool(
        file_attributes & _REPARSE_POINT_ATTRIBUTE
    )


def _device_id(path: Path) -> int:
    try:
        return path.stat(follow_symlinks=False).st_dev
    except OSError as error:
        _raise_storage_error(f"inspect filesystem device for {path}", error)


def _raise_storage_error(action: str, error: OSError) -> Never:
    windows_error = getattr(error, "winerror", None)
    if error.errno == errno.EXDEV or windows_error == _CROSS_DEVICE_WINDOWS_ERROR:
        raise CrossDeviceStorageError(
            f"{action} crossed a filesystem boundary; hard-link publication "
            "requires one filesystem"
        ) from error
    if error.errno in _BUSY_ERRNOS or windows_error in _BUSY_WINDOWS_ERRORS:
        raise StorageBusyError(f"{action} failed because storage is busy") from error
    raise StorageOperationError(f"{action} failed: {error}") from error


def _require_digest(value: str, *, label: str) -> str:
    if not isinstance(value, str) or _DIGEST_PATTERN.fullmatch(value) is None:
        raise InvalidStorageKeyError(
            f"{label} must be exactly 64 lowercase hexadecimal characters"
        )
    return value


def _parse_storage_key(storage_key: str) -> str:
    if not isinstance(storage_key, str):
        raise InvalidStorageKeyError("storage key must be a string")
    match = _STORAGE_KEY_PATTERN.fullmatch(storage_key)
    if match is None or match.group(1) != match.group(2)[:2]:
        raise InvalidStorageKeyError(
            "storage key must use canonical sha256/xx/<64 lowercase hex> form"
        )
    return match.group(2)


def _storage_key(digest: str) -> str:
    return f"sha256/{digest[:2]}/{digest}"


def _identity(path_stat: os.stat_result) -> tuple[int, int]:
    return path_stat.st_dev, path_stat.st_ino


def _safe_regular_stat(path: Path, *, label: str) -> os.stat_result:
    try:
        path_stat = path.lstat()
    except FileNotFoundError as error:
        raise ContentNotFoundError(f"{label} is missing: {path}") from error
    except OSError as error:
        _raise_storage_error(f"inspect {label}", error)

    if _stat_is_reparse_point(path_stat):
        raise ContentIntegrityError(f"{label} is a symlink or reparse point: {path}")
    if not stat.S_ISREG(path_stat.st_mode):
        raise ContentIntegrityError(f"{label} is not a regular file: {path}")
    return path_stat


def _sha256_and_size(path: Path, *, label: str) -> tuple[str, int]:
    before = _safe_regular_stat(path, label=label)
    hasher = hashlib.sha256()
    size_bytes = 0
    try:
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            if _stat_is_reparse_point(opened) or not stat.S_ISREG(opened.st_mode):
                raise ContentIntegrityError(f"{label} is not a safe regular file")
            if _identity(opened) != _identity(before):
                raise ContentIntegrityError(f"{label} changed while it was opened")

            while chunk := handle.read(STREAM_CHUNK_BYTES):
                hasher.update(chunk)
                size_bytes += len(chunk)

            after_read = os.fstat(handle.fileno())
    except ContentIntegrityError:
        raise
    except FileNotFoundError as error:
        raise ContentNotFoundError(
            f"{label} disappeared while reading: {path}"
        ) from error
    except OSError as error:
        _raise_storage_error(f"read {label}", error)

    after = _safe_regular_stat(path, label=label)
    stable_fields_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    stable_fields_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    if (
        stable_fields_after != stable_fields_before
        or _identity(after_read) != _identity(before)
        or after_read.st_size != before.st_size
        or after_read.st_mtime_ns != before.st_mtime_ns
        or size_bytes != before.st_size
    ):
        raise ContentIntegrityError(f"{label} changed while it was being read")
    return hasher.hexdigest(), size_bytes


def _read_bounded_bytes_and_identity(
    path: Path,
    *,
    label: str,
    expected_size: int,
    maximum_size: int,
) -> tuple[bytes, str]:
    """Read at most the trusted bound while enforcing stable file identity."""

    before = _safe_regular_stat(path, label=label)
    if before.st_size != expected_size:
        raise ContentSizeMismatchError(
            f"{label} size mismatch: expected {expected_size}, found {before.st_size}"
        )
    if before.st_size > maximum_size:
        raise UploadTooLargeError(
            f"{label} exceeds the configured read limit ({maximum_size} bytes)"
        )

    try:
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            if _stat_is_reparse_point(opened) or not stat.S_ISREG(opened.st_mode):
                raise ContentIntegrityError(f"{label} is not a safe regular file")
            if _identity(opened) != _identity(before):
                raise ContentIntegrityError(f"{label} changed while it was opened")
            content = handle.read(expected_size + 1)
            after_read = os.fstat(handle.fileno())
    except ContentStoreError:
        raise
    except FileNotFoundError as error:
        raise ContentNotFoundError(
            f"{label} disappeared while reading: {path}"
        ) from error
    except OSError as error:
        _raise_storage_error(f"read {label}", error)

    if len(content) != expected_size:
        raise ContentSizeMismatchError(
            f"{label} size mismatch: expected {expected_size}, found at least "
            f"{len(content)}"
        )
    after = _safe_regular_stat(path, label=label)
    stable_fields_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    stable_fields_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    if (
        stable_fields_after != stable_fields_before
        or _identity(after_read) != _identity(before)
        or after_read.st_size != before.st_size
        or after_read.st_mtime_ns != before.st_mtime_ns
    ):
        raise ContentIntegrityError(f"{label} changed while it was being read")
    return content, hashlib.sha256(content).hexdigest()


def _files_equal(left: Path, right: Path) -> bool:
    """Compare two safe regular files byte for byte without trusting a digest."""

    left_stat = _safe_regular_stat(left, label="staged content")
    right_stat = _safe_regular_stat(right, label="existing content object")
    if left_stat.st_size != right_stat.st_size:
        return False

    try:
        with left.open("rb") as left_handle, right.open("rb") as right_handle:
            if _identity(os.fstat(left_handle.fileno())) != _identity(left_stat):
                raise ContentIntegrityError(
                    "staged content changed while it was opened"
                )
            if _identity(os.fstat(right_handle.fileno())) != _identity(right_stat):
                raise ContentIntegrityError(
                    "existing content object changed while it was opened"
                )
            while True:
                left_chunk = left_handle.read(STREAM_CHUNK_BYTES)
                right_chunk = right_handle.read(STREAM_CHUNK_BYTES)
                if left_chunk != right_chunk:
                    return False
                if not left_chunk:
                    return True
    except ContentIntegrityError:
        raise
    except FileNotFoundError as error:
        raise ContentNotFoundError(
            "content disappeared during byte-for-byte comparison"
        ) from error
    except OSError as error:
        _raise_storage_error("compare content objects", error)


def _windows_extended_path(path: Path) -> str:
    path_text = os.path.abspath(os.fspath(path))
    if path_text.startswith("\\\\?\\"):
        return path_text
    if path_text.startswith("\\\\"):
        return f"\\\\?\\UNC\\{path_text[2:]}"
    return f"\\\\?\\{path_text}"


def _raise_windows_directory_error(
    action: str,
    path: Path,
    error: OSError,
) -> Never:
    if getattr(error, "winerror", None) in {1, 5, 6, 50, 87}:
        raise StorageConfigurationError(
            f"{action} is unsupported or denied for the configured Windows "
            f"storage directory: {path}"
        ) from error
    _raise_storage_error(f"{action} {path}", error)


def _assert_supported_windows_volume(path: Path) -> None:
    """Require the Windows storage root to reside on a local NTFS volume."""

    from ctypes import wintypes

    windows_ctypes = _windows_ctypes_api()
    kernel32 = windows_ctypes.WinDLL("kernel32", use_last_error=True)
    get_volume_path_name = kernel32.GetVolumePathNameW
    get_volume_path_name.argtypes = (
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.DWORD,
    )
    get_volume_path_name.restype = wintypes.BOOL
    get_drive_type = kernel32.GetDriveTypeW
    get_drive_type.argtypes = (wintypes.LPCWSTR,)
    get_drive_type.restype = wintypes.UINT
    get_volume_information = kernel32.GetVolumeInformationW
    get_volume_information.argtypes = (
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPWSTR,
        wintypes.DWORD,
    )
    get_volume_information.restype = wintypes.BOOL

    volume_path = ctypes.create_unicode_buffer(32768)
    if not get_volume_path_name(
        _windows_extended_path(path),
        volume_path,
        len(volume_path),
    ):
        _raise_windows_directory_error(
            "identify Windows storage volume",
            path,
            windows_ctypes.WinError(windows_ctypes.get_last_error()),
        )

    drive_fixed = 3
    if get_drive_type(volume_path.value) != drive_fixed:
        raise StorageConfigurationError(
            "Windows storage root must use a local fixed NTFS volume; "
            f"unsupported volume for {path}"
        )

    filesystem_name = ctypes.create_unicode_buffer(256)
    if not get_volume_information(
        volume_path.value,
        None,
        0,
        None,
        None,
        None,
        filesystem_name,
        len(filesystem_name),
    ):
        _raise_windows_directory_error(
            "inspect Windows storage filesystem",
            path,
            windows_ctypes.WinError(windows_ctypes.get_last_error()),
        )
    if filesystem_name.value.casefold() != "ntfs":
        raise StorageConfigurationError(
            "Windows storage root must use NTFS; "
            f"found {filesystem_name.value or 'unknown'} for {path}"
        )


def _flush_windows_directory(path: Path) -> None:
    """Flush a local Windows directory handle without silently degrading."""

    from ctypes import wintypes

    generic_write = 0x40000000
    share_read_write_delete = 0x00000001 | 0x00000002 | 0x00000004
    open_existing = 3
    file_flag_backup_semantics = 0x02000000
    file_flag_open_reparse_point = 0x00200000

    windows_ctypes = _windows_ctypes_api()
    kernel32 = windows_ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    flush_file_buffers = kernel32.FlushFileBuffers
    flush_file_buffers.argtypes = (wintypes.HANDLE,)
    flush_file_buffers.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL

    handle = create_file(
        _windows_extended_path(path),
        generic_write,
        share_read_write_delete,
        None,
        open_existing,
        file_flag_backup_semantics | file_flag_open_reparse_point,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle == invalid_handle:
        _raise_windows_directory_error(
            "open directory for synchronisation",
            path,
            windows_ctypes.WinError(windows_ctypes.get_last_error()),
        )

    flush_error: OSError | None = None
    close_error: OSError | None = None
    try:
        if not flush_file_buffers(handle):
            flush_error = windows_ctypes.WinError(windows_ctypes.get_last_error())
    finally:
        if not close_handle(handle):
            close_error = windows_ctypes.WinError(windows_ctypes.get_last_error())
    if flush_error is not None:
        _raise_windows_directory_error("synchronise directory", path, flush_error)
    if close_error is not None:
        _raise_windows_directory_error(
            "close synchronised directory handle for",
            path,
            close_error,
        )


def _fsync_directory(path: Path) -> None:
    """Persist a managed directory entry or fail the storage operation."""

    if os.name == "nt":
        _flush_windows_directory(path)
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as error:
        _raise_storage_error(f"synchronise directory {path}", error)


class LocalContentStore:
    """Filesystem-only immutable SHA-256 content store."""

    def __init__(self, root: Path, max_upload_bytes: int) -> None:
        supplied_root = Path(root)
        if not supplied_root.is_absolute():
            raise StorageConfigurationError("storage root must be an absolute path")
        if supplied_root == Path(supplied_root.anchor):
            raise StorageConfigurationError(
                "storage root must not be a filesystem root"
            )
        if type(max_upload_bytes) is not int or max_upload_bytes <= 0:
            raise StorageConfigurationError(
                "max_upload_bytes must be a positive integer"
            )

        self.root = Path(os.path.abspath(os.fspath(supplied_root)))
        self.max_upload_bytes = max_upload_bytes
        self._ingest_root = self.root / ".ingest"
        self._content_root = self.root / "sha256"
        self._quarantine_root = self.root / ".quarantine"
        self._managed_roots = frozenset(
            {
                self.root,
                self._ingest_root,
                self._content_root,
                self._quarantine_root,
            }
        )
        self._confirmed_managed_directory_entries: set[
            tuple[Path, tuple[int, int], tuple[int, int]]
        ] = set()

    def assert_ready(self) -> None:
        """Create and validate the managed storage directories."""

        self._assert_existing_components_safe(self.root.parent)
        self._create_directory(self.root, label="storage root")
        if os.name == "nt":
            _assert_supported_windows_volume(self.root)
        self._create_directory(self._ingest_root, label="ingest directory")
        self._create_directory(self._content_root, label="content directory")
        self._create_directory(self._quarantine_root, label="quarantine directory")

        devices = {
            _device_id(self.root),
            _device_id(self._ingest_root),
            _device_id(self._content_root),
            _device_id(self._quarantine_root),
        }
        if len(devices) != 1:
            raise StorageConfigurationError(
                "storage root, ingest, content, and quarantine directories must use "
                "the same filesystem"
            )

    def temporary_key(self, token: UUID) -> str:
        """Return the only accepted temporary key for a lease token."""

        if not isinstance(token, UUID):
            raise TypeError("token must be a UUID")
        return f".ingest/{token}.part"

    def write_stream(self, token: UUID, source: BinaryReadStream) -> StagedContent:
        """Stream, hash, flush, and synchronise an upload into private staging."""

        self.assert_ready()
        temporary_key = self.temporary_key(token)
        temporary_path = self.root / temporary_key
        hasher = hashlib.sha256()
        size_bytes = 0
        created = False

        try:
            with temporary_path.open("xb") as handle:
                created = True
                if os.name != "nt":
                    os.fchmod(handle.fileno(), 0o600)
                while True:
                    chunk = source.read(STREAM_CHUNK_BYTES)
                    if not isinstance(chunk, (bytes, bytearray, memoryview)):
                        raise TypeError("binary upload stream must return bytes")
                    bytes_chunk = bytes(chunk)
                    if not bytes_chunk:
                        break
                    observed_size = size_bytes + len(bytes_chunk)
                    if observed_size > self.max_upload_bytes:
                        raise UploadTooLargeError(
                            "upload exceeds max_upload_bytes "
                            f"({self.max_upload_bytes}); observed at least "
                            f"{observed_size} bytes"
                        )
                    written = handle.write(bytes_chunk)
                    if written != len(bytes_chunk):
                        raise StorageOperationError(
                            "short write while staging uploaded content"
                        )
                    hasher.update(bytes_chunk)
                    size_bytes = observed_size
                handle.flush()
                os.fsync(handle.fileno())
            _fsync_directory(self._ingest_root)
        except FileExistsError as error:
            raise TemporaryContentExistsError(
                f"temporary content already exists for lease token {token}"
            ) from error
        except UploadTooLargeError, TypeError, StorageOperationError:
            if created:
                self._best_effort_unlink(temporary_path)
            raise
        except OSError as error:
            if created:
                self._best_effort_unlink(temporary_path)
            _raise_storage_error("write staged content", error)
        except BaseException:
            if created:
                self._best_effort_unlink(temporary_path)
            raise

        return StagedContent(
            lease_token=token,
            temporary_key=temporary_key,
            path=temporary_path,
            sha256_hex=hasher.hexdigest(),
            size_bytes=size_bytes,
        )

    def promote(self, staged: StagedContent) -> StoredContent:
        """Publish staged bytes with a non-overwriting atomic hard link."""

        self.assert_ready()
        self._validate_staged_identity(staged)
        actual_digest, actual_size = _sha256_and_size(
            staged.path,
            label="staged content",
        )
        if actual_digest != staged.sha256_hex or actual_size != staged.size_bytes:
            raise ContentIntegrityError(
                "staged content no longer matches its recorded digest and size"
            )

        storage_key = _storage_key(staged.sha256_hex)
        prefix_root = self._content_root / staged.sha256_hex[:2]
        self._create_directory(prefix_root, label="content prefix directory")
        self._assert_same_device(prefix_root)
        final_path = self.root / storage_key

        try:
            os.link(staged.path, final_path, follow_symlinks=False)
        except FileExistsError:
            return self._reuse_existing(staged, storage_key, final_path)
        except FileNotFoundError as error:
            if not staged.path.exists():
                raise ContentNotFoundError(
                    "staged content disappeared before publication"
                ) from error
            _raise_storage_error("publish content object", error)
        except OSError as error:
            _raise_storage_error("publish content object", error)

        published_stat = _safe_regular_stat(
            final_path, label="published content object"
        )
        published_identity = _identity(published_stat)
        if published_identity != _identity(
            _safe_regular_stat(staged.path, label="staged content")
        ):
            self._remove_created_link(final_path, published_identity)
            raise ContentIntegrityError(
                "published content object is not linked to staged content"
            )
        try:
            published_digest, published_size = _sha256_and_size(
                final_path,
                label="published content object",
            )
            if (
                published_digest != staged.sha256_hex
                or published_size != staged.size_bytes
            ):
                raise ContentIntegrityError(
                    "published content object does not match the staged identity"
                )
        except ContentStoreError:
            self._remove_created_link(final_path, published_identity)
            raise

        final_after_validation = _safe_regular_stat(
            final_path,
            label="published content object",
        )
        staged_after_validation = _safe_regular_stat(
            staged.path,
            label="staged content",
        )
        if (
            _identity(final_after_validation) != published_identity
            or _identity(staged_after_validation) != published_identity
        ):
            self._remove_created_link(final_path, published_identity)
            raise ContentIntegrityError(
                "published or staged content changed after validation"
            )
        _fsync_directory(final_path.parent)
        self._unlink_staged(staged.path)
        _fsync_directory(self._ingest_root)
        return StoredContent(
            storage_key=storage_key,
            sha256_hex=staged.sha256_hex,
            size_bytes=staged.size_bytes,
            reused=False,
        )

    def discard_staged(self, staged: StagedContent) -> None:
        """Idempotently delete only the token's exact private staging path."""

        self._validate_staged_identity(staged)
        self.assert_ready()
        try:
            staged_stat = staged.path.lstat()
        except FileNotFoundError:
            _fsync_directory(staged.path.parent)
            return
        except OSError as error:
            _raise_storage_error("inspect staged content for discard", error)
        if _stat_is_reparse_point(staged_stat) or not stat.S_ISREG(staged_stat.st_mode):
            raise StorageConfigurationError(
                "staged path is not a safe regular file and will not be deleted"
            )
        try:
            staged.path.unlink()
        except FileNotFoundError:
            _fsync_directory(staged.path.parent)
            return
        except OSError as error:
            _raise_storage_error("discard staged content", error)
        _fsync_directory(self._ingest_root)

    def inspect(
        self,
        storage_key: str,
        expected_sha256_hex: str,
        expected_size: int,
    ) -> ContentObject:
        """Check canonical metadata without opening or hashing file content."""

        self.assert_ready()
        key_digest = _parse_storage_key(storage_key)
        expected_digest = _require_digest(
            expected_sha256_hex,
            label="expected SHA-256",
        )
        if isinstance(expected_size, bool) or expected_size < 0:
            raise StorageConfigurationError("expected size must be non-negative")
        if key_digest != expected_digest:
            raise ContentIntegrityError(
                "storage key digest does not match the expected SHA-256"
            )
        path = self.root / storage_key
        path_stat = _safe_regular_stat(path, label="content object")
        if path_stat.st_size != expected_size:
            raise ContentSizeMismatchError(
                f"content object size mismatch: expected {expected_size}, "
                f"found {path_stat.st_size}"
            )
        return ContentObject(
            storage_key=storage_key,
            path=path,
            size_bytes=path_stat.st_size,
            modified_at=datetime.fromtimestamp(path_stat.st_mtime, tz=UTC),
        )

    def read_csv_preview(
        self,
        storage_key: str,
        expected_sha256_hex: str,
        expected_size: int,
        *,
        encoding: str,
        row_limit: int,
    ) -> CsvPreview:
        """Stream one header and a bounded number of CSV rows."""

        if encoding not in {"utf-8-sig", "utf-8", "windows-1252"}:
            raise ContentPreviewError("unsupported preview encoding")
        if isinstance(row_limit, bool) or not 1 <= row_limit <= 200:
            raise ContentPreviewError("row_limit must be between 1 and 200")
        content_object = self.inspect(
            storage_key,
            expected_sha256_hex,
            expected_size,
        )
        before = _safe_regular_stat(content_object.path, label="content object")
        try:
            with content_object.path.open("rb") as binary_handle:
                opened = os.fstat(binary_handle.fileno())
                if _identity(opened) != _identity(before):
                    raise ContentIntegrityError(
                        "content object changed while it was opened"
                    )
                with io.TextIOWrapper(
                    binary_handle,
                    encoding=encoding,
                    errors="strict",
                    newline="",
                ) as text_handle:
                    reader = csv.reader(text_handle)
                    try:
                        headers = tuple(next(reader))
                    except StopIteration:
                        headers = ()
                    rows: list[tuple[str, ...]] = []
                    truncated = False
                    for row in reader:
                        if len(rows) >= row_limit:
                            truncated = True
                            break
                        rows.append(tuple(row))
                    after_read = os.fstat(binary_handle.fileno())
        except (UnicodeDecodeError, csv.Error) as error:
            raise ContentPreviewError(
                "The source file could not be decoded as CSV with this encoding."
            ) from error
        except ContentStoreError:
            raise
        except FileNotFoundError as error:
            raise ContentNotFoundError(
                "content object disappeared while reading preview"
            ) from error
        except OSError as error:
            _raise_storage_error("read content preview", error)
        after = _safe_regular_stat(content_object.path, label="content object")
        stable_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        )
        stable_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        )
        if stable_after != stable_before or _identity(after_read) != _identity(before):
            raise ContentIntegrityError(
                "content object changed while its preview was being read"
            )
        return CsvPreview(headers=headers, rows=tuple(rows), truncated=truncated)

    def validate(
        self,
        storage_key: str,
        expected_sha256_hex: str,
        expected_size: int,
    ) -> bool:
        """Re-read an object and verify its key, digest, and exact size."""

        self.assert_ready()
        key_digest = _parse_storage_key(storage_key)
        expected_digest = _require_digest(
            expected_sha256_hex,
            label="expected SHA-256",
        )
        if isinstance(expected_size, bool) or expected_size < 0:
            raise StorageConfigurationError("expected size must be non-negative")
        if key_digest != expected_digest:
            raise ContentIntegrityError(
                "storage key digest does not match the expected SHA-256"
            )

        actual_digest, actual_size = _sha256_and_size(
            self.root / storage_key,
            label="content object",
        )
        if actual_size != expected_size:
            raise ContentSizeMismatchError(
                f"content object size mismatch: expected {expected_size}, "
                f"found {actual_size}"
            )
        if actual_digest != expected_digest:
            raise ContentHashMismatchError(
                "content object digest mismatch: "
                f"expected {expected_digest}, found {actual_digest}"
            )
        return True

    def read_bytes(
        self,
        storage_key: str,
        expected_sha256_hex: str,
        expected_size: int,
    ) -> bytes:
        """Read one immutable object after verifying its complete identity."""

        self.assert_ready()
        key_digest = _parse_storage_key(storage_key)
        expected_digest = _require_digest(
            expected_sha256_hex,
            label="expected SHA-256",
        )
        if isinstance(expected_size, bool) or expected_size < 0:
            raise StorageConfigurationError("expected size must be non-negative")
        if key_digest != expected_digest:
            raise ContentIntegrityError(
                "storage key digest does not match the expected SHA-256"
            )

        content, actual_digest = _read_bounded_bytes_and_identity(
            self.root / storage_key,
            label="content object",
            expected_size=expected_size,
            maximum_size=self.max_upload_bytes,
        )
        if actual_digest != expected_digest:
            raise ContentHashMismatchError(
                "content object digest mismatch: "
                f"expected {expected_digest}, found {actual_digest}"
            )
        return content

    def iter_objects(self) -> Iterable[ContentObject]:
        """Yield only canonical direct children of the SHA-256 namespace."""

        self.assert_ready()
        for prefix_path in self._directory_entries(self._content_root):
            if _PREFIX_PATTERN.fullmatch(prefix_path.name) is None:
                continue
            if not self._is_safe_directory_for_enumeration(prefix_path):
                continue
            for object_path in self._directory_entries(prefix_path):
                storage_key = f"sha256/{prefix_path.name}/{object_path.name}"
                try:
                    _parse_storage_key(storage_key)
                except InvalidStorageKeyError:
                    continue
                try:
                    object_stat = object_path.lstat()
                except FileNotFoundError:
                    continue
                except OSError as error:
                    _raise_storage_error("inspect content object", error)
                if _stat_is_reparse_point(object_stat) or not stat.S_ISREG(
                    object_stat.st_mode
                ):
                    continue
                yield ContentObject(
                    storage_key=storage_key,
                    path=object_path,
                    size_bytes=object_stat.st_size,
                    modified_at=datetime.fromtimestamp(object_stat.st_mtime, UTC),
                )

    def iter_temporary_objects(self) -> Iterable[TemporaryObject]:
        """Yield only canonical UUID-named regular files from ``.ingest``."""

        self.assert_ready()
        for object_path in self._directory_entries(self._ingest_root):
            temporary_key = f".ingest/{object_path.name}"
            match = _TEMPORARY_KEY_PATTERN.fullmatch(temporary_key)
            if match is None:
                continue
            try:
                token = UUID(match.group("token"))
                object_stat = object_path.lstat()
            except ValueError, FileNotFoundError:
                continue
            except OSError as error:
                _raise_storage_error("inspect temporary content object", error)
            if (
                str(token) != match.group("token")
                or _stat_is_reparse_point(object_stat)
                or not stat.S_ISREG(object_stat.st_mode)
            ):
                continue
            yield TemporaryObject(
                lease_token=token,
                temporary_key=temporary_key,
                path=object_path,
                size_bytes=object_stat.st_size,
                modified_at=datetime.fromtimestamp(object_stat.st_mtime, UTC),
            )

    def quarantine(
        self,
        storage_key: str,
        scan_id: UUID,
    ) -> QuarantinedContent | None:
        """Atomically remove one live object into a scan-specific quarantine."""

        self.assert_ready()
        _parse_storage_key(storage_key)
        if not isinstance(scan_id, UUID):
            raise TypeError("scan_id must be a UUID")

        source_path = self.root / storage_key
        try:
            source_stat = _safe_regular_stat(
                source_path,
                label="content object selected for quarantine",
            )
        except ContentNotFoundError:
            _fsync_directory(source_path.parent)
            return None

        quarantine_key = f"{scan_id}/{storage_key}"
        scan_root = self._quarantine_root / str(scan_id)
        algorithm_root = scan_root / "sha256"
        prefix_root = algorithm_root / storage_key.split("/")[1]
        for path, label in (
            (scan_root, "quarantine scan directory"),
            (algorithm_root, "quarantine algorithm directory"),
            (prefix_root, "quarantine prefix directory"),
        ):
            self._create_directory(path, label=label)
            self._assert_same_device(path)
        destination_path = self._quarantine_root / quarantine_key

        try:
            os.link(source_path, destination_path, follow_symlinks=False)
        except FileExistsError as error:
            destination_stat = _safe_regular_stat(
                destination_path,
                label="existing quarantine object",
            )
            try:
                destination_matches = _files_equal(source_path, destination_path)
            except ContentNotFoundError:
                try:
                    source_path.lstat()
                except FileNotFoundError:
                    _fsync_directory(source_path.parent)
                    return None
                except OSError as inspect_error:
                    _raise_storage_error(
                        "inspect concurrently changed quarantine source",
                        inspect_error,
                    )
                raise
            if not destination_matches:
                raise ContentIntegrityError(
                    "existing quarantine destination contains different bytes"
                ) from error
        except FileNotFoundError as error:
            try:
                source_path.lstat()
            except FileNotFoundError:
                _fsync_directory(source_path.parent)
                return None
            except OSError as inspect_error:
                _raise_storage_error(
                    "inspect concurrently changed quarantine source",
                    inspect_error,
                )
            _raise_storage_error("quarantine content object", error)
        except OSError as error:
            _raise_storage_error("quarantine content object", error)
        else:
            destination_stat = _safe_regular_stat(
                destination_path,
                label="quarantined content object",
            )
            if _identity(destination_stat) != _identity(source_stat):
                raise ContentIntegrityError(
                    "quarantine destination is not linked to its source"
                )

        _fsync_directory(destination_path.parent)
        try:
            source_path.unlink()
        except FileNotFoundError:
            pass
        except OSError as error:
            _raise_storage_error("remove quarantined content from live storage", error)
        _fsync_directory(source_path.parent)

        return QuarantinedContent(
            storage_key=storage_key,
            quarantine_key=quarantine_key,
            path=destination_path,
            size_bytes=destination_stat.st_size,
        )

    def quarantine_temporary(
        self,
        temporary: TemporaryObject,
        scan_id: UUID,
    ) -> QuarantinedTemporary | None:
        """Move one abandoned private upload to scan-specific quarantine."""

        self.assert_ready()
        self._validate_temporary_object_identity(temporary)
        if not isinstance(scan_id, UUID):
            raise TypeError("scan_id must be a UUID")

        try:
            source_stat = _safe_regular_stat(
                temporary.path,
                label="temporary content selected for quarantine",
            )
        except ContentNotFoundError:
            _fsync_directory(temporary.path.parent)
            return None

        quarantine_key = f"{scan_id}/{temporary.temporary_key}"
        scan_root = self._quarantine_root / str(scan_id)
        ingest_root = scan_root / ".ingest"
        for path, label in (
            (scan_root, "quarantine scan directory"),
            (ingest_root, "quarantine ingest directory"),
        ):
            self._create_directory(path, label=label)
            self._assert_same_device(path)
        destination_path = self._quarantine_root / quarantine_key

        try:
            os.link(temporary.path, destination_path, follow_symlinks=False)
        except FileExistsError as error:
            destination_stat = _safe_regular_stat(
                destination_path,
                label="existing quarantined temporary content",
            )
            try:
                destination_matches = _files_equal(
                    temporary.path,
                    destination_path,
                )
            except ContentNotFoundError:
                try:
                    temporary.path.lstat()
                except FileNotFoundError:
                    _fsync_directory(temporary.path.parent)
                    return None
                except OSError as inspect_error:
                    _raise_storage_error(
                        "inspect concurrently changed temporary quarantine source",
                        inspect_error,
                    )
                raise
            if not destination_matches:
                raise ContentIntegrityError(
                    "existing temporary quarantine destination contains different bytes"
                ) from error
        except FileNotFoundError as error:
            try:
                temporary.path.lstat()
            except FileNotFoundError:
                _fsync_directory(temporary.path.parent)
                return None
            except OSError as inspect_error:
                _raise_storage_error(
                    "inspect concurrently changed temporary quarantine source",
                    inspect_error,
                )
            _raise_storage_error("quarantine temporary content", error)
        except OSError as error:
            _raise_storage_error("quarantine temporary content", error)
        else:
            destination_stat = _safe_regular_stat(
                destination_path,
                label="quarantined temporary content",
            )
            if _identity(destination_stat) != _identity(source_stat):
                raise ContentIntegrityError(
                    "temporary quarantine destination is not linked to its source"
                )

        _fsync_directory(destination_path.parent)
        try:
            temporary.path.unlink()
        except FileNotFoundError:
            pass
        except OSError as error:
            _raise_storage_error(
                "remove quarantined content from temporary storage",
                error,
            )
        _fsync_directory(temporary.path.parent)

        return QuarantinedTemporary(
            lease_token=temporary.lease_token,
            temporary_key=temporary.temporary_key,
            quarantine_key=quarantine_key,
            path=destination_path,
            size_bytes=destination_stat.st_size,
        )

    def _reuse_existing(
        self,
        staged: StagedContent,
        storage_key: str,
        final_path: Path,
    ) -> StoredContent:
        existing_digest, existing_size = _sha256_and_size(
            final_path,
            label="existing content object",
        )
        if existing_digest != staged.sha256_hex or existing_size != staged.size_bytes:
            raise ContentIntegrityError(
                "existing content object does not match its storage key, digest, "
                "or size"
            )
        if not _files_equal(staged.path, final_path):
            raise ContentIntegrityError(
                "existing content object has a SHA-256 collision with different bytes"
            )
        _fsync_directory(final_path.parent)
        self._unlink_staged(staged.path)
        _fsync_directory(self._ingest_root)
        return StoredContent(
            storage_key=storage_key,
            sha256_hex=staged.sha256_hex,
            size_bytes=staged.size_bytes,
            reused=True,
        )

    def _validate_staged_identity(self, staged: StagedContent) -> None:
        if not isinstance(staged, StagedContent):
            raise TypeError("staged must be a StagedContent instance")
        expected_key = self.temporary_key(staged.lease_token)
        expected_path = self.root / expected_key
        if staged.temporary_key != expected_key or staged.path != expected_path:
            raise StorageConfigurationError(
                "staged path and temporary key must match the lease token "
                "inside .ingest"
            )
        _require_digest(staged.sha256_hex, label="staged SHA-256")
        if isinstance(staged.size_bytes, bool) or staged.size_bytes < 0:
            raise StorageConfigurationError("staged size must be non-negative")

    def _validate_temporary_object_identity(
        self,
        temporary: TemporaryObject,
    ) -> None:
        if not isinstance(temporary, TemporaryObject):
            raise TypeError("temporary must be a TemporaryObject instance")
        expected_key = self.temporary_key(temporary.lease_token)
        if (
            temporary.temporary_key != expected_key
            or temporary.path != self.root / expected_key
        ):
            raise StorageConfigurationError(
                "temporary object path must match its lease token inside .ingest"
            )
        if isinstance(temporary.size_bytes, bool) or temporary.size_bytes < 0:
            raise StorageConfigurationError(
                "temporary object size must be non-negative"
            )

    def _unlink_staged(self, path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            return
        except OSError as error:
            _raise_storage_error("remove published staged content", error)

    @staticmethod
    def _remove_created_link(path: Path, expected_identity: tuple[int, int]) -> None:
        """Remove only the exact canonical inode created by this promotion."""

        try:
            current = path.lstat()
        except FileNotFoundError:
            return
        except OSError as error:
            _raise_storage_error("inspect invalid published content", error)
        if (
            _stat_is_reparse_point(current)
            or not stat.S_ISREG(current.st_mode)
            or _identity(current) != expected_identity
        ):
            raise ContentIntegrityError(
                "published path changed before invalid content could be removed"
            )
        try:
            path.unlink()
        except FileNotFoundError:
            return
        except OSError as error:
            _raise_storage_error("remove invalid published content", error)
        _fsync_directory(path.parent)

    @staticmethod
    def _best_effort_unlink(path: Path) -> None:
        with suppress(OSError):
            path.unlink(missing_ok=True)
            with suppress(ContentStoreError):
                _fsync_directory(path.parent)

    def _create_directory(self, path: Path, *, label: str) -> None:
        try:
            path.mkdir(mode=0o700, parents=False, exist_ok=False)
        except FileNotFoundError as error:
            raise StorageConfigurationError(
                f"parent directory is missing while creating {label}: {path}"
            ) from error
        except FileExistsError:
            pass
        except OSError as error:
            _raise_storage_error(f"create {label}", error)
        self._assert_existing_components_safe(path)
        if os.name != "nt":
            try:
                current_mode = stat.S_IMODE(path.lstat().st_mode)
                if current_mode != 0o700:
                    path.chmod(0o700)
                    _fsync_directory(path)
            except OSError as error:
                _raise_storage_error(f"protect {label}", error)

        try:
            directory_stat = path.lstat()
            parent_stat = path.parent.lstat()
        except OSError as error:
            _raise_storage_error(f"inspect {label} before synchronisation", error)
        confirmation = (
            path,
            _identity(directory_stat),
            _identity(parent_stat),
        )
        cache_confirmation = path in self._managed_roots
        if (
            cache_confirmation
            and confirmation in self._confirmed_managed_directory_entries
        ):
            return

        _fsync_directory(path)
        _fsync_directory(path.parent)

        try:
            directory_after_sync = path.lstat()
            parent_after_sync = path.parent.lstat()
        except OSError as error:
            _raise_storage_error(f"inspect {label} after synchronisation", error)
        if (
            _identity(directory_after_sync) != confirmation[1]
            or _identity(parent_after_sync) != confirmation[2]
            or not stat.S_ISDIR(directory_after_sync.st_mode)
            or not stat.S_ISDIR(parent_after_sync.st_mode)
            or _stat_is_reparse_point(directory_after_sync)
            or _stat_is_reparse_point(parent_after_sync)
        ):
            raise StorageConfigurationError(
                f"{label} or its parent changed during directory synchronisation: "
                f"{path}"
            )
        if cache_confirmation:
            self._confirmed_managed_directory_entries.add(confirmation)

    def _assert_existing_components_safe(self, path: Path) -> None:
        anchor = Path(path.anchor)
        candidates = [anchor]
        current = anchor
        for component in path.parts[1:]:
            current /= component
            candidates.append(current)

        for candidate in candidates:
            try:
                candidate_stat = candidate.lstat()
            except FileNotFoundError:
                break
            except OSError as error:
                _raise_storage_error("inspect storage path", error)
            if _stat_is_reparse_point(candidate_stat):
                raise StorageConfigurationError(
                    f"storage paths may not contain a symlink, junction, or reparse "
                    f"point: {candidate}"
                )
            if not stat.S_ISDIR(candidate_stat.st_mode):
                raise StorageConfigurationError(
                    f"storage path component is not a directory: {candidate}"
                )

    def _assert_same_device(self, path: Path) -> None:
        if _device_id(path) != _device_id(self._ingest_root):
            raise StorageConfigurationError(
                f"managed directory must be on the same filesystem as .ingest: {path}"
            )

    @staticmethod
    def _directory_entries(path: Path) -> list[Path]:
        try:
            return sorted(path.iterdir(), key=lambda entry: entry.name)
        except OSError as error:
            _raise_storage_error(f"enumerate directory {path}", error)

    @staticmethod
    def _is_safe_directory_for_enumeration(path: Path) -> bool:
        try:
            path_stat = path.lstat()
        except FileNotFoundError:
            return False
        except OSError as error:
            _raise_storage_error(f"inspect directory {path}", error)
        return stat.S_ISDIR(path_stat.st_mode) and not _stat_is_reparse_point(path_stat)
