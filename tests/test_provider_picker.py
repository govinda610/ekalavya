"""The Settings provider picker: specific model OR 'Auto (sticky)' balancing."""

import os
import tempfile

os.environ["EKLAVYA_HOME"] = tempfile.mkdtemp(prefix="eklavya-prov-")

from starlette.testclient import TestClient  # noqa: E402

from eklavya import settings, webapp  # noqa: E402


def _client():
    return TestClient(webapp.create_app())


def test_auto_balanced_is_selectable_and_reflected():
    c = _client()
    assert c.get("/api/settings").json()["active_provider"] != "auto"  # default is a concrete lead
    assert c.put("/api/settings", json={"provider": "auto"}).json()["active_provider"] == "auto"
    assert settings.get_provider() == "auto"
    cfg = c.get("/api/config").json()
    assert cfg["provider"] == "Auto (sticky)"
    assert "fails over on exhaustion" in cfg["model"]
    assert c.get("/api/settings").json()["active_provider"] == "auto"


def test_can_override_back_to_a_specific_model():
    c = _client()
    c.put("/api/settings", json={"provider": "auto"})
    c.put("/api/settings", json={"provider": "glm"})
    assert settings.get_provider() == "glm"
    assert c.get("/api/config").json()["provider"] != "Auto (sticky)"


def test_spa_renders_the_auto_option():
    assert "Auto (sticky" in webapp._INDEX
    assert "value='auto'" in webapp._INDEX
