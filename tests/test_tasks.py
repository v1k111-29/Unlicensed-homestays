import tasks


def test_all_documented_targets_exist() -> None:
    assert set(tasks.TARGETS) == {"setup", "run", "test", "lint", "eval", "seed", "migrate"}


def test_unknown_target_rejected() -> None:
    assert tasks.main(["tasks.py", "nope"]) == 2


def test_missing_target_rejected() -> None:
    assert tasks.main(["tasks.py"]) == 2


def test_unimplemented_target_fails_loudly(capsys) -> None:
    assert tasks.main(["tasks.py", "eval"]) == 2
    assert "M5" in capsys.readouterr().out
