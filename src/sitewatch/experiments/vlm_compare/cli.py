"""CLI стенда. Без --execute изображения не отправляются."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

from sitewatch.experiments.vlm_compare.catalog import load_catalog, refresh_catalog
from sitewatch.experiments.vlm_compare.common import PROJECT_ROOT, dump_json
from sitewatch.experiments.vlm_compare.prepare import load_config, load_manifest, resolve
from sitewatch.experiments.vlm_compare.runner import default_paths, execute_run, rebuild_report, rescore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sitewatch vlm-compare")
    sub = parser.add_subparsers(dest="cmd", required=True)
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--config", default=None)
    parent.add_argument("--manifest", default=None)
    parent.add_argument("--labels", default=None)
    parent.add_argument("--catalog", default=None)
    parent.add_argument("--split", choices=["dev", "check"])
    parent.add_argument("--samples", default=None, help="sample_id или pair_id через запятую")
    parent.add_argument("--tasks", default=None, help="floors,elements,works,change")
    parent.add_argument("--modes", default=None, help="text,structured")
    parent.add_argument("--models", default=None, help="id через запятую, например or-kimi-k2.6,local-qwen3-vl-8b")

    sub.add_parser("plan", parents=[parent], help="Показать план. Изображения не отправляются.")
    run = sub.add_parser("run", parents=[parent], help="План или запуск. По умолчанию только план.")
    run.add_argument("--execute", action="store_true")
    run.add_argument("--transport", choices=["fixture"], default=None, help="fixture — тестовый транспорт без сети и без оплаты")
    run.add_argument("--budget-usd", type=float, default=None)
    run.add_argument("--max-requests", type=int, default=None)
    run.add_argument("--max-output-tokens", type=int, default=None)
    run.add_argument("--allow-unknown-price", action="store_true")
    run.add_argument("--out", default=None)
    resume = sub.add_parser("resume", parents=[parent], help="Продолжить каталог прогона, не повторяя завершённые вызовы.")
    resume.add_argument("--run-dir", required=True)
    resume.add_argument("--execute", action="store_true")
    resume.add_argument("--retry-ambiguous", action="store_true")
    resume.add_argument("--transport", choices=["fixture"], default=None)
    resume.add_argument("--budget-usd", type=float, default=None)
    resume.add_argument("--max-requests", type=int, default=None)
    resume.add_argument("--max-output-tokens", type=int, default=None)
    resume.add_argument("--allow-unknown-price", action="store_true")
    score = sub.add_parser("score", parents=[parent], help="Пересчитать оценку без инференса.")
    score.add_argument("--run-dir", required=True)
    score.add_argument("--scorer-version", default=None)
    report = sub.add_parser("report", parents=[parent], help="Пересобрать HTML/JSON/CSV без инференса.")
    report.add_argument("--run-dir", required=True)
    catalog = sub.add_parser("catalog", help="Обновить публичный снимок каталога OpenRouter.")
    catalog.add_argument("--out", default=None)

    args = parser.parse_args(argv)
    paths = default_paths()
    if args.cmd == "catalog":
        config = load_config(paths["config"])
        dest = Path(args.out) if args.out else paths["catalog"]
        snapshot = refresh_catalog([model["model"] for model in config["models"] if model.get("transport") == "openrouter"], dest)
        print(json.dumps({"fetched_at": snapshot["fetched_at"], "models": [item["id"] for item in snapshot["models"]], "missing": snapshot["missing"]}, ensure_ascii=False, indent=2))
        return 0
    config = load_config(Path(args.config) if args.config else paths["config"])
    manifest = load_manifest(Path(args.manifest) if args.manifest else resolve(config["manifest"]))
    labels = Path(args.labels) if args.labels else resolve(config["labels"])
    catalog_path = Path(args.catalog) if args.catalog else resolve(config["catalog_snapshot"])
    catalog_data = load_catalog(catalog_path)
    model_ids = {item.strip() for item in args.models.split(",") if item.strip()} if args.models else None
    sample_ids = {item.strip() for item in args.samples.split(",") if item.strip()} if args.samples else None
    task_ids = {item.strip() for item in args.tasks.split(",") if item.strip()} if args.tasks else None
    mode_ids = {item.strip() for item in args.modes.split(",") if item.strip()} if args.modes else None
    key = os.environ.get(str(config.get("api_key_env") or "OPENROUTER_API_KEY"), "")
    secrets = [key] if key else []
    if args.cmd == "plan":
        state = execute_run(
            config,
            manifest,
            catalog_data,
            out_dir=PROJECT_ROOT / "artifacts" / "vlm_compare" / "plan-unused",
            execute=False,
            model_ids=model_ids,
            split=args.split,
            sample_ids=sample_ids,
            tasks=task_ids,
            response_modes=mode_ids,
            secrets=secrets,
            labels_path=labels,
        )
        _print_plan(state)
        return 0
    if args.cmd == "score":
        version = args.scorer_version or "2"
        scores = rescore(Path(args.run_dir), labels, scorer_version=version, secrets=secrets)
        print(json.dumps({key: scores[key] for key in scores if key != "comparisons"}, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "report":
        rebuild_report(Path(args.run_dir), manifest, labels, secrets)
        print(str(Path(args.run_dir) / "report.html"))
        return 0
    execute = bool(args.execute)
    out = Path(args.out) if getattr(args, "out", None) else None
    if args.cmd == "resume":
        out = Path(args.run_dir)
    elif execute and out is None:
        from datetime import datetime, timezone

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out = PROJECT_ROOT / "artifacts" / "vlm_compare" / "runs" / f"vc-{stamp}"
    elif out is None:
        out = PROJECT_ROOT / "artifacts" / "vlm_compare" / "plan-unused"
    try:
        state = execute_run(
            config,
            manifest,
            catalog_data,
            out_dir=out,
            execute=execute,
            budget_usd=args.budget_usd,
            max_requests=args.max_requests,
            max_output_tokens=args.max_output_tokens,
            allow_unknown_price=args.allow_unknown_price,
            retry_ambiguous=bool(getattr(args, "retry_ambiguous", False)),
            transport_override=args.transport,
            model_ids=model_ids,
            split=args.split,
            sample_ids=sample_ids,
            tasks=task_ids,
            response_modes=mode_ids,
            secrets=secrets,
            labels_path=labels,
        )
    except RuntimeError as exc:
        if str(exc) == "paid_run_requires_budget_request_and_token_caps":
            print(
                "Платный запуск требует --execute вместе с --budget-usd, --max-requests и --max-output-tokens.",
                file=sys.stderr,
            )
            return 2
        raise
    if not execute:
        _print_plan(state)
        return 0
    print(json.dumps({"run_id": state.get("run_id"), "report": state.get("report"), "calls": state.get("calls"), "ledger": state.get("ledger")}, ensure_ascii=False, indent=2))
    return 0


def _print_plan(plan: dict) -> None:
    by_model = Counter(job["model_id"] for job in plan["jobs"])
    by_task = Counter(job["task"] for job in plan["jobs"])
    summary = {
        "images_sent": False,
        "samples": plan["samples"],
        "pairs": plan["pairs"],
        "source_images": plan["source_images"],
        "calls": plan["calls"],
        "billable_calls": plan["billable_calls"],
        "skipped_unsupported": plan["skipped_unsupported"],
        "sent_images": plan["sent_images"],
        "calls_by_model": dict(by_model),
        "calls_by_task": dict(by_task),
        "generation": plan["generation"],
        "max_retries": plan["max_retries"],
        "concurrency": plan["concurrency"],
        "estimate_usd": plan["estimate_usd"],
        "catalog_fetched_at": plan["catalog_fetched_at"],
        "models": plan["models"],
        "limitations": plan["limitations"],
        "config_sha256": plan["config_sha256"],
        "revision": plan["revision"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def write_plan_file(plan: dict, path: Path) -> None:
    public = {key: value for key, value in plan.items() if key != "_jobs"}
    dump_json(path, public)
