"""Tests for Chroma runtime configuration and client selection."""

from unittest.mock import patch


def test_chroma_http_client_uses_configured_host(monkeypatch):
    from core.config import get_settings
    import knowledge.store as store

    settings = get_settings()
    monkeypatch.setattr(settings, "CHROMA_MODE", "http")
    monkeypatch.setattr(settings, "CHROMA_HOST", "chroma")
    monkeypatch.setattr(settings, "CHROMA_PORT", 8000)
    monkeypatch.setattr(settings, "CHROMA_SSL", False)

    with patch("chromadb.HttpClient") as http_client:
        store.create_chroma_client()

    http_client.assert_called_once_with(host="chroma", port=8000, ssl=False)


def test_chroma_persistent_client_kept_for_explicit_local_mode(monkeypatch, tmp_path):
    from core.config import get_settings
    import knowledge.store as store

    settings = get_settings()
    monkeypatch.setattr(settings, "CHROMA_MODE", "persistent")
    monkeypatch.setattr(settings, "CHROMA_PERSIST_DIR", str(tmp_path / "kb"))

    with patch("chromadb.PersistentClient") as persistent_client:
        store.create_chroma_client()

    _, kwargs = persistent_client.call_args
    assert kwargs["path"] == str(tmp_path / "kb")
