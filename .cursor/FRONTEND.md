# Frontend map

React 19 + Vite 7 + react-router-dom 7. Без UI-kit.  
Контекст — `WorkspaceProvider`. Пути — `frontend/src/routes.ts`. UI на `:8000` (`frontend/dist`).

Backend **Zone** ↔ UI **«объект»** (`zoneCode`).

---

## CURRENT

### Маршруты

| Путь | Роль |
|------|------|
| `/` → `/objects` | Старт: визуальная витрина |
| `/objects` | Витрина: обложка = последний реальный кадр (`preview_url`) |
| `/objects/new` | Создать объект (имя, описание, вид) → workspace |
| `/objects/:zoneCode` | Обзор |
| `…/progress` | План-факт (+ раскрытие редактора графика) |
| `…/sources` | Камеры; локально «Фото и видео» (`?view=media`) |
| `…/history` | Хронология; кадр: `?observation=` |
| `…/signals` | Сигналы объекта |
| `…/notes` | Заметки (из меню шапки) |
| `…/settings` | Настройки объекта (из меню шапки) |
| `/project` | Информация о проекте (`/setup` → redirect) |
| `/signals` | Глобальная очередь сигналов (не в стартовом sidebar) |

Legacy: `/dashboard`→objects; `/queue|alerts|inspect`→signals; `/object` `/timeline`→object sections; `?tab=`→section path; `/schedule`→progress?edit=schedule.

### Sidebar

**Всегда стартовый:** знак «Скрипка» и строка «Контроль строительства» · Объекты · «Добавить объект» · «О проекте».

**В объекте:** вкладки в шапке контента — Обзор, Камеры, План-факт, Хронология, Сигналы. Заметки и настройки — ссылки в шапке.

Фильтры/scroll витрины: `sessionStorage` `sitewatch.objects.list` / `.scroll`.

### Витрина

Порядок и `card_state` / `rank_reason` / `preview_url` / cover_* — с API (`sort_zones_for_vitrine`). Без fake stock. Нет кадра → empty + «Добавить фото» / «Подключить источник».

### Подобъекты

В модели runtime нет — не дублировать параллельной структурой.

### Проверки

```bash
cd frontend && npm run typecheck && npm test && npm run build
```
