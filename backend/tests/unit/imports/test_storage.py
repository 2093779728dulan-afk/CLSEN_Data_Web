from __future__ import annotations

import errno
import hashlib
import os
import stat
from datetime import UTC
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import BinaryIO, cast
from uuid import UUID, uuid4

import app.imports.storage as storage_module
import pytest
from app.imports.storage import (
    ContentHashMismatchError,
    ContentIntegrityError,
    ContentNotFoundError,
    ContentPreviewError,
    ContentSizeMismatchError,
    CrossDeviceStorageError,
    InvalidStorageKeyError,
    LocalContentStore,
    StagedContent,
    StorageBusyError,
    StorageConfigurationError,
    StorageOperationError,
    TemporaryContentExistsError,
    TemporaryObject,
    UploadTooLargeError,
)


def test_inspect_checks_metadata_without_hashing_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    stored = store.promote(_stage(store, b"a,b\n1,2\n"))
    monkeypatch.setattr(
        storage_module,
        "_sha256_and_size",
        lambda *args, **kwargs: pytest.fail("inspect must not hash content"),
    )

    inspected = store.inspect(
        stored.storage_key,
        stored.sha256_hex,
        stored.size_bytes,
    )

    assert inspected.path == store.root / stored.storage_key
    assert inspected.size_bytes == stored.size_bytes


def test_read_csv_preview_streams_only_the_requested_rows(tmp_path: Path) -> None:
    store = _store(tmp_path)
    content = b"sku,sales\n2301-White-S,10\n2301-White-M,20\n"
    stored = store.promote(_stage(store, content))

    preview = store.read_csv_preview(
        stored.storage_key,
        stored.sha256_hex,
        stored.size_bytes,
        encoding="utf-8",
        row_limit=1,
    )

    assert preview.headers == ("sku", "sales")
    assert preview.rows == (("2301-White-S", "10"),)
    assert preview.truncated is True


def test_read_csv_preview_handles_quoted_newlines(tmp_path: Path) -> None:
    store = _store(tmp_path)
    content = b'sku,note\n2301-White-S,"first\nsecond"\n'
    stored = store.promote(_stage(store, content))

    preview = store.read_csv_preview(
        stored.storage_key,
        stored.sha256_hex,
        stored.size_bytes,
        encoding="utf-8",
        row_limit=200,
    )

    assert preview.rows == (("2301-White-S", "first\nsecond"),)
    assert preview.truncated is False


def test_read_csv_preview_rejects_wrong_encoding(tmp_path: Path) -> None:
    store = _store(tmp_path)
    stored = store.promote(_stage(store, b"sku\n\xff\n"))

    with pytest.raises(ContentPreviewError, match="decoded"):
        store.read_csv_preview(
            stored.storage_key,
            stored.sha256_hex,
            stored.size_bytes,
            encoding="utf-8",
            row_limit=200,
        )


def _store(tmp_path: Path, *, limit: int = 4 * 1024 * 1024) -> LocalContentStore:
    return LocalContentStore(tmp_path / "objects", max_upload_bytes=limit)


def _stage(
    store: LocalContentStore,
    content: bytes,
    *,
    token: UUID | None = None,
) -> StagedContent:
    return store.write_stream(token or uuid4(), BytesIO(content))


class _RecordingReader:
    def __init__(self, content: bytes) -> None:
        self._source = BytesIO(content)
        self.request_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.request_sizes.append(size)
        return self._source.read(size)


class _TextEofReader:
    def read(self, size: int = -1) -> str:
        del size
        return ""


def test_storage_root_must_be_absolute() -> None:
    with pytest.raises(StorageConfigurationError, match="absolute"):
        LocalContentStore(Path("relative/storage"), max_upload_bytes=1024)


def test_upload_limit_must_be_positive(tmp_path: Path) -> None:
    with pytest.raises(StorageConfigurationError, match="positive"):
        LocalContentStore(tmp_path / "objects", max_upload_bytes=0)


def test_filesystem_root_is_rejected() -> None:
    filesystem_root = Path(Path.cwd().anchor)

    with pytest.raises(StorageConfigurationError, match="filesystem root"):
        LocalContentStore(filesystem_root, max_upload_bytes=1024)


def test_upload_limit_must_be_an_integer(tmp_path: Path) -> None:
    with pytest.raises(StorageConfigurationError, match="integer"):
        LocalContentStore(tmp_path / "objects", max_upload_bytes=1.5)  # type: ignore[arg-type]


def test_assert_ready_creates_private_and_content_directories(tmp_path: Path) -> None:
    store = _store(tmp_path)

    store.assert_ready()

    assert (store.root / ".ingest").is_dir()
    assert (store.root / "sha256").is_dir()
    assert (store.root / ".quarantine").is_dir()


