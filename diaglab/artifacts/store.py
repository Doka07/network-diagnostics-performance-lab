"""Small POSIX artifact store: no-follow files, bounded reads and durable writes."""

import hashlib
import os
import stat
from pathlib import Path
from uuid import uuid4

from diaglab.artifacts.checksums import open_directory, safe_artifact_path
from diaglab.exceptions import ArtifactIntegrityError, MissingInputError, SafetyPreflightError
from diaglab.serialization import canonical_json


class ArtifactStore:
    def __init__(self, root: str | Path, *, create: bool = False) -> None:
        self.root = Path(root).absolute()
        self.directory = -1
        self.lock_owned = False
        try:
            self.directory = open_directory(self.root, create=create)
            if create:
                lock = os.open(
                    ".run.lock",
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=self.directory,
                )
                self.lock_owned = True
                os.close(lock)
                if os.listdir(self.directory) != [".run.lock"]:
                    raise SafetyPreflightError("run destination must be absent or empty")
        except FileNotFoundError as exc:
            self.close()
            raise MissingInputError(f"run directory not found: {self.root}") from exc
        except FileExistsError as exc:
            self.close()
            raise SafetyPreflightError("run destination is owned by another invocation") from exc
        except OSError as exc:
            self.close()
            raise ArtifactIntegrityError(f"cannot open artifact directory: {exc}") from exc
        except BaseException:
            self.close()
            raise

    def __enter__(self) -> "ArtifactStore":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        if self.directory >= 0:
            try:
                if self.lock_owned:
                    os.unlink(".run.lock", dir_fd=self.directory)
                    os.fsync(self.directory)
                    self.lock_owned = False
            finally:
                os.close(self.directory)
                self.directory = -1

    def _name(self, name: str) -> str:
        # Phase 2 artifacts are a closed, flat directory; reject nested names.
        if not name or "/" in name or "\\" in name or name in {".", ".."} or ":" in name:
            raise ArtifactIntegrityError("expected a flat normalized artifact name")
        safe_artifact_path(self.root, name)
        self._assert_identity()
        return name

    def _assert_identity(self) -> None:
        """Refuse a renamed/replaced root instead of delegating into a different tree."""
        check = -1
        try:
            check = open_directory(self.root)
            current, owned = os.fstat(check), os.fstat(self.directory)
            if (current.st_dev, current.st_ino) != (owned.st_dev, owned.st_ino):
                raise ArtifactIntegrityError("artifact root identity changed")
        except OSError as exc:
            raise ArtifactIntegrityError("artifact root is no longer securely reachable") from exc
        finally:
            if check >= 0:
                os.close(check)

    def open_new(self, name: str):
        name = self._name(name)
        try:
            fd = os.open(
                name,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                0o600,
                dir_fd=self.directory,
            )
            return os.fdopen(fd, "wb")
        except OSError as exc:
            raise ArtifactIntegrityError(f"cannot create artifact {name}: {exc}") from exc

    def write(self, name: str, data: bytes) -> None:
        with self.open_new(name) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.fsync(self.directory)

    def write_json(self, name: str, record: object) -> None:
        self.write(name, canonical_json(record) + b"\n")

    def replace_json(self, name: str, record: object) -> None:
        name = self._name(name)
        if name != "manifest.json":
            raise ArtifactIntegrityError("only the manifest may be atomically updated")
        temporary = ".manifest-" + uuid4().hex
        data = canonical_json(record) + b"\n"
        try:
            with self.open_new(temporary) as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, name, src_dir_fd=self.directory, dst_dir_fd=self.directory)
            os.fsync(self.directory)
        except OSError as exc:
            raise ArtifactIntegrityError(f"cannot finalize manifest: {exc}") from exc

    def read(self, name: str, *, limit: int = 16 * 1024 * 1024) -> bytes:
        name = self._name(name)
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.directory)
        except FileNotFoundError as exc:
            raise MissingInputError(f"artifact missing: {name}") from exc
        except OSError as exc:
            raise ArtifactIntegrityError(f"cannot read artifact {name}: {exc}") from exc
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
                raise ArtifactIntegrityError(f"artifact {name} is nonregular or exceeds size bound")
            parts = []
            size = 0
            while chunk := os.read(fd, min(65536, limit + 1 - size)):
                size += len(chunk)
                if size > limit:
                    raise ArtifactIntegrityError(f"artifact {name} exceeds size bound")
                parts.append(chunk)
            after = os.fstat(fd)
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ):
                raise ArtifactIntegrityError(f"artifact {name} changed during read")
            return b"".join(parts)
        finally:
            os.close(fd)

    def digest(self, name: str, *, limit: int = 16 * 1024 * 1024) -> dict:
        data = self.read(name, limit=limit)
        return {"path": name, "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}

    def names(self) -> set[str]:
        self._assert_identity()
        return set(os.listdir(self.directory))
