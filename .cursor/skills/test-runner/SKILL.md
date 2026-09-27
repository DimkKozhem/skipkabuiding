---
name: test-runner
description: Run Скрипка pytest from LCT2026/.venv. Use after code changes or when verifying work.
disable-model-invocation: true
---

# Test Runner (LCT2026)

Интерпретатор только `LCT2026/.venv`, не `myenv`.

```bash
cd /home/dimk/my_project/LCT2026
.venv/bin/python -m pytest -q
```

Один файл:

```bash
.venv/bin/python -m pytest tests/test_e2e.py -q
.venv/bin/python -m pytest tests/test_temporal.py tests/test_deviation.py -q
```

`conftest.py` изолирует SQLite через `tmp_path`. Не писать в чужой `data/observations/sitewatch.db` из тестов.

Успех — коротко (`N passed`). Падение — файл, тест, traceback. Починить и перезапустить.
