"""Private configuration setup stays local, exclusive and independent of model inference."""

import os
import pytest

from scripts.configure_review import configure


def test_setup_generates_private_secret_without_reusing_it(tmp_path):
    first, second = tmp_path / "one", tmp_path / "two"
    configure("synthetic-public-client", output=first)
    configure("synthetic-public-client", output=second)
    text = first.read_text()
    assert "BERN_REVIEW_HF_CLIENT_ID=synthetic-public-client" in text
    secret = text.split("BERN_REVIEW_SESSION_SECRET=", 1)[1].strip()
    assert len(secret) >= 32 and secret not in second.read_text()
    if os.name != "nt":
        assert first.stat().st_mode & 0o777 == 0o600


def test_setup_never_overwrites_existing_private_settings(tmp_path):
    path = tmp_path / "existing"
    path.write_text("keep unchanged")
    with pytest.raises(FileExistsError):
        configure("synthetic-public-client", output=path)
    assert path.read_text() == "keep unchanged"


@pytest.mark.parametrize("client,callback", [
    ("bad\nCLIENT=other", "http://127.0.0.1:17863/auth/huggingface/callback"),
    ("client", "http://example.org/auth/huggingface/callback"),
    ("client", "http://127.0.0.1:17863/wrong"),
])
def test_setup_rejects_invalid_settings_before_writing(tmp_path, client, callback):
    path = tmp_path / "not-created"
    with pytest.raises(ValueError):
        configure(client, callback, path)
    assert not path.exists()
