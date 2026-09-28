import env_loader


def test_ausencia_de_env_nao_e_erro(tmp_path):
    assert env_loader.carregar_env(str(tmp_path / "nao_existe.env")) == []


def test_le_pares_chave_valor(tmp_path, monkeypatch):
    monkeypatch.delenv("PSI_ENABLED", raising=False)
    monkeypatch.delenv("PSI_API_KEY", raising=False)
    p = tmp_path / ".env"
    p.write_text("PSI_ENABLED=1\nPSI_API_KEY=abc123\n", encoding="utf-8")

    definidas = env_loader.carregar_env(str(p))

    assert sorted(definidas) == ["PSI_API_KEY", "PSI_ENABLED"]
    import os
    assert os.environ["PSI_ENABLED"] == "1"
    assert os.environ["PSI_API_KEY"] == "abc123"


def test_ambiente_real_tem_precedencia(tmp_path, monkeypatch):
    monkeypatch.setenv("PSI_API_KEY", "do_ambiente")
    p = tmp_path / ".env"
    p.write_text("PSI_API_KEY=do_arquivo\n", encoding="utf-8")

    definidas = env_loader.carregar_env(str(p))

    import os
    assert "PSI_API_KEY" not in definidas
    assert os.environ["PSI_API_KEY"] == "do_ambiente"


def test_ignora_comentarios_linhas_vazias_e_aspas(tmp_path, monkeypatch):
    monkeypatch.delenv("FOO", raising=False)
    monkeypatch.delenv("BAR", raising=False)
    p = tmp_path / ".env"
    p.write_text(
        "# comentário\n"
        "\n"
        "   \n"
        'FOO="com aspas"\n'
        "BAR='outro'\n"
        "linha sem igual\n",
        encoding="utf-8",
    )

    definidas = env_loader.carregar_env(str(p))

    import os
    assert sorted(definidas) == ["BAR", "FOO"]
    assert os.environ["FOO"] == "com aspas"
    assert os.environ["BAR"] == "outro"


def test_valor_com_sinal_de_igual_e_preservado(tmp_path, monkeypatch):
    monkeypatch.delenv("TOKEN", raising=False)
    p = tmp_path / ".env"
    p.write_text("TOKEN=a=b=c\n", encoding="utf-8")

    env_loader.carregar_env(str(p))

    import os
    assert os.environ["TOKEN"] == "a=b=c"
