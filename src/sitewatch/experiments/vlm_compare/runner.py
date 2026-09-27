"""План, запуск, кеш и продолжение. В рабочую БД не пишет."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sitewatch.experiments.vlm_compare.catalog import load_catalog, model_index, token_prices
from sitewatch.experiments.vlm_compare.common import PROJECT_ROOT, dump_json, load_json, redact_tree, sha256_file
from sitewatch.experiments.vlm_compare.parse import CLASSIFIER_VERSION, PARSER_VERSION, VALIDATOR_VERSION, parse_provider_output
from sitewatch.experiments.vlm_compare.prepare import (
    assert_prompt_isolated,
    clock_visible,
    config_fingerprint,
    generation_for_model,
    generation_of,
    image_meta,
    inference_cache_key,
    load_schema,
    load_template,
    pair_mapping,
    prepare_sample_views,
    preprocessing_of,
    render_prompt,
    resolve,
    openrouter_pin_error,
    route_of,
    single_mapping,
)
from sitewatch.experiments.vlm_compare.report import write_reports
from sitewatch.experiments.vlm_compare.score import SCORER_VERSION, load_labels, score_calls
from sitewatch.experiments.vlm_compare.transport import (
    CallSpec,
    FixtureTransport,
    LocalOpenAITransport,
    OpenRouterTransport,
    ProviderRaw,
)

TERMINAL = {
    "completed",
    "truncated",
    "provider_error",
    "http_error",
    "refused",
    "unsupported",
    "ambiguous_after_send",
}


def plan_experiment(
    config: dict[str, Any],
    manifest: dict[str, Any],
    catalog: dict[str, Any],
    *,
    model_ids: set[str] | None = None,
    split: str | None = None,
    sample_ids: set[str] | None = None,
    tasks: set[str] | None = None,
    response_modes: set[str] | None = None,
    transport_override: str | None = None,
) -> dict[str, Any]:
    fingerprint = config_fingerprint(config)
    catalog_models = model_index(catalog)
    internal = list(
        _jobs(
            config,
            manifest,
            catalog_models,
            model_ids=model_ids,
            split=split,
            sample_ids=sample_ids,
            tasks=tasks,
            response_modes=response_modes,
            transport_override=transport_override,
        )
    )
    jobs = [{key: value for key, value in job.items() if not str(key).startswith("_")} for job in internal]
    billed = [job for job in jobs if job["billed"] and job["supported"]]
    estimate = sum(job["estimate_usd"] for job in billed if job["estimate_usd"] is not None)
    unknown_price = [job["model_id"] for job in billed if job["estimate_usd"] is None]
    return {
        "kind": "plan",
        "images_sent": False,
        "revision": fingerprint["revision"],
        "config_sha256": fingerprint["config_sha256"],
        "file_hashes": fingerprint["files"],
        "catalog_fetched_at": catalog.get("fetched_at"),
        "models": _model_cards(config, catalog_models, transport_override),
        "samples": len(manifest["samples"]),
        "pairs": len(manifest.get("pairs") or []),
        "source_images": len({sample["sha256"] for sample in manifest["samples"]}),
        "calls": len(jobs),
        "billable_calls": len(billed),
        "skipped_unsupported": sum(1 for job in jobs if not job["supported"]),
        "sent_images": sum(job["n_images"] for job in jobs if job["supported"]),
        "generation": generation_of(config),
        "max_retries": int(config.get("max_retries") or 0),
        "concurrency": 1,
        "estimate_usd": None if unknown_price else round(estimate, 6),
        "models_without_price": sorted(set(unknown_price)),
        "jobs": jobs,
        "_jobs": internal,
        "limitations": _limitations(catalog, unknown_price),
    }


def _limitations(catalog: dict[str, Any], unknown_price: list[str]) -> list[str]:
    notes = [
        "Оценка стоимости — верхняя прикидка по цене каталога и запасу токенов, не счёт OpenRouter.",
        "Лимит USD не является гарантированным денежным пределом, если цена или usage неизвестны. Жёсткие пределы — число запросов и выходных токенов.",
        "Повтор после неоднозначного обрыва не выполняется: запрос мог быть уже оплачен.",
        "Ревизия весов внешнего провайдера не обещается, если API её не сообщил.",
        "Офисные даты интерполированы по видео и не используются для календарного отставания.",
        "Оценка агента не является независимой человеческой разметкой.",
        f"Каталог получен {catalog.get('fetched_at') or 'unknown'}.",
    ]
    if unknown_price:
        notes.append("Для части моделей в снимке каталога нет цены: денежный лимит по ним не гарантируется.")
    missing = catalog.get("missing") or []
    if missing:
        notes.append("В снимке каталога нет идентификаторов: " + ", ".join(missing))
    return notes


def _model_cards(config: dict[str, Any], catalog_models: dict[str, dict[str, Any]], override: str | None) -> list[dict[str, Any]]:
    cards = []
    for model in config["models"]:
        entry = catalog_models.get(model["model"])
        prices = _endpoint_prices(model) or (token_prices(entry) if model.get("transport") == "openrouter" else None)
        price_status = "pinned_endpoint" if _endpoint_prices(model) else ("catalog" if prices else "unknown")
        modalities = (entry or {}).get("input_modalities")
        cards.append(
            {
                "id": model["id"],
                "requested_model": model["model"],
                "transport": override or model["transport"],
                "provider_order": list(model.get("provider_order") or []),
                "provider_only": list(model.get("provider_only") or []),
                "allow_fallbacks": model.get("allow_fallbacks"),
                "route_pin": (
                    "not_openrouter"
                    if model.get("transport") != "openrouter"
                    else (openrouter_pin_error(model) or "pinned")
                ),
                "structured_output": model.get("structured_output"),
                "input_modalities": modalities if modalities is not None else "unknown",
                "prompt_usd_per_token": prices[0] if prices else None,
                "completion_usd_per_token": prices[1] if prices else None,
                "price_status": price_status,
            }
        )
    return cards


def _jobs(config, manifest, catalog_models, *, model_ids, split, sample_ids, tasks, response_modes, transport_override) -> Any:
    estimate_cfg = config.get("estimate") or {}
    text_tokens = 500 if estimate_cfg.get("prompt_text_tokens") is None else int(estimate_cfg["prompt_text_tokens"])
    per_image = 1600 if estimate_cfg.get("tokens_per_image") is None else int(estimate_cfg["tokens_per_image"])
    max_tokens = int((config.get("generation") or {}).get("max_tokens") or 400)
    samples = {item["sample_id"]: item for item in manifest["samples"]}
    units: list[tuple[dict[str, Any] | None, dict[str, Any] | None, str]] = []
    for sample in manifest["samples"]:
        if split and sample.get("split") != split:
            continue
        if sample_ids and sample.get("sample_id") not in sample_ids:
            continue
        for task in sample.get("applicable_tasks") or []:
            if tasks and task not in tasks:
                continue
            units.append((sample, None, task))
    for pair in manifest.get("pairs") or []:
        if split and pair.get("split") != split:
            continue
        if sample_ids and pair.get("pair_id") not in sample_ids:
            continue
        for task in pair.get("tasks") or []:
            if tasks and task not in tasks:
                continue
            units.append((None, pair, task))
    for sample, pair, task in units:
        n_images = 4 if pair else 2
        for model in config["models"]:
            if model_ids and model["id"] not in model_ids:
                continue
            transport = transport_override or model["transport"]
            modes = response_modes or set(config.get("response_modes") or ["text"])
            for mode in config.get("response_modes") or ["text"]:
                if mode not in modes:
                    continue
                supported = True
                reason = None
                if mode == "structured" and model.get("structured_output") == "unsupported" and transport != "fixture":
                    supported = False
                    reason = "structured_output_unsupported"
                if transport == "openrouter":
                    entry = catalog_models.get(model["model"])
                    modalities = (entry or {}).get("input_modalities")
                    if modalities is not None and "image" not in modalities:
                        supported = False
                        reason = "catalog_without_image"
                    prices = token_prices(entry)
                else:
                    prices = None
                price_status = "catalog" if prices else "unknown"
                endpoint_prices = _endpoint_prices(model)
                if endpoint_prices:
                    prices = endpoint_prices
                    price_status = "pinned_endpoint"
                estimate = None
                if prices and supported:
                    prompt_tokens = text_tokens + per_image * n_images
                    estimate = round(prompt_tokens * prices[0] + max_tokens * prices[1], 8)
                yield {
                    "sample_id": None if sample is None else sample["sample_id"],
                    "pair_id": None if pair is None else pair["pair_id"],
                    "split": (sample or pair).get("split"),
                    "task": task,
                    "model_id": model["id"],
                    "requested_model": model["model"],
                    "transport": transport,
                    "response_mode": mode,
                    "supported": supported,
                    "skip_reason": reason,
                    "n_images": n_images,
                    "billed": transport == "openrouter" and supported,
                    "estimate_usd": estimate,
                    "price_status": price_status,
                    "price_prompt": prices[0] if prices else None,
                    "price_completion": prices[1] if prices else None,
                    "_sample": sample,
                    "_pair": pair,
                    "_model": model,
                }


def _endpoint_prices(model: dict[str, Any]) -> tuple[float, float] | None:
    pricing = model.get("endpoint_pricing_usd_per_token") or {}
    prompt = pricing.get("prompt")
    completion = pricing.get("completion")
    if prompt is None or completion is None:
        return None
    try:
        return float(prompt), float(completion)
    except (TypeError, ValueError):
        return None


def execute_run(
    config: dict[str, Any],
    manifest: dict[str, Any],
    catalog: dict[str, Any],
    *,
    out_dir: Path,
    execute: bool,
    budget_usd: float | None = None,
    max_requests: int | None = None,
    max_output_tokens: int | None = None,
    allow_unknown_price: bool = False,
    retry_ambiguous: bool = False,
    transport_override: str | None = None,
    transports: dict[str, Any] | None = None,
    model_ids: set[str] | None = None,
    split: str | None = None,
    sample_ids: set[str] | None = None,
    tasks: set[str] | None = None,
    response_modes: set[str] | None = None,
    secrets: list[str] | None = None,
    labels_path: Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    plan = plan_experiment(
        config,
        manifest,
        catalog,
        model_ids=model_ids,
        split=split,
        sample_ids=sample_ids,
        tasks=tasks,
        response_modes=response_modes,
        transport_override=transport_override,
    )
    jobs = plan.pop("_jobs", [])
    if not execute:
        plan["images_sent"] = False
        return plan
    needs_budget = any(job["billed"] for job in plan["jobs"])
    if needs_budget and (budget_usd is None or max_requests is None or max_output_tokens is None):
        raise RuntimeError("paid_run_requires_budget_request_and_token_caps")
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = load_json(out_dir / "run.json") if (out_dir / "run.json").is_file() else {}
    run_id = run_id or existing.get("run_id") or "vc-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    secret_values = [item for item in (secrets or []) if item]
    ledger = existing.get("ledger") or {
        "budget_usd": budget_usd,
        "max_requests": max_requests,
        "max_output_tokens": max_output_tokens,
        "spent_usd": 0.0,
        "reserved_usd": 0.0,
        "requests": 0,
        "http_attempts": 0,
        "successful_responses": 0,
        "parsed_responses": 0,
        "output_tokens": 0,
        "unknown_cost_calls": 0,
        "budget_is_money_guarantee": True,
        "stopped_reason": None,
    }
    if budget_usd is not None:
        ledger["budget_usd"] = budget_usd
        ledger["max_requests"] = max_requests
        ledger["max_output_tokens"] = max_output_tokens
    clients = dict(transports or {})
    shared_ledger_path = resolve(config["attempt_ledger"]) if config.get("attempt_ledger") else None
    shared_ledger = _load_shared_attempts(shared_ledger_path) if shared_ledger_path else None
    if shared_ledger is not None:
        ledger["shared_attempt_remaining"] = _shared_attempt_remaining(shared_ledger)
        if ledger["shared_attempt_remaining"] <= 0:
            ledger["attempt_budget_exhausted"] = True
    views_cache: dict[str, Any] = {}
    image_dir = out_dir / "images"
    label_text = ""
    if labels_path and labels_path.is_file():
        label_text = labels_path.read_text(encoding="utf-8")
    manifest_text = Path(manifest["_path"]).read_text(encoding="utf-8") if manifest.get("_path") else ""
    blocked_reason = None
    active_keys: list[str] = []
    for job in jobs:
        record = _prepare_record(job, config, manifest, plan, views_cache, image_dir, label_text, manifest_text)
        active_keys.append(record["cache_key"])
        path = out_dir / "calls" / f"{record['cache_key']}.json"
        previous = load_json(path) if path.is_file() else None
        if previous and previous.get("cache_key") == record["cache_key"]:
            action = _resume_action(previous, retry_ambiguous=retry_ambiguous)
            if action == "skip":
                continue
            if action == "mark_ambiguous":
                previous["status"] = "ambiguous_after_send"
                previous["completed"] = False
                previous["errors"] = list(previous.get("errors") or []) + ["resume_found_unfinished_send"]
                _write_call(path, previous, secret_values)
                if job["billed"]:
                    ledger["unknown_cost_calls"] += 1
                    ledger["budget_is_money_guarantee"] = False
                    blocked_reason = "ambiguous_cost_unknown"
                continue
        if job["transport"] == "openrouter" and job["supported"]:
            pin_error = openrouter_pin_error(job["_model"])
            if pin_error:
                record["status"] = "not_sent"
                record["completed"] = False
                record["invoked"] = False
                record["errors"] = [pin_error]
                _write_call(path, record, secret_values)
                continue
        if not job["supported"]:
            record["status"] = "unsupported"
            record["completed"] = False
            record["invoked"] = False
            record["errors"] = [job.get("skip_reason") or "unsupported"]
            record["unsupported_settings"] = ["response_format"] if job.get("skip_reason") == "structured_output_unsupported" else []
            _write_call(path, record, secret_values)
            continue
        if job["billed"]:
            reason = _budget_block(ledger, job, config, allow_unknown_price=allow_unknown_price)
            if blocked_reason:
                reason = blocked_reason
            if reason:
                blocked_reason = reason
                ledger["stopped_reason"] = reason
                record["status"] = "not_sent"
                record["completed"] = False
                record["invoked"] = False
                record["errors"] = [reason]
                _write_call(path, record, secret_values)
                continue
            ledger["reserved_usd"] = (job["estimate_usd"] or 0) * (int(config.get("max_retries") or 0) + 1)
        record["status"] = "sending"
        record["invoked"] = True
        _write_call(path, record, secret_values)
        if job["billed"]:
            job["_attempt_room"] = _attempt_room(ledger)
        raw = _dispatch(job, record, clients, config, secret_values)
        filled = _apply_raw(record, raw, job, catalog)
        _account(ledger, job, filled, config)
        if shared_ledger is not None and job["billed"] and filled.get("invoked"):
            _append_shared_attempt(shared_ledger_path, shared_ledger, filled, run_id)
            ledger["shared_attempt_remaining"] = _shared_attempt_remaining(shared_ledger)
            if ledger["shared_attempt_remaining"] <= 0:
                ledger["attempt_budget_exhausted"] = True
        ledger["reserved_usd"] = 0.0
        if job["billed"] and filled.get("cost_status") == "unknown":
            ledger["budget_is_money_guarantee"] = False
            ledger["unknown_reserved_usd"] = float(ledger.get("unknown_reserved_usd") or 0) + float(job.get("estimate_usd") or 0)
            if not _pre_send_connect_failure(filled):
                ledger["unknown_cost_calls"] += 1
                if not config.get("continue_after_unknown_cost"):
                    blocked_reason = "cost_unknown_after_send"
                    ledger["stopped_reason"] = blocked_reason
        _write_call(path, filled, secret_values)
    wanted = set(active_keys)
    calls = [call for call in _load_calls(out_dir) if call.get("cache_key") in wanted]
    parses = _ensure_parses(out_dir, calls)
    ledger["parsed_responses"] = sum(1 for item in parses.values() if item.get("parse_status") == "ok")
    labels = load_labels(labels_path) if labels_path and labels_path.is_file() else {"items": [], "author_kind": "agent_preliminary"}
    scores = score_calls(calls, parses, labels, scorer_version=SCORER_VERSION)
    dump_json(out_dir / "scores.json", redact_tree(scores, secret_values))
    state = {
        "run_id": run_id,
        "images_sent": any(call.get("invoked") for call in calls),
        "plan_summary": {key: plan[key] for key in plan if key != "jobs"},
        "ledger": ledger,
        "parser_version": PARSER_VERSION,
        "scorer_version": SCORER_VERSION,
    }
    dump_json(out_dir / "run.json", redact_tree(state, secret_values))
    write_reports(
        out_dir,
        plan=plan,
        calls=calls,
        parses=parses,
        scores=scores,
        manifest=manifest,
        labels=labels,
        secrets=secret_values,
    )
    state["calls"] = len(calls)
    state["report"] = str(out_dir / "report.html")
    return state


def rescore(out_dir: Path, labels_path: Path, *, scorer_version: str = SCORER_VERSION, secrets: list[str] | None = None) -> dict[str, Any]:
    calls = _load_calls(out_dir)
    parses = _ensure_parses(out_dir, calls)
    labels = load_labels(labels_path)
    scores = score_calls(calls, parses, labels, scorer_version=scorer_version)
    dump_json(out_dir / "scores.json", redact_tree(scores, secrets or []))
    return scores


def rebuild_report(out_dir: Path, manifest: dict[str, Any], labels_path: Path, secrets: list[str] | None = None) -> None:
    calls = _load_calls(out_dir)
    parses = _ensure_parses(out_dir, calls)
    labels = load_labels(labels_path)
    scores = load_json(out_dir / "scores.json") if (out_dir / "scores.json").is_file() else score_calls(calls, parses, labels)
    run = load_json(out_dir / "run.json")
    plan = run.get("plan_summary") or {"limitations": []}
    write_reports(out_dir, plan=plan, calls=calls, parses=parses, scores=scores, manifest=manifest, labels=labels, secrets=secrets or [])


def _resume_action(previous: dict[str, Any], *, retry_ambiguous: bool) -> str:
    status = previous.get("status")
    if status in TERMINAL:
        return "skip"
    if status == "sending":
        return "retry" if retry_ambiguous else "mark_ambiguous"
    if status in {"prepared", "not_sent"}:
        return "retry"
    return "skip"


def _pre_send_connect_failure(record: dict[str, Any]) -> bool:
    """Обрыв до ответа сервера. Попытка списана, счёта нет, пакет не останавливается."""
    if record.get("status") != "http_error" or record.get("http_status") is not None:
        return False
    errors = [str(item) for item in (record.get("errors") or [])]
    return bool(errors) and all(item in {"ConnectTimeout", "ConnectError", "PoolTimeout"} for item in errors)


def _http_attempts(ledger: dict[str, Any]) -> int:
    if ledger.get("http_attempts") is not None:
        return int(ledger["http_attempts"])
    return int(ledger.get("requests") or 0)


def _attempt_room(ledger: dict[str, Any]) -> int | None:
    room = None
    if ledger.get("max_requests") is not None:
        room = max(int(ledger["max_requests"]) - _http_attempts(ledger), 0)
    if ledger.get("shared_attempt_remaining") is not None:
        shared = max(int(ledger["shared_attempt_remaining"]), 0)
        room = shared if room is None else min(room, shared)
    return room


def _load_shared_attempts(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"grants": [], "events": []}
    data = load_json(path)
    data.setdefault("grants", [])
    data.setdefault("events", [])
    return data


def _shared_attempt_remaining(document: dict[str, Any]) -> int:
    """Остаток попыток. Уже записанное превышение не съедает новый пакет."""
    granted = sum(int(item.get("http_attempts") or 0) for item in document.get("grants") or [])
    used = sum(int(item.get("http_attempts") or 0) for item in document.get("events") or [])
    recorded_overrun = int((document.get("totals") or {}).get("overrun_http_attempts") or 0)
    return granted - used + recorded_overrun


def _append_shared_attempt(path: Path | None, document: dict[str, Any], record: dict[str, Any], run_id: str) -> None:
    if path is None:
        return
    sent = int(record.get("attempts") or 0)
    if sent < 1:
        sent = 1
    event = {
        "run_id": run_id,
        "model_id": record.get("model_id"),
        "requested_model": record.get("requested_model"),
        "http_attempts": sent,
        "http_status": record.get("http_status"),
        "status": record.get("status"),
        "cost_usd": record.get("cost_usd"),
        "cost_status": record.get("cost_status"),
        "called_at": record.get("called_at"),
    }
    document.setdefault("events", []).append(event)
    dump_json(path, document)


def _budget_block(ledger: dict[str, Any], job: dict[str, Any], config: dict[str, Any], *, allow_unknown_price: bool) -> str | None:
    if ledger.get("unknown_cost_calls") and not config.get("continue_after_unknown_cost"):
        return "cost_unknown_blocks_further_paid_calls"
    if ledger.get("attempt_budget_exhausted"):
        return "attempt_budget_exhausted"
    requests = _http_attempts(ledger)
    if ledger.get("max_requests") is not None and requests >= int(ledger["max_requests"]):
        return "max_requests"
    max_tokens = int((config.get("generation") or {}).get("max_tokens") or 0)
    if ledger.get("max_output_tokens") is not None and int(ledger.get("output_tokens") or 0) + max_tokens > int(ledger["max_output_tokens"]):
        return "max_output_tokens"
    if job.get("estimate_usd") is None and not allow_unknown_price:
        return "price_unknown"
    if job.get("estimate_usd") is None:
        ledger["budget_is_money_guarantee"] = False
        return None
    reserve = float(job["estimate_usd"]) * (int(config.get("max_retries") or 0) + 1)
    spent = float(ledger.get("spent_usd") or 0) + float(ledger.get("unknown_reserved_usd") or 0)
    if ledger.get("budget_usd") is not None and spent + reserve > float(ledger["budget_usd"]):
        return "budget_usd"
    return None


def _account(ledger: dict[str, Any], job: dict[str, Any], record: dict[str, Any], config: dict[str, Any]) -> None:
    if not job["billed"] or not record.get("invoked"):
        return
    sent = int(record.get("attempts") or 0)
    if sent < 1:
        sent = 1
    ledger["http_attempts"] = _http_attempts(ledger) + sent
    ledger["requests"] = ledger["http_attempts"]
    if record.get("http_status") == 200 and record.get("status") in {"completed", "truncated"}:
        ledger["successful_responses"] = int(ledger.get("successful_responses") or 0) + 1
    usage = record.get("usage") or {}
    completion = usage.get("completion_tokens")
    if isinstance(completion, int):
        ledger["output_tokens"] = int(ledger.get("output_tokens") or 0) + completion
    else:
        ledger["output_tokens"] = int(ledger.get("output_tokens") or 0) + int((config.get("generation") or {}).get("max_tokens") or 0)
        ledger["output_tokens_include_unknown_reserve"] = True
    if record.get("cost_usd") is not None and record.get("cost_status") in {"api", "derived"}:
        ledger["spent_usd"] = round(float(ledger.get("spent_usd") or 0) + float(record["cost_usd"]), 8)


def _prepare_record(job, config, manifest, plan, views_cache, image_dir, label_text, manifest_text) -> dict[str, Any]:
    samples = {item["sample_id"]: item for item in manifest["samples"]}
    if job["_pair"]:
        pair = job["_pair"]
        earlier = _views(samples[pair["earlier"]], config, image_dir, views_cache)
        later = _views(samples[pair["later"]], config, image_dir, views_cache)
        mapping = pair_mapping(earlier, later)
        views = earlier + later
        clock = clock_visible(samples[pair["earlier"]], send_full=True, crop_xyxy=samples[pair["earlier"]]["crop_xyxy"]) or clock_visible(
            samples[pair["later"]], send_full=True, crop_xyxy=samples[pair["later"]]["crop_xyxy"]
        )
    else:
        sample = job["_sample"]
        views = _views(sample, config, image_dir, views_cache)
        mapping = single_mapping(views)
        clock = clock_visible(sample, send_full=True, crop_xyxy=sample["crop_xyxy"])
    template = load_template(config, job["task"])
    prompt = render_prompt(job["task"], job["response_mode"], template, mapping)
    assert_prompt_isolated(prompt, manifest_text=manifest_text, label_text=label_text)
    schema = load_schema(config, job["task"]) if job["response_mode"] == "structured" else None
    route = route_of(job["_model"], structured=job["response_mode"] == "structured")
    generation, omitted_generation = generation_for_model(config, job["_model"])
    preprocessing = preprocessing_of(config)
    key = inference_cache_key(
        image_sha256=[view.payload.sha256 for view in views],
        crops=[view.crop_xyxy for view in views],
        preprocessing=preprocessing,
        prompt_text=prompt,
        requested_model=job["requested_model"],
        route=route,
        generation=generation,
        response_mode=job["response_mode"],
        schema=schema,
    )
    return {
        "record_kind": "provider_result",
        "run_planned_revision": plan["revision"],
        "config_sha256": plan["config_sha256"],
        "sample_id": job["sample_id"],
        "pair_id": job["pair_id"],
        "task": job["task"],
        "response_mode": job["response_mode"],
        "model_id": job["model_id"],
        "cache_key": key,
        "prompt_template": (config.get("prompts") or {}).get(job["task"]),
        "prompt_template_sha256": sha256_file(resolve((config.get("prompts") or {})[job["task"]])),
        "prompt_text": prompt,
        "images": image_meta(views, clock=clock),
        "camera_clock_visible_to_model": clock,
        "clock_stripped": False,
        "requested_model": job["requested_model"],
        "actual_model": "unknown",
        "requested_route": route,
        "actual_provider": "unknown",
        "provider_revision": None,
        "generation_settings": generation,
        "preprocessing": preprocessing,
        "status": "prepared",
        "completed": False,
        "invoked": False,
        "synthetic": job["transport"] == "fixture",
        "usage": {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None},
        "cost_usd": None,
        "cost_status": "unknown",
        "attempts": 0,
        "unsupported_settings": omitted_generation,
        "errors": [],
        "called_at": None,
        "_views": views,
        "_schema": schema,
        "_route": route,
    }


def _views(sample, config, image_dir, cache):
    key = sample["sample_id"]
    if key not in cache:
        cache[key] = prepare_sample_views(sample, config, image_dir)
    return cache[key]


def _dispatch(job, record, clients, config, secrets) -> ProviderRaw:
    transport_name = job["transport"]
    if transport_name not in clients:
        clients[transport_name] = _build_transport(transport_name, job["_model"], config, secrets)
    transport = clients[transport_name]
    if job.get("_attempt_room") is not None and hasattr(transport, "max_http_attempts"):
        transport.max_http_attempts = job["_attempt_room"]
    spec = CallSpec(
        requested_model=job["requested_model"],
        prompt_text=record["prompt_text"],
        images=[view.payload for view in record["_views"]],
        response_mode=job["response_mode"],
        schema=record["_schema"],
        generation=record["generation_settings"],
        route=record["_route"],
        schema_name=job["task"],
    )
    return clients[transport_name].complete(spec)


def _build_transport(name: str, model: dict[str, Any], config: dict[str, Any], secrets: list[str]):
    if name == "fixture":
        return FixtureTransport()
    if name == "openrouter":
        key = secrets[0] if secrets else ""
        return OpenRouterTransport(
            api_key=key,
            max_retries=int(config.get("max_retries") or 0),
            timeout=float(config.get("timeout_seconds") or 180),
        )
    if name == "local_openai":
        return LocalOpenAITransport(
            base_url=str(model.get("base_url") or "http://127.0.0.1:8001/v1"),
            structured_output=str(model.get("structured_output") or "unsupported"),
            provider_routing=str(model.get("provider_routing") or "unsupported"),
            timeout=float(config.get("timeout_seconds") or 180),
        )
    raise ValueError(f"unknown_transport:{name}")


def _apply_raw(record: dict[str, Any], raw: ProviderRaw, job: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    record["status"] = raw.status
    record["completed"] = raw.completed
    record["invoked"] = raw.invoked
    record["raw_text"] = raw.raw_text
    record["http_status"] = raw.http_status
    record["finish_reason"] = raw.finish_reason
    record["native_finish_reason"] = raw.native_finish_reason
    record["actual_model"] = raw.actual_model or "unknown"
    record["actual_provider"] = raw.actual_provider or "unknown"
    record["provider_revision"] = raw.provider_revision
    record["generation_id"] = raw.generation_id
    record["request_id"] = raw.request_id
    record["response_headers"] = dict(raw.response_headers)
    record["usage"] = raw.usage or record["usage"]
    record["cost_usd"] = raw.cost_usd
    record["cost_status"] = raw.cost_status
    record["duration_ms"] = raw.duration_ms
    record["attempts"] = raw.attempts
    record["errors"] = list(raw.errors)
    record["unsupported_settings"] = list(dict.fromkeys(list(record.get("unsupported_settings") or []) + list(raw.unsupported_settings)))
    record["synthetic"] = bool(raw.synthetic or job["transport"] == "fixture")
    record["settings_applied"] = raw.settings_applied
    record["request_provider"] = raw.request_provider
    record["reasoning_text"] = raw.reasoning_text
    record["reproducibility_note"] = raw.reproducibility_note
    record["called_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if record["cost_usd"] is None:
        derived = _derive_cost(record, job, catalog)
        if derived is not None:
            record["cost_usd"] = derived
            record["cost_status"] = "derived"
    record.pop("_views", None)
    record.pop("_schema", None)
    record.pop("_route", None)
    return record


def _derive_cost(record: dict[str, Any], job: dict[str, Any], catalog: dict[str, Any]) -> float | None:
    if job["transport"] != "openrouter":
        return None
    prices = None
    if job.get("price_prompt") is not None and job.get("price_completion") is not None:
        prices = (float(job["price_prompt"]), float(job["price_completion"]))
    if prices is None:
        prices = token_prices(model_index(catalog).get(job["requested_model"]))
    usage = record.get("usage") or {}
    if not prices or usage.get("prompt_tokens") is None or usage.get("completion_tokens") is None:
        return None
    return round(usage["prompt_tokens"] * prices[0] + usage["completion_tokens"] * prices[1], 8)


def _write_call(path: Path, record: dict[str, Any], secrets: list[str]) -> None:
    stored = dict(record)
    stored.pop("_views", None)
    stored.pop("_schema", None)
    stored.pop("_route", None)
    blob = redact_tree(stored, secrets)
    text = str(blob)
    if "base64," in text:
        raise RuntimeError("refusing_to_store_base64_image")
    dump_json(path, blob)


def _load_calls(out_dir: Path) -> list[dict[str, Any]]:
    folder = out_dir / "calls"
    if not folder.is_dir():
        return []
    rows = [load_json(path) for path in sorted(folder.glob("*.json"))]
    return rows


def _ensure_parses(out_dir: Path, calls: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    folder = out_dir / "parsed"
    folder.mkdir(parents=True, exist_ok=True)
    found = {}
    for call in calls:
        key = call["cache_key"]
        path = folder / f"{key}.json"
        current = load_json(path) if path.is_file() else None
        source_status = call.get("status") or ""
        if (
            not current
            or current.get("parser_version") != PARSER_VERSION
            or current.get("validator_version") != VALIDATOR_VERSION
            or current.get("classifier_version") != CLASSIFIER_VERSION
            or current.get("source_status") != source_status
        ):
            current = parse_provider_output(
                task=call["task"],
                response_mode=call["response_mode"],
                provider_status=source_status,
                raw_text=call.get("raw_text"),
            )
            current["cache_key"] = key
            current["source_status"] = source_status
            current["record_kind"] = "parse_result"
            dump_json(path, current)
        found[key] = current
    return found


def default_paths() -> dict[str, Path]:
    return {
        "config": PROJECT_ROOT / "config" / "vlm_compare.yaml",
        "manifest": PROJECT_ROOT / "validation" / "vlm_compare" / "manifest.yaml",
        "labels": PROJECT_ROOT / "validation" / "vlm_compare" / "labels.yaml",
        "catalog": PROJECT_ROOT / "validation" / "vlm_compare" / "openrouter_catalog_snapshot.json",
    }
