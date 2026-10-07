# Thin wrapper only. No logic here: tasks.py is the single source of commands.
.PHONY: setup run test lint eval seed migrate load

setup run test lint eval seed migrate load:
	python tasks.py $@
