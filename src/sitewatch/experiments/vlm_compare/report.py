"""Локальный HTML, JSON и CSV. Секреты в отчёт не пишутся."""

from __future__ import annotations

import csv
from html import escape
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from sitewatch.experiments.vlm_compare.common import dump_json, redact_tree
from sitewatch.experiments.vlm_compare.prepare import resolve


def write_reports(
    out_dir: Path,
    *,
    plan: dict[str, Any],
    calls: list[dict[str, Any]],
    parses: dict[str, dict[str, Any]],
    scores: dict[str, Any],
    manifest: dict[str, Any],
    labels: dict[str, Any],
    secrets: list[str],
) -> None:
    safe_scores = redact_tree(scores, secrets)
    safe_calls = [redact_tree(call, secrets) for call in calls]
    dump_json(out_dir / "report.json", {"plan": redact_tree(plan, secrets), "scores": safe_scores, "calls": safe_calls})
    _write_csv(out_dir / "report.csv", safe_calls, parses)
    _write_html(out_dir, plan=plan, calls=safe_calls, parses=parses, scores=safe_scores, manifest=manifest, labels=labels)


def _write_csv(path: Path, calls: list[dict[str, Any]], parses: dict[str, dict[str, Any]]) -> None:
    fields = [
        "synthetic",
        "sample_id",
        "pair_id",
        "task",
        "response_mode",
        "model_id",
        "requested_model",
        "actual_model",
        "actual_provider",
        "provider_status",
        "parse_outcome",
        "count",
        "cost_usd",
        "cost_status",
        "duration_ms",
        "attempts",
        "finish_reason",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for call in calls:
            parsed = (parses.get(call.get("cache_key")) or {}).get("parsed") or {}
            writer.writerow(
                {
                    "synthetic": call.get("synthetic"),
                    "sample_id": call.get("sample_id"),
                    "pair_id": call.get("pair_id"),
                    "task": call.get("task"),
                    "response_mode": call.get("response_mode"),
                    "model_id": call.get("model_id"),
                    "requested_model": call.get("requested_model"),
                    "actual_model": call.get("actual_model"),
                    "actual_provider": call.get("actual_provider"),
                    "provider_status": call.get("status"),
                    "parse_outcome": (parses.get(call.get("cache_key")) or {}).get("outcome"),
                    "count": parsed.get("count") if isinstance(parsed, dict) else None,
                    "cost_usd": call.get("cost_usd"),
                    "cost_status": call.get("cost_status"),
                    "duration_ms": call.get("duration_ms"),
                    "attempts": call.get("attempts"),
                    "finish_reason": call.get("finish_reason"),
                }
            )


def _write_html(out_dir: Path, **kwargs: Any) -> None:
    plan = kwargs["plan"]
    calls = kwargs["calls"]
    parses = kwargs["parses"]
    scores = kwargs["scores"]
    manifest = kwargs["manifest"]
    labels = kwargs["labels"]
    synthetic = any(call.get("synthetic") for call in calls)
    samples = {item["sample_id"]: item for item in manifest["samples"]}
    label_rows = labels.get("items") or []
    parts = [
        "<!DOCTYPE html><html lang='ru'><head><meta charset='utf-8'>",
        "<title>Сравнение VLM — экспериментальный отчёт</title>",
        "<style>body{font-family:sans-serif;margin:24px;background:#f6f4ef;color:#1c1a16}"
        "table{border-collapse:collapse;width:100%;background:#fff}td,th{border:1px solid #ddd;padding:6px;vertical-align:top}"
        ".banner{background:#7a1f1f;color:#fff;padding:12px 16px;font-weight:700}"
        ".card{background:#fff;padding:16px;margin:16px 0;border:1px solid #e4dfd4}"
        "img{max-width:360px;height:auto} .muted{color:#666}</style></head><body>",
    ]
    if synthetic:
        parts.append(
            "<div class='banner'>ФИКТИВНЫЙ ПРОГОН. Ответы созданы тестовым транспортом. "
            "Это не ответы OpenRouter и не ответ локальной модели. Метрики качества по ним не считаются.</div>"
        )
    acc = scores.get("accuracy") or {}
    parts.append("<h1>Экспериментальное сравнение визуальных моделей</h1>")
    parts.append(
        "<p class='muted'>Точность и MAE считаются только на нефиктивных ответах с подтверждённым точным эталоном. "
        "Оценка агента таким эталоном не является. Попадание на двух знакомых офисных кадрах не доказывает перенос.</p>"
    )
    parts.append("<ul>")
    parts.append(f"<li>Точность количества: {_fmt(acc.get('count_exact'))} (примеров {acc.get('count_support')})</li>")
    parts.append(f"<li>MAE: {_fmt(acc.get('mae'))}</li>")
    rate = scores.get("answer_rate") or {}
    parts.append(
        f"<li>Ответы с числом: {rate.get('with_number', 0)}; отказы: {rate.get('refusals', 0)}; "
        f"завершённые ответы провайдера: {rate.get('completed_provider', 0)}; записей: {rate.get('calls', 0)}. "
        "Сводка не включает фиктивные ответы.</li>"
    )
    parts.append(f"<li>Ошибки на пустых сценах: {_fmt(scores.get('empty_scene_error_rate'))}</li>")
    parts.append(f"<li>Наличие/отсутствие: {_fmt(scores.get('presence_accuracy'))}</li>")
    parts.append(
        f"<li>Локализация: {_fmt(scores.get('localization_accuracy'))} "
        f"(размеченных категорий {scores.get('localization_support')})</li>"
    )
    parts.append(f"<li>Ракурс на проверенных парах: {_fmt(scores.get('change_viewpoint_accuracy'))}</li>")
    parts.append(f"<li>Технические ошибки: {scores.get('technical_errors')}; ошибки восприятия: {scores.get('perception_errors')}</li>")
    parts.append(f"<li>Средняя задержка, мс: {_fmt(scores.get('latency_ms_mean'))}</li>")
    parts.append(
        f"<li>Фактическая стоимость, USD: {_fmt(scores.get('cost_usd_sum'))}; "
        f"вызовов с неизвестной стоимостью: {scores.get('unknown_cost_calls')}</li>"
    )
    parts.append("</ul>")
    limits = plan.get("limitations") or []
    if limits:
        parts.append("<h2>Ограничения</h2><ul>")
        parts.extend(f"<li>{escape(str(item))}</li>" for item in limits)
        parts.append("</ul>")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for call in calls:
        grouped.setdefault(call.get("sample_id") or call.get("pair_id") or "?", []).append(call)
    for sample_id, sample in samples.items():
        parts.append("<section class='card'>")
        parts.append(f"<h2>{escape(sample_id)} <span class='muted'>{escape(str(sample.get('split')))}</span></h2>")
        parts.append(_images_html(out_dir, sample, label_rows, grouped.get(sample_id, [])))
        parts.append(_label_block([item for item in label_rows if item.get("sample_id") == sample_id]))
        parts.append(_call_table(grouped.get(sample_id, []), parses))
        parts.append("</section>")
    for pair in manifest.get("pairs") or []:
        parts.append("<section class='card'>")
        parts.append(f"<h2>Пара {escape(pair['pair_id'])}</h2>")
        parts.append(
            f"<p>Порядок: {escape(str(pair.get('order')))}. Интервал, дни: {escape(str(pair.get('interval_days')))}. "
            f"Интервал достоверен: {escape(str(pair.get('interval_reliable')))}. "
            f"Для календарного отставания не используется.</p>"
        )
        parts.append(_call_table(grouped.get(pair["pair_id"], []), parses))
        parts.append("</section>")
    parts.append("</body></html>")
    (out_dir / "report.html").write_text("".join(parts), encoding="utf-8")


def _fmt(value: Any) -> str:
    if value is None:
        return "нет данных"
    if isinstance(value, float):
        return f"{value:.4f}"
    return escape(str(value))


def _label_block(items: list[dict[str, Any]]) -> str:
    if not items:
        return "<p class='muted'>Проверочной оценки для этого примера нет.</p>"
    chunks = ["<p><b>Проверочная оценка.</b> Автор — агент, статус предварительный. Это не независимая человеческая разметка.</p><ul>"]
    for item in items:
        chunks.append(
            "<li>"
            f"{escape(str(item.get('task')))}: value={escape(str(item.get('value')))}, "
            f"range={escape(str(item.get('allowed_range')))}, "
            f"visibility={escape(str(item.get('visibility')))}, "
            f"ambiguity={escape(str(item.get('ambiguity')))}, "
            f"review={escape(str(item.get('review_status')))}. "
            f"{escape(str(item.get('notes') or ''))}"
            "</li>"
        )
    chunks.append("</ul>")
    return "".join(chunks)


def _images_html(out_dir: Path, sample: dict[str, Any], labels: list[dict[str, Any]], calls: list[dict[str, Any]]) -> str:
    source = resolve(sample["image"])
    overlay = _overlay(out_dir, sample, labels, source)
    chunks = ["<div>"]
    shown = False
    for call in calls:
        for image in call.get("images") or []:
            name = image.get("stored_name")
            if not name:
                continue
            rel = f"images/{name}"
            if (out_dir / rel).is_file():
                chunks.append(
                    f"<figure><img src='{escape(rel)}' alt='{escape(str(image.get('role')))}'>"
                    f"<figcaption>{escape(str(image.get('role')))} {escape(str(image.get('neutral_id')))}</figcaption></figure>"
                )
                shown = True
        if shown:
            break
    if overlay:
        rel = overlay.relative_to(out_dir).as_posix()
        chunks.append(
            f"<figure><img src='{escape(rel)}' alt='overlay'>"
            "<figcaption>Исходник: рамка кропа и полосы агента. На вход модели полосы не наносились.</figcaption></figure>"
        )
    chunks.append("</div>")
    return "".join(chunks)


def _overlay(out_dir: Path, sample: dict[str, Any], labels: list[dict[str, Any]], source: Path) -> Path | None:
    regions = []
    for item in labels:
        if item.get("sample_id") == sample["sample_id"] and item.get("regions"):
            regions.extend(item["regions"])
    if not source.is_file():
        return None
    dest_dir = out_dir / "overlays"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{sample['sample_id']}.jpg"
    with Image.open(source) as raw:
        image = raw.convert("RGB")
        draw = ImageDraw.Draw(image)
        box = sample.get("crop_xyxy") or []
        if len(box) == 4:
            draw.rectangle(box, outline=(20, 90, 180), width=4)
        for region in regions:
            rect = [region["x0"], region["y0"], region["x1"], region["y1"]]
            draw.rectangle(rect, outline=(180, 90, 20), width=3)
        image.save(dest, quality=80)
    return dest


def _call_table(calls: list[dict[str, Any]], parses: dict[str, dict[str, Any]]) -> str:
    if not calls:
        return "<p class='muted'>Вызовов нет.</p>"
    rows = ["<table><tr><th>Модель</th><th>Режим</th><th>Провайдер</th><th>Разбор</th><th>Ответ</th><th>Технически</th></tr>"]
    for call in calls:
        parsed = parses.get(call.get("cache_key")) or {}
        badge = "ФИКСТУРА" if call.get("synthetic") else call.get("actual_provider")
        body = parsed.get("parsed")
        text = escape(str(body if body is not None else parsed.get("outcome")))
        rows.append(
            "<tr>"
            f"<td>{escape(str(call.get('model_id')))}<br><span class='muted'>{escape(str(call.get('requested_model')))}</span></td>"
            f"<td>{escape(str(call.get('response_mode')))}<br>{escape(str(call.get('task')))}</td>"
            f"<td>{escape(str(badge))}<br>{escape(str(call.get('status')))} / {escape(str(call.get('finish_reason')))}</td>"
            f"<td>{escape(str(parsed.get('outcome')))}</td>"
            f"<td>{text}</td>"
            f"<td>попытки {escape(str(call.get('attempts')))}; стоимость {escape(str(call.get('cost_usd')))} ({escape(str(call.get('cost_status')))})</td>"
            "</tr>"
        )
    rows.append("</table>")
    return "".join(rows)
