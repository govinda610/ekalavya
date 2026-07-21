"""The agent's filesystem: read broadly, write only inside a persistent workspace.

Reuses deepagents' CompositeBackend + FilesystemBackend (no custom sandbox):
  - writes/edits route to `/workspace/`, a real dir under the eklavya home, with
    virtual_mode=True so the agent cannot escape it (no `..`, `~`, or absolute paths
    outside the root);
  - everything else routes to a read-only host backend (writes/edits denied) that also
    refuses to read forbidden paths (ssh / aws / gnupg / .env / keychains / our own home).

This confines write/edit on every OS with zero dependencies. Bash is gated separately
(approval + explanation + denylist — see #42), since a backend can't confine a shell.
"""

from __future__ import annotations

from pathlib import Path

from . import config

# Secrets under the home dir that are never readable (the host backend is otherwise
# read-broad). The eklavya home itself is handled specially in _is_forbidden.
_FORBIDDEN = (".ssh", ".aws", ".gnupg", ".netrc", ".config/gcloud",
              "Library/Keychains", "Library/Application Support")

_DENY_MSG = "(access to this path is not allowed)"


def workspace_dir() -> Path:
    config.WORKSPACE.mkdir(parents=True, exist_ok=True)
    return config.WORKSPACE


def _is_forbidden(file_path: str) -> bool:
    try:
        resolved = str(Path(file_path).expanduser().resolve())
    except Exception:
        return True
    if resolved.startswith(str(config.WORKSPACE.resolve())):
        return False  # the agent's own workspace (db + profile) — always allowed
    if Path(resolved).name == ".env":
        return True
    if resolved.startswith(str(config.EKLAVYA_HOME.resolve())):
        return True  # backups, checkpointer, other app internals — off limits
    home = Path.home()
    return any(resolved.startswith(str(home / f)) for f in _FORBIDDEN)


def build_backend():
    """The CompositeBackend the agent runs on: read-broad host + writable /workspace."""
    from deepagents.backends import CompositeBackend, FilesystemBackend
    from deepagents.backends.protocol import EditResult, WriteResult

    class ReadOnlyHost(FilesystemBackend):
        """Read the host broadly, but deny all writes/edits and forbidden reads."""

        def write(self, file_path, content):
            return WriteResult(error="Read-only path. Write only under /workspace/.")

        def edit(self, file_path, old_string, new_string, replace_all=False):
            return EditResult(error="Read-only path. Edit only under /workspace/.")

        def read(self, file_path, *args, **kwargs):
            if _is_forbidden(file_path):
                return _DENY_MSG
            return super().read(file_path, *args, **kwargs)

        async def awrite(self, file_path, content):
            return WriteResult(error="Read-only path. Write only under /workspace/.")

        async def aedit(self, file_path, old_string, new_string, replace_all=False):
            return EditResult(error="Read-only path. Edit only under /workspace/.")

        async def aread(self, file_path, *args, **kwargs):
            if _is_forbidden(file_path):
                return _DENY_MSG
            return await super().aread(file_path, *args, **kwargs)

    return CompositeBackend(
        default=ReadOnlyHost(root_dir=str(Path.home()), virtual_mode=False),
        routes={"/workspace/": FilesystemBackend(root_dir=str(workspace_dir()), virtual_mode=True)},
    )
