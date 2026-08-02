"""is_safe_bash must be target-aware, not verb-only.

The old check auto-approved any whitelisted verb regardless of its target, so
`cat /etc/passwd` and `cat ~/.eklavya-data/users.db` ran silently (an exfil vector).
Now a command auto-runs ONLY when its verb is whitelisted AND every path argument
resolves inside the tenant workspace; file-read verbs (cat/head/tail/grep/nl/cut) are
off the whitelist entirely, so any file read needs explicit approval.
"""

import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="eklavya-bash-")
os.environ["EKLAVYA_HOME"] = _TMP

from eklavya import agent as ag  # noqa: E402
from eklavya.workspace import workspace_dir  # noqa: E402


def test_file_read_and_escapes_are_not_auto_approved():
    workspace_dir()  # ensure the workspace exists so path resolution is stable
    # File-content reads are the exfil vector — never auto-approved now.
    assert ag.is_safe_bash("cat /etc/passwd") is False
    assert ag.is_safe_bash("cat ~/.eklavya-data/users.db") is False
    assert ag.is_safe_bash("grep -r x /") is False
    assert ag.is_safe_bash("cat ../../x") is False
    # Absolute / escaping targets on a still-whitelisted verb are refused too.
    assert ag.is_safe_bash("ls /") is False
    assert ag.is_safe_bash("stat ../../etc/passwd") is False
    assert ag.is_safe_bash("du ~/.eklavya-data") is False


def test_workspace_local_read_only_commands_still_auto_approve():
    workspace_dir()
    assert ag.is_safe_bash("pwd") is True
    assert ag.is_safe_bash("ls") is True
    assert ag.is_safe_bash("ls -la") is True
    assert ag.is_safe_bash("wc sol.py") is True  # a plain workspace-relative file
    assert ag.is_safe_bash("date") is True


def test_metacharacters_still_blocked():
    assert ag.is_safe_bash("ls; rm -rf /") is False
    assert ag.is_safe_bash("cat $(echo x)") is False
    assert ag.is_safe_bash("ls | grep x") is False