def test_new_managed_directories_sync_their_entries_to_the_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    synced: list[Path] = []
    monkeypatch.setattr(storage_module, "_fsync_directory", synced.append)

    store.assert_ready()

    assert synced == [
        store.root,
        store.root.parent,
        store.root / ".ingest",
        store.root,
        store.root / "sha256",
        store.root,
        store.root / ".quarantine",
        store.root,
    ]


def test_existing_directory_retries_an_unconfirmed_parent_sync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    store.assert_ready()
    prefix_root = store.root / "sha256" / "aa"
    synced: list[Path] = []
    fail_parent_once = True

    def fail_first_parent_sync(path: Path) -> None:
        nonlocal fail_parent_once
        synced.append(path)
        if path == prefix_root.parent and fail_parent_once:
            fail_parent_once = False
            raise StorageOperationError("injected parent directory sync failure")

    monkeypatch.setattr(storage_module, "_fsync_directory", fail_first_parent_sync)

    with pytest.raises(StorageOperationError, match="parent directory sync"):
        store._create_directory(prefix_root, label="test prefix")

    assert prefix_root.is_dir()
    store._create_directory(prefix_root, label="test prefix")
    assert synced == [
        prefix_root,
        prefix_root.parent,
        prefix_root,
        prefix_root.parent,
    ]


def test_existing_directory_retries_an_unconfirmed_directory_sync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    store.assert_ready()
    prefix_root = store.root / "sha256" / "bb"
    synced: list[Path] = []
    fail_directory_once = True

    def fail_first_directory_sync(path: Path) -> None:
        nonlocal fail_directory_once
        synced.append(path)
        if path == prefix_root and fail_directory_once:
            fail_directory_once = False
            raise StorageOperationError("injected directory sync failure")

    monkeypatch.setattr(storage_module, "_fsync_directory", fail_first_directory_sync)

    with pytest.raises(StorageOperationError, match="directory sync failure"):
        store._create_directory(prefix_root, label="test prefix")

    assert prefix_root.is_dir()
    store._create_directory(prefix_root, label="test prefix")
    assert synced == [prefix_root, prefix_root, prefix_root.parent]


def test_replaced_managed_directory_does_not_reuse_a_sync_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    store.assert_ready()
    content_root = store.root / "sha256"
    replaced_root = content_root.with_name("replaced-sha256")
    content_root.rename(replaced_root)
    content_root.mkdir(mode=0o700)
    synced: list[Path] = []
    monkeypatch.setattr(storage_module, "_fsync_directory", synced.append)

    store.assert_ready()

    assert synced == [content_root, content_root.parent]


@pytest.mark.skipif(os.name != "nt", reason="Windows directory flush is unavailable")
def test_fsync_directory_uses_the_windows_flush_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flushed: list[Path] = []
    monkeypatch.setattr(storage_module, "_flush_windows_directory", flushed.append)

    storage_module._fsync_directory(tmp_path)

    assert flushed == [tmp_path]


