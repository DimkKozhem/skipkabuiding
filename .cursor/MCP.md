# MCP — LCT2026

Базовые серверы из глобального `~/.cursor/mcp.json`. Проектный `.cursor/mcp.json` **не коммитить**: шаблон — `mcp.json.example`.

Схемы: `GetDynamicTools` **перед** вызовом.

## Подключено (глобально)

| Сервер | Когда |
|--------|--------|
| `user-context7` | Доки FastAPI, React, Ultralytics, OpenCV |
| `user-fetch` | Публичный URL; smoke `http://127.0.0.1:8000` |
| `cursor-ide-browser` | Проверка UI React |
| `user-github` | Только GitHub |

## Не дублировать в проектном mcp.json

`context7`, `fetch`, `github` уже в `~/.cursor/mcp.json`.

## Замены

| Нет в MCP | Чем |
|-----------|-----|
| lean-ctx MCP | CLI `lean-ctx` + native Read/Grep/Glob |
| YOLO/SAM runtime | `LCT2026/.venv` + `src/sitewatch/cv/` |

## Порядок

1. Код — Grep/Glob/Read; большой файл — `lean-ctx read -m map`.
2. Доки библиотек — `user-context7`.
3. Правки — native Edit/Write.
4. UI — browser на `http://127.0.0.1:8000` (skill `improve-sitewatch-ui`). Карта: `.cursor/FRONTEND.md`.
5. В MCP не передавать `.env`, веса моделей, содержимое БД.
