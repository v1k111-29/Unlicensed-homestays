import tasks


def test_all_documented_targets_exist() -> None:
    assert set(tasks.TARGETS) == {"setup", "run", "test", "lint", "eval", "seed", "migrate", "load"}


def test_unknown_target_rejected() -> None:
    assert tasks.main(["tasks.py", "nope"]) == 2


def test_missing_target_rejected() -> None:
    assert tasks.main(["tasks.py"]) == 2


def test_unimplemented_target_fails_loudly(capsys) -> None:
    assert tasks.main(["tasks.py", "eval"]) == 2
    assert "M5" in capsys.readouterr().out


def test_db_targets_need_database_url(monkeypatch, capsys) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(tasks, "DOTENV", tasks.ROOT / "does-not-exist.env")
    assert tasks.main(["tasks.py", "migrate"]) == 2
    assert "DATABASE_URL" in capsys.readouterr().out


def test_read_dotenv(tmp_path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "# comment\n\nDATABASE_URL=postgres://u:p@localhost/db\nQUOTED='a b'\nnoequals\n",
        encoding="utf-8",
    )
    assert tasks.read_dotenv(env) == {
        "DATABASE_URL": "postgres://u:p@localhost/db",
        "QUOTED": "a b",
    }


def test_dotenv_does_not_override_existing(monkeypatch, tmp_path) -> None:
    env = tmp_path / ".env"
    env.write_text("SOME_VS_TEST_VAR=from-file\n", encoding="utf-8")
    monkeypatch.setattr(tasks, "DOTENV", env)
    monkeypatch.setenv("SOME_VS_TEST_VAR", "from-shell")
    tasks._load_env()
    import os

    assert os.environ["SOME_VS_TEST_VAR"] == "from-shell"
