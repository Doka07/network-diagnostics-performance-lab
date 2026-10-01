"""File checksums with artifact-root containment and symlink rejection."""

import hashlib
import os
import stat
from pathlib import Path, PurePosixPath, PureWindowsPath

from diaglab.exceptions import ArtifactIntegrityError


def open_directory(path: str | Path, *, create: bool = False) -> int:
    """Walk directories with no-follow opens, retaining ownership of the returned FD."""
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise ArtifactIntegrityError("secure artifact operations currently require POSIX")
    absolute = Path(os.path.abspath(path))
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY
    directory = os.open(absolute.anchor, flags)
    try:
        for part in absolute.parts[1:]:
            if create:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=directory)
                except FileExistsError:
                    pass
            next_directory = os.open(part, flags, dir_fd=directory)
            os.close(directory)
            directory = next_directory
        return directory
    except BaseException:
        os.close(directory)
        raise


def safe_artifact_path(root: str | Path, relative_path: str) -> Path:
    posix = PurePosixPath(relative_path)
    windows = PureWindowsPath(relative_path)
    if (
        not relative_path
        or posix.is_absolute()
        or windows.drive
        or windows.is_absolute()
        or "\\" in relative_path
        or ".." in posix.parts
        or posix.as_posix() != relative_path
        or relative_path == "."
    ):
        raise ArtifactIntegrityError("artifact path must be normalized and relative to its root")
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ArtifactIntegrityError("artifact root must be an existing nonsymlink directory")
    resolved_root = root.resolve(strict=True)
    candidate = resolved_root.joinpath(*posix.parts)
    current = resolved_root
    for part in posix.parts:
        current = current / part
        if current.is_symlink():
            raise ArtifactIntegrityError("symlinks are unsupported in artifact paths")
    if not candidate.resolve(strict=False).is_relative_to(resolved_root):
        raise ArtifactIntegrityError("artifact path escapes its root")
    return candidate


def artifact_digest(root: str | Path, relative_path: str) -> dict[str, str | int]:
    """Use directory-relative no-follow opens, not only a pre-open path check."""
    safe_artifact_path(root, relative_path)
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise ArtifactIntegrityError(
            "secure artifact hashing currently requires POSIX no-follow opens"
        )
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY
    directory = open_directory(root)
    try:
        parts = PurePosixPath(relative_path).parts
        for part in parts[:-1]:
            next_directory = os.open(part, flags, dir_fd=directory)
            os.close(directory)
            directory = next_directory
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode):
                raise ArtifactIntegrityError("only regular artifact files can be hashed")
            digest = hashlib.sha256()
            while data := os.read(fd, 1_048_576):
                digest.update(data)
            after = os.fstat(fd)
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ):
                raise ArtifactIntegrityError("artifact changed while hashing")
            return {
                "path": relative_path,
                "size_bytes": after.st_size,
                "sha256": digest.hexdigest(),
            }
        finally:
            os.close(fd)
    except OSError as exc:
        raise ArtifactIntegrityError(f"cannot securely hash artifact: {exc}") from exc
    finally:
        os.close(directory)