@pytest.mark.skipif(os.name != "nt", reason="Windows volume checks are unavailable")
def test_assert_ready_checks_the_windows_storage_volume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    checked: list[Path] = []
    monkeypatch.setattr(
        storage_module,
        "_assert_supported_windows_volume",
        checked.append,
    )

    store.assert_ready()

    assert checked == [store.root]


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits are unavailable")
def test_managed_directories_and_staged_content_are_private(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.assert_ready()

    for directory in (
        store.root,
        store.root / ".ingest",
        store.root / "sha256",
        store.root / ".quarantine",
    ):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700

    staged = _stage(store, b"private")

    assert stat.S_IMODE(staged.path.stat().st_mode) == 0o600


def test_assert_ready_rejects_a_file_as_the_storage_root(tmp_path: Path) -> None:
    root = tmp_path / "objects"
    root.write_bytes(b"not a directory")
    store = LocalContentStore(root, max_upload_bytes=1024)

    with pytest.raises(StorageConfigurationError, match="not a directory"):
        store.assert_ready()


def test_assert_ready_rejects_reparse_storage_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    store.root.mkdir()
    original = storage_module._stat_is_reparse_point

    def mark_root_as_reparse(path_stat: os.stat_result) -> bool:
        if path_stat == store.root.lstat():
            return True
        return original(path_stat)

    monkeypatch.setattr(storage_module, "_stat_is_reparse_point", mark_root_as_reparse)

    with pytest.raises(StorageConfigurationError, match="reparse"):
        store.assert_ready()


def test_windows_reparse_attribute_is_rejected_without_symlink_privilege() -> None:
    fake_stat = cast(
        os.stat_result,
        SimpleNamespace(
            st_mode=stat.S_IFDIR,
            st_file_attributes=storage_module._REPARSE_POINT_ATTRIBUTE,
        ),
    )

    assert storage_module._stat_is_reparse_point(fake_stat) is True


def test_assert_ready_rejects_an_actual_symlink_root_when_supported(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    linked_root = tmp_path / "linked-root"
    try:
        linked_root.symlink_to(target, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlinks are unavailable: {error}")
    store = LocalContentStore(linked_root, max_upload_bytes=1024)

    with pytest.raises(StorageConfigurationError, match="reparse"):
        store.assert_ready()


def test_assert_ready_rejects_different_filesystems(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    original = storage_module._device_id

    def different_content_device(path: Path) -> int:
        if path.name == "sha256":
            return original(path) + 1
        return original(path)

    monkeypatch.setattr(storage_module, "_device_id", different_content_device)

    with pytest.raises(StorageConfigurationError, match="same filesystem"):
        store.assert_ready()


def test_temporary_key_is_canonical(tmp_path: Path) -> None:
    store = _store(tmp_path)
    token = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")

    assert store.temporary_key(token) == (
        ".ingest/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa.part"
    )


def test_write_stream_is_chunked_hashed_and_fsynced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    store.assert_ready()
    content = b"abcdefgh" * (storage_module.STREAM_CHUNK_BYTES // 4)
    reader = _RecordingReader(content)
    fsynced: list[int] = []
    synced_directories: list[Path] = []
    real_fsync = os.fsync

    def record_fsync(file_descriptor: int) -> None:
        fsynced.append(file_descriptor)
        real_fsync(file_descriptor)

    monkeypatch.setattr(os, "fsync", record_fsync)
    monkeypatch.setattr(
        storage_module,
        "_fsync_directory",
        synced_directories.append,
    )

    staged = store.write_stream(uuid4(), reader)

    assert staged.path.read_bytes() == content
    assert staged.size_bytes == len(content)
    assert staged.sha256_hex == hashlib.sha256(content).hexdigest()
    assert staged.lease_token == staged.token
    assert staged.temporary_key == staged.temp_key
    assert len(reader.request_sizes) >= 3
    assert all(
        size == storage_module.STREAM_CHUNK_BYTES for size in reader.request_sizes
    )
    assert len(fsynced) == 1
    assert synced_directories == [store.root / ".ingest"]


def test_write_stream_enforces_limit_and_removes_partial_file(tmp_path: Path) -> None:
    store = _store(tmp_path, limit=5)
    token = uuid4()

    with pytest.raises(UploadTooLargeError, match="5"):
        store.write_stream(token, BytesIO(b"123456"))

    assert not (store.root / store.temporary_key(token)).exists()


def test_write_stream_translates_fsync_busy_and_removes_partial_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    token = uuid4()
    store.assert_ready()

    def busy_fsync(_file_descriptor: int) -> None:
        raise OSError(errno.EBUSY, "busy")

    monkeypatch.setattr(os, "fsync", busy_fsync)

    with pytest.raises(StorageBusyError):
        store.write_stream(token, BytesIO(b"partial"))

    assert not (store.root / store.temporary_key(token)).exists()


def test_write_stream_removes_partial_when_ingest_directory_sync_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    token = uuid4()

    def fail_directory_sync(_path: Path) -> None:
        raise StorageOperationError("directory sync failed")

    monkeypatch.setattr(storage_module, "_fsync_directory", fail_directory_sync)

    with pytest.raises(StorageOperationError, match="directory sync failed"):
        store.write_stream(token, BytesIO(b"fully written but not durable"))

    assert not (store.root / store.temporary_key(token)).exists()


def test_write_stream_accepts_exact_limit(tmp_path: Path) -> None:
    store = _store(tmp_path, limit=5)

    staged = store.write_stream(uuid4(), BytesIO(b"12345"))

    assert staged.size_bytes == 5


def test_write_stream_rejects_a_text_eof_and_removes_partial_file(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    token = uuid4()

    with pytest.raises(TypeError, match="bytes"):
        store.write_stream(token, _TextEofReader())  # type: ignore[arg-type]

    assert not (store.root / store.temporary_key(token)).exists()


def test_write_stream_never_overwrites_an_existing_temporary_file(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    token = uuid4()
    first = store.write_stream(token, BytesIO(b"first"))

    with pytest.raises(TemporaryContentExistsError):
        store.write_stream(token, BytesIO(b"second"))

    assert first.path.read_bytes() == b"first"


def test_promote_publishes_without_overwrite_and_removes_temporary_file(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    staged = _stage(store, b"immutable content")

    stored = store.promote(staged)

    expected_digest = hashlib.sha256(b"immutable content").hexdigest()
    assert stored.storage_key == f"sha256/{expected_digest[:2]}/{expected_digest}"
    assert stored.sha256_hex == staged.sha256_hex
    assert stored.size_bytes == len(b"immutable content")
    assert stored.reused is False
    assert not staged.path.exists()
    assert (store.root / stored.storage_key).read_bytes() == b"immutable content"


def test_promote_reuses_only_after_hash_and_byte_comparison(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    first = store.promote(_stage(store, b"same bytes"))
    second_stage = _stage(store, b"same bytes")
    comparisons: list[tuple[Path, Path]] = []
    real_files_equal = storage_module._files_equal

    def record_comparison(left: Path, right: Path) -> bool:
        comparisons.append((left, right))
        return real_files_equal(left, right)

    monkeypatch.setattr(storage_module, "_files_equal", record_comparison)

    second = store.promote(second_stage)

    assert first.reused is False
    assert second.reused is True
    assert second.storage_key == first.storage_key
    assert comparisons == [(second_stage.path, store.root / first.storage_key)]
    assert not second_stage.path.exists()


def test_promote_retry_resynchronises_an_existing_published_link(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    staged = _stage(store, b"retry durable publication")
    storage_key = f"sha256/{staged.sha256_hex[:2]}/{staged.sha256_hex}"
    final_path = store.root / storage_key
    real_directory_sync = storage_module._fsync_directory
    fail_publication_sync_once = True
    synced: list[Path] = []

    def fail_first_publication_sync(path: Path) -> None:
        nonlocal fail_publication_sync_once
        synced.append(path)
        if (
            path == final_path.parent
            and final_path.exists()
            and fail_publication_sync_once
        ):
            fail_publication_sync_once = False
            raise StorageOperationError("injected publication sync failure")
        real_directory_sync(path)

    monkeypatch.setattr(
        storage_module,
        "_fsync_directory",
        fail_first_publication_sync,
    )

    with pytest.raises(StorageOperationError, match="publication sync failure"):
        store.promote(staged)

    assert staged.path.is_file()
    assert final_path.is_file()
    synced.clear()

    retried = store.promote(staged)

    assert retried.storage_key == storage_key
    assert retried.reused is True
    assert final_path.parent in synced
    assert not staged.path.exists()


def test_promote_syncs_a_concurrently_created_link_before_reuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    staged = _stage(store, b"concurrent durable publication")
    storage_key = f"sha256/{staged.sha256_hex[:2]}/{staged.sha256_hex}"
    final_path = store.root / storage_key
    real_link = os.link
    real_directory_sync = storage_module._fsync_directory
    real_unlink_staged = LocalContentStore._unlink_staged
    events: list[tuple[str, Path]] = []

    def publish_concurrently_then_report_exists(
        source: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        target: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> None:
        real_link(
            source,
            target,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
            follow_symlinks=follow_symlinks,
        )
        events.append(("link", Path(os.fsdecode(target))))
        raise FileExistsError(errno.EEXIST, "concurrent publication")

    def record_directory_sync(path: Path) -> None:
        events.append(("sync", path))
        real_directory_sync(path)

    def record_staged_unlink(self: LocalContentStore, path: Path) -> None:
        events.append(("unlink", path))
        real_unlink_staged(self, path)

    monkeypatch.setattr(os, "link", publish_concurrently_then_report_exists)
    monkeypatch.setattr(storage_module, "_fsync_directory", record_directory_sync)
    monkeypatch.setattr(LocalContentStore, "_unlink_staged", record_staged_unlink)

    stored = store.promote(staged)

    link_index = events.index(("link", final_path))
    reuse_sync_index = events.index(("sync", final_path.parent), link_index)
    unlink_index = events.index(("unlink", staged.path))
    assert link_index < reuse_sync_index < unlink_index
    assert stored.reused is True
    assert not staged.path.exists()


def test_promote_rejects_a_corrupt_existing_object(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = store.promote(_stage(store, b"expected"))
    target = store.root / first.storage_key
    target.write_bytes(b"corrupt!")
    staged = _stage(store, b"expected")

    with pytest.raises(ContentIntegrityError, match="existing"):
        store.promote(staged)

    assert staged.path.exists()
    assert target.read_bytes() == b"corrupt!"


def test_promote_rejects_tampered_staged_content(tmp_path: Path) -> None:
    store = _store(tmp_path)
    staged = _stage(store, b"original")
    staged.path.write_bytes(b"tampered")

    with pytest.raises(ContentIntegrityError, match="staged content"):
        store.promote(staged)

    assert staged.path.read_bytes() == b"tampered"


def test_promote_revalidates_the_inode_that_was_actually_linked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    staged = _stage(store, b"expected")
    expected_key = f"sha256/{staged.sha256_hex[:2]}/{staged.sha256_hex}"
    real_link = os.link

    def replace_source_before_link(
        source: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        target: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> None:
        source_path = Path(os.fsdecode(source))
        source_path.unlink()
        source_path.write_bytes(b"MALICIOUS")
        real_link(
            source,
            target,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
            follow_symlinks=follow_symlinks,
        )

    monkeypatch.setattr(os, "link", replace_source_before_link)

    with pytest.raises(ContentIntegrityError, match="published"):
        store.promote(staged)

    assert not (store.root / expected_key).exists()
    assert staged.path.read_bytes() == b"MALICIOUS"


@pytest.mark.parametrize(
    ("error", "expected_exception"),
    [
        (OSError(errno.EXDEV, "cross-device link"), CrossDeviceStorageError),
        (OSError(errno.EBUSY, "resource busy"), StorageBusyError),
        (OSError(errno.EIO, "I/O failure"), StorageOperationError),
    ],
)
def test_promote_translates_link_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: OSError,
    expected_exception: type[Exception],
) -> None:
    store = _store(tmp_path)
    staged = _stage(store, b"content")

    def fail_link(
        _source: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        _target: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> None:
        del src_dir_fd, dst_dir_fd, follow_symlinks
        raise error

    monkeypatch.setattr(os, "link", fail_link)

    with pytest.raises(expected_exception):
        store.promote(staged)

    assert staged.path.exists()


@pytest.mark.parametrize(
    "key",
    [
        "",
        "sha256/aa/not-a-digest",
        f"sha256/AA/{'a' * 64}",
        f"sha256/aa/{'A' * 64}",
        f"sha256/ab/{'a' * 64}",
        f"sha256/aa/{'a' * 63}",
        f"sha256/aa/{'a' * 65}",
        f"sha256\\aa\\{'a' * 64}",
        f"../sha256/aa/{'a' * 64}",
        f"sha256/aa/{'a' * 64}/extra",
    ],
)
def test_validate_rejects_noncanonical_storage_keys(tmp_path: Path, key: str) -> None:
    store = _store(tmp_path)

    with pytest.raises(InvalidStorageKeyError):
        store.validate(key, "a" * 64, 0)


def test_validate_rehashes_object_and_reports_corruption(tmp_path: Path) -> None:
    store = _store(tmp_path)
    stored = store.promote(_stage(store, b"trusted"))

    assert store.validate(stored.storage_key, stored.sha256_hex, 7) is True

    (store.root / stored.storage_key).write_bytes(b"changed")
    with pytest.raises(ContentHashMismatchError, match="digest"):
        store.validate(stored.storage_key, stored.sha256_hex, 7)


def test_read_bytes_returns_only_content_matching_its_immutable_identity(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    stored = store.promote(_stage(store, b"report-content"))

    assert (
        store.read_bytes(
            stored.storage_key,
            stored.sha256_hex,
            stored.size_bytes,
        )
        == b"report-content"
    )

    (store.root / stored.storage_key).write_bytes(b"tampered-bytes")
    with pytest.raises(ContentHashMismatchError, match="digest"):
        store.read_bytes(
            stored.storage_key,
            stored.sha256_hex,
            stored.size_bytes,
        )


def test_read_bytes_rejects_an_object_above_the_configured_memory_bound(
    tmp_path: Path,
) -> None:
    writer = _store(tmp_path, limit=1024)
    stored = writer.promote(_stage(writer, b"123456"))
    bounded_reader = LocalContentStore(writer.root, max_upload_bytes=5)

    with pytest.raises(UploadTooLargeError, match="read limit"):
        bounded_reader.read_bytes(
            stored.storage_key,
            stored.sha256_hex,
            stored.size_bytes,
        )


def test_validate_distinguishes_size_mismatch(tmp_path: Path) -> None:
    store = _store(tmp_path)
    stored = store.promote(_stage(store, b"trusted"))

    with pytest.raises(ContentSizeMismatchError, match="size"):
        store.validate(stored.storage_key, stored.sha256_hex, 8)


def test_validate_reports_a_missing_canonical_object(tmp_path: Path) -> None:
    store = _store(tmp_path)
    digest = "a" * 64

    with pytest.raises(ContentNotFoundError, match="missing"):
        store.validate(f"sha256/aa/{digest}", digest, 0)


def test_validate_rejects_key_digest_disagreement(tmp_path: Path) -> None:
    store = _store(tmp_path)

    with pytest.raises(ContentIntegrityError, match="storage key digest"):
        store.validate(f"sha256/aa/{'a' * 64}", "b" * 64, 0)


def test_validate_rejects_negative_expected_size(tmp_path: Path) -> None:
    store = _store(tmp_path)
    digest = "a" * 64

    with pytest.raises(StorageConfigurationError, match="non-negative"):
        store.validate(f"sha256/aa/{digest}", digest, -1)


def test_iter_objects_only_returns_canonical_regular_objects(tmp_path: Path) -> None:
    store = _store(tmp_path)
    stored = store.promote(_stage(store, b"listed"))
    (store.root / "sha256" / "not-a-prefix").mkdir()
    (store.root / "sha256" / "not-a-prefix" / "junk").write_bytes(b"junk")
    (store.root / "sha256" / "aa").mkdir(exist_ok=True)
    (store.root / "sha256" / "aa" / ("b" * 64)).write_bytes(b"wrong prefix")
    (store.root / "sha256" / "aa" / "short").write_bytes(b"junk")

    objects = list(store.iter_objects())

    assert [item.storage_key for item in objects] == [stored.storage_key]
    assert objects[0].path == store.root / stored.storage_key
    assert objects[0].size_bytes == len(b"listed")
    assert objects[0].modified_at.tzinfo is UTC


def test_quarantine_uses_non_overwriting_link_and_unlink(tmp_path: Path) -> None:
    store = _store(tmp_path)
    stored = store.promote(_stage(store, b"orphan"))
    source = store.root / stored.storage_key
    scan_id = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

    quarantined = store.quarantine(stored.storage_key, scan_id)

    assert quarantined is not None
    assert quarantined.storage_key == stored.storage_key
    assert quarantined.quarantine_key == (
        f"bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb/{stored.storage_key}"
    )
    assert quarantined.path.read_bytes() == b"orphan"
    assert not source.exists()
    assert store.quarantine(stored.storage_key, scan_id) is None


def test_quarantine_keeps_source_when_destination_directory_sync_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    stored = store.promote(_stage(store, b"orphan"))
    source = store.root / stored.storage_key
    scan_id = UUID("abababab-abab-abab-abab-abababababab")
    destination = store.root / ".quarantine" / str(scan_id) / stored.storage_key
    destination.parent.mkdir(parents=True)
    real_directory_sync = storage_module._fsync_directory

    def fail_destination_sync(path: Path) -> None:
        if path == destination.parent and destination.exists():
            raise StorageOperationError("directory sync failed")
        real_directory_sync(path)

    monkeypatch.setattr(storage_module, "_fsync_directory", fail_destination_sync)

    with pytest.raises(StorageOperationError, match="directory sync failed"):
        store.quarantine(stored.storage_key, scan_id)

    assert source.read_bytes() == b"orphan"
    assert destination.read_bytes() == b"orphan"


def test_quarantine_retry_resynchronises_a_missing_source_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    stored = store.promote(_stage(store, b"orphan removal retry"))
    source = store.root / stored.storage_key
    scan_id = UUID("acacacac-acac-acac-acac-acacacacacac")
    destination = store.root / ".quarantine" / str(scan_id) / stored.storage_key
    real_directory_sync = storage_module._fsync_directory
    fail_source_sync_once = True
    synced: list[Path] = []

    def fail_first_source_sync(path: Path) -> None:
        nonlocal fail_source_sync_once
        synced.append(path)
        if path == source.parent and not source.exists() and fail_source_sync_once:
            fail_source_sync_once = False
            raise StorageOperationError("injected source removal sync failure")
        real_directory_sync(path)

    monkeypatch.setattr(storage_module, "_fsync_directory", fail_first_source_sync)

    with pytest.raises(StorageOperationError, match="source removal sync failure"):
        store.quarantine(stored.storage_key, scan_id)

    assert not source.exists()
    assert destination.is_file()
    synced.clear()

    assert store.quarantine(stored.storage_key, scan_id) is None
    assert synced == [source.parent]


def test_quarantine_treats_source_loss_during_link_as_concurrent_loss(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    stored = store.promote(_stage(store, b"orphan"))
    source = store.root / stored.storage_key

    def lose_source(
        source_path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        _target: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> None:
        del source_path, src_dir_fd, dst_dir_fd, follow_symlinks
        source.unlink()
        raise FileNotFoundError(errno.ENOENT, "source disappeared")

    monkeypatch.setattr(os, "link", lose_source)

    assert store.quarantine(stored.storage_key, uuid4()) is None


def test_quarantine_treats_source_loss_during_reuse_as_concurrent_loss(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    stored = store.promote(_stage(store, b"orphan reuse race"))
    source = store.root / stored.storage_key
    scan_id = UUID("adadadad-adad-adad-adad-adadadadadad")
    destination = store.root / ".quarantine" / str(scan_id) / stored.storage_key
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"orphan reuse race")
    real_files_equal = storage_module._files_equal

    def lose_source_before_comparison(left: Path, right: Path) -> bool:
        source.unlink()
        return real_files_equal(left, right)

    monkeypatch.setattr(storage_module, "_files_equal", lose_source_before_comparison)

    assert store.quarantine(stored.storage_key, scan_id) is None
    assert destination.read_bytes() == b"orphan reuse race"


def test_quarantine_never_overwrites_a_conflicting_destination(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    stored = store.promote(_stage(store, b"orphan"))
    scan_id = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
    destination = store.root / ".quarantine" / str(scan_id) / stored.storage_key
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"different")

    with pytest.raises(ContentIntegrityError, match="different bytes"):
        store.quarantine(stored.storage_key, scan_id)

    assert destination.read_bytes() == b"different"
    assert (store.root / stored.storage_key).read_bytes() == b"orphan"


def test_quarantine_reuses_an_identical_destination_without_overwriting(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    stored = store.promote(_stage(store, b"orphan"))
    scan_id = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
    destination = store.root / ".quarantine" / str(scan_id) / stored.storage_key
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"orphan")

    quarantined = store.quarantine(stored.storage_key, scan_id)

    assert quarantined is not None
    assert quarantined.path == destination
    assert destination.read_bytes() == b"orphan"
    assert not (store.root / stored.storage_key).exists()


def test_quarantine_requires_a_uuid_scan_id(tmp_path: Path) -> None:
    store = _store(tmp_path)
    stored = store.promote(_stage(store, b"orphan"))

    with pytest.raises(TypeError, match="scan_id"):
        store.quarantine(stored.storage_key, "not-a-uuid")  # type: ignore[arg-type]


def test_discard_staged_is_scoped_to_matching_ingest_token(tmp_path: Path) -> None:
    store = _store(tmp_path)
    staged = _stage(store, b"temporary")
    outside = tmp_path / "outside.part"
    outside.write_bytes(b"must remain")
    forged = StagedContent(
        lease_token=staged.lease_token,
        temporary_key=staged.temporary_key,
        path=outside,
        sha256_hex=staged.sha256_hex,
        size_bytes=staged.size_bytes,
    )

    with pytest.raises(StorageConfigurationError, match="staged path"):
        store.discard_staged(forged)

    assert outside.read_bytes() == b"must remain"
    store.discard_staged(staged)
    store.discard_staged(staged)
    assert not staged.path.exists()


def test_discard_retry_resynchronises_an_already_missing_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    staged = _stage(store, b"discard retry")
    real_directory_sync = storage_module._fsync_directory
    fail_removal_sync_once = True
    synced: list[Path] = []

    def fail_first_removal_sync(path: Path) -> None:
        nonlocal fail_removal_sync_once
        synced.append(path)
        if (
            path == staged.path.parent
            and not staged.path.exists()
            and fail_removal_sync_once
        ):
            fail_removal_sync_once = False
            raise StorageOperationError("injected discard sync failure")
        real_directory_sync(path)

    monkeypatch.setattr(storage_module, "_fsync_directory", fail_first_removal_sync)

    with pytest.raises(StorageOperationError, match="discard sync failure"):
        store.discard_staged(staged)

    assert not staged.path.exists()
    synced.clear()

    store.discard_staged(staged)
    assert synced == [staged.path.parent]


def test_discard_staged_refuses_a_replaced_directory(tmp_path: Path) -> None:
    store = _store(tmp_path)
    staged = _stage(store, b"temporary")
    staged.path.unlink()
    staged.path.mkdir()

    with pytest.raises(StorageConfigurationError, match="safe regular file"):
        store.discard_staged(staged)

    assert staged.path.is_dir()


def test_write_stream_accepts_binary_io_protocol(tmp_path: Path) -> None:
    store = _store(tmp_path)
    source: BinaryIO = BytesIO(b"binary")

    assert store.write_stream(uuid4(), source).size_bytes == 6


def test_iter_temporary_objects_only_returns_canonical_regular_files(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    staged = _stage(store, b"abandoned upload")
    ingest_root = store.root / ".ingest"
    (ingest_root / "not-a-lease.part").write_bytes(b"ignored")
    (ingest_root / f"{uuid4()}.tmp").write_bytes(b"ignored")
    (ingest_root / str(uuid4())).mkdir()

    objects = list(store.iter_temporary_objects())

    assert len(objects) == 1
    assert objects[0].lease_token == staged.lease_token
    assert objects[0].temporary_key == staged.temporary_key
    assert objects[0].path == staged.path
    assert objects[0].size_bytes == staged.size_bytes


def test_quarantine_temporary_object_is_non_overwriting_and_idempotent(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    staged = _stage(store, b"abandoned upload")
    temporary = next(iter(store.iter_temporary_objects()))
    assert isinstance(temporary, TemporaryObject)
    scan_id = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")

    quarantined = store.quarantine_temporary(temporary, scan_id)
    repeated = store.quarantine_temporary(temporary, scan_id)

    assert quarantined is not None
    assert quarantined.temporary_key == staged.temporary_key
    assert quarantined.quarantine_key == f"{scan_id}/{staged.temporary_key}"
    assert quarantined.path.read_bytes() == b"abandoned upload"
    assert repeated is None
    assert not staged.path.exists()


def test_temporary_quarantine_keeps_source_when_destination_sync_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    staged = _stage(store, b"abandoned upload")
    temporary = next(iter(store.iter_temporary_objects()))
    scan_id = UUID("fafafafa-fafa-fafa-fafa-fafafafafafa")
    destination = store.root / ".quarantine" / str(scan_id) / staged.temporary_key
    destination.parent.mkdir(parents=True)
    real_directory_sync = storage_module._fsync_directory

    def fail_destination_sync(path: Path) -> None:
        if path == destination.parent and destination.exists():
            raise StorageOperationError("directory sync failed")
        real_directory_sync(path)

    monkeypatch.setattr(storage_module, "_fsync_directory", fail_destination_sync)

    with pytest.raises(StorageOperationError, match="directory sync failed"):
        store.quarantine_temporary(temporary, scan_id)

    assert staged.path.read_bytes() == b"abandoned upload"
    assert destination.read_bytes() == b"abandoned upload"


def test_temporary_quarantine_treats_source_loss_during_link_as_concurrent_loss(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    staged = _stage(store, b"temporary race")
    temporary = next(iter(store.iter_temporary_objects()))

    def lose_source(
        source_path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        _target: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> None:
        del source_path, src_dir_fd, dst_dir_fd, follow_symlinks
        staged.path.unlink()
        raise FileNotFoundError(errno.ENOENT, "source disappeared")

    monkeypatch.setattr(os, "link", lose_source)

    assert store.quarantine_temporary(temporary, uuid4()) is None


def test_temporary_quarantine_treats_source_loss_during_reuse_as_concurrent_loss(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    staged = _stage(store, b"temporary reuse race")
    temporary = next(iter(store.iter_temporary_objects()))
    scan_id = UUID("fcfcfcfc-fcfc-fcfc-fcfc-fcfcfcfcfcfc")
    destination = store.root / ".quarantine" / str(scan_id) / staged.temporary_key
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"temporary reuse race")
    real_files_equal = storage_module._files_equal

    def lose_source_before_comparison(left: Path, right: Path) -> bool:
        staged.path.unlink()
        return real_files_equal(left, right)

    monkeypatch.setattr(storage_module, "_files_equal", lose_source_before_comparison)

    assert store.quarantine_temporary(temporary, scan_id) is None
    assert destination.read_bytes() == b"temporary reuse race"


def test_temporary_quarantine_retry_resynchronises_a_missing_source_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    staged = _stage(store, b"temporary removal retry")
    temporary = next(iter(store.iter_temporary_objects()))
    scan_id = UUID("fbfbfbfb-fbfb-fbfb-fbfb-fbfbfbfbfbfb")
    destination = store.root / ".quarantine" / str(scan_id) / staged.temporary_key
    real_directory_sync = storage_module._fsync_directory
    fail_source_sync_once = True
    synced: list[Path] = []

    def fail_first_source_sync(path: Path) -> None:
        nonlocal fail_source_sync_once
        synced.append(path)
        if (
            path == staged.path.parent
            and not staged.path.exists()
            and fail_source_sync_once
        ):
            fail_source_sync_once = False
            raise StorageOperationError("injected temporary removal sync failure")
        real_directory_sync(path)

    monkeypatch.setattr(storage_module, "_fsync_directory", fail_first_source_sync)

    with pytest.raises(StorageOperationError, match="temporary removal sync failure"):
        store.quarantine_temporary(temporary, scan_id)

    assert not staged.path.exists()
    assert destination.is_file()
    synced.clear()

    assert store.quarantine_temporary(temporary, scan_id) is None
    assert synced == [staged.path.parent]
