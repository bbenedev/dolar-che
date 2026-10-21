from dolar_che import settings


def test_token_from_the_environment_wins(tmp_path):
    (tmp_path / "token").write_text("from-file\n", encoding="utf-8")
    assert settings.load_token({"DISCORD_TOKEN": " from-env "}, tmp_path) == "from-env"


def test_token_from_the_file_uses_the_first_line_only(tmp_path):
    (tmp_path / "token").write_text("  abc.def  \nnotes the user wrote\n", encoding="utf-8")
    assert settings.load_token({}, tmp_path) == "abc.def"


def test_no_token_anywhere_is_none(tmp_path):
    assert settings.load_token({}, tmp_path) is None
    (tmp_path / "token").write_text("\n", encoding="utf-8")
    assert settings.load_token({}, tmp_path) is None


def test_summary_channel_roundtrip_and_switch_off(tmp_path):
    assert settings.summary_channel({}, tmp_path) is None
    settings.set_summary_channel(tmp_path, 1234)
    assert settings.summary_channel({}, tmp_path) == 1234
    settings.set_summary_channel(tmp_path, None)
    assert settings.summary_channel({}, tmp_path) is None


def test_summary_channel_from_the_environment_wins(tmp_path):
    settings.set_summary_channel(tmp_path, 1234)
    assert settings.summary_channel({"DOLAR_CHE_CANAL_RESUMEN": "999"}, tmp_path) == 999


def test_a_broken_config_file_means_no_channel(tmp_path):
    (tmp_path / "config.json").write_text("{not json", encoding="utf-8")
    assert settings.summary_channel({}, tmp_path) is None
    settings.set_summary_channel(tmp_path, 5)
    assert settings.summary_channel({}, tmp_path) == 5
