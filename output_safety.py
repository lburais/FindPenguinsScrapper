"""Guards for explicitly requested generated-output cleanup."""

from pathlib import Path


def validate_clear_directory(directory):
    """! @brief Refuse to clear a symlink, filesystem root, cwd, this project or the home directory.
    @param directory Directory about to be deleted.
    @return None
    @throws ValueError When the directory is unsafe to clear.
    """
    path = Path(directory)
    if path.is_symlink():
        raise ValueError(f"Refusing to clear symbolic link {directory}")
    resolved = path.resolve()
    protected = (Path.cwd().resolve(), Path(__file__).resolve().parent, Path.home().resolve())
    if resolved == Path(resolved.anchor) or any(
        resolved == item or resolved in item.parents for item in protected
    ):
        raise ValueError(f"Refusing to clear {directory}")


def validate_component(value):
    """! @brief Ensure `value` is a single safe path component (no separators, `.` or `..`).
    @param value Candidate folder name, e.g. a trip slug.
    @return None
    @throws ValueError When the value is empty or could traverse directories.
    """
    if not value or value in (".", "..") or Path(value).name != value or "/" in value or "\\" in value:
        raise ValueError(f"Invalid path component: {value!r}")
