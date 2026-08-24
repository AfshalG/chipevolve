import chipevolve.agents.session as session


def test_credentials_missing_when_no_env(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    assert session.credentials_available() is False


def test_either_credential_variable_counts(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert session.credentials_available() is True

    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "token")
    assert session.credentials_available() is True


def test_blank_key_is_not_a_credential(monkeypatch) -> None:
    """An empty VS Code setting exports an empty string, not an unset var."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "   ")
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    assert session.credentials_available() is False
