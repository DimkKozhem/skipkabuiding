"""Стенд сравнения VLM: запрос, кеш, бюджет, фикстуры. Сеть и рабочая БД не используются."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import httpx
import pytest
import yaml
from PIL import Image

from sitewatch.experiments.vlm_compare.common import PROJECT_ROOT
from sitewatch.experiments.vlm_compare.parse import parse_provider_output, validate_fields
from sitewatch.experiments.vlm_compare.prepare import (
    generation_for_model,
    load_config,
    load_manifest,
    load_template,
    pair_mapping,
    prepare_sample_views,
    render_prompt,
    single_mapping,
)
from sitewatch.experiments.vlm_compare.runner import execute_run, rescore
from sitewatch.experiments.vlm_compare.score import score_calls
from sitewatch.experiments.vlm_compare.transport import (
    CallSpec,
    safe_response_headers,
    ImagePayload,
    OpenRouterTransport,
    classify_completion,
    usage_from_payload,
)

ROOT = PROJECT_ROOT
BANNED = ("Жилой дом, 6 этажей", "6 этажей", "2 этажа", "КСГ", "ExpectedState", "leak_canary", "no_dynamics", "schedule_delay")


def _jpeg(path: Path, color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (40, 30), color).save(path, format="JPEG", quality=80)


def _spec() -> CallSpec:
    image = ImagePayload("img_test", "full_frame", "abc", b"\xff\xd8\xff", 2, 2)
    return CallSpec(
        requested_model="qwen/qwen3-vl-235b-a22b-instruct",
        prompt_text="observe",
        images=[image],
        response_mode="text",
        schema=None,
        generation={"temperature": 0, "max_tokens": 20, "top_p": 1, "seed": 0},
        route={"order": ["deepinfra"], "only": [], "ignore": [], "allow_fallbacks": False},
    )


class _Resp:
    def __init__(self, status: int, payload: dict, headers: dict | None = None):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class _Client:
    def __init__(self, responses):
        self.responses = list(responses)
        self.posts = 0
        self.seen_headers = []
        self.seen_json = []

    def post(self, url, json, headers):  # noqa: A002
        self.posts += 1
        self.seen_headers.append(headers)
        self.seen_json.append(json)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def get(self, *args, **kwargs):
        return _Resp(404, {"error": {"message": "no"}})

    def close(self):
        return None


def _tiny_world(tmp_path: Path, *, modes: list[str] | None = None, models: list[dict] | None = None) -> dict:
    left = tmp_path / "a.jpg"
    right = tmp_path / "b.jpg"
    _jpeg(left, (20, 20, 20))
    _jpeg(right, (200, 10, 10))
    manifest = {
        "protocol_version": "1",
        "samples": [
            {
                "sample_id": "s-a",
                "split": "dev",
                "image": str(left),
                "sha256": "",
                "object_id": "obj",
                "zone_id": "zone",
                "target_region": "целевая область",
                "crop_xyxy": [2, 2, 30, 24],
                "captured_on": None,
                "date_source": "test",
                "date_confidence": "unreliable",
                "usable_for_calendar_delay": False,
                "camera_clock_burned_in": False,
                "stage": "test",
                "applicable_tasks": ["floors", "elements"],
            },
            {
                "sample_id": "s-b",
                "split": "check",
                "image": str(right),
                "sha256": "",
                "object_id": "obj",
                "zone_id": "zone",
                "target_region": "целевая область",
                "crop_xyxy": [2, 2, 30, 24],
                "captured_on": None,
                "date_source": "test",
                "date_confidence": "unreliable",
                "usable_for_calendar_delay": False,
                "camera_clock_burned_in": True,
                "overlay_bbox": [0, 0, 10, 8],
                "stage": "test",
                "applicable_tasks": ["floors"],
            },
        ],
        "pairs": [
            {
                "pair_id": "p-ab",
                "split": "dev",
                "earlier": "s-a",
                "later": "s-b",
                "order": ["s-a", "s-b"],
                "interval_days": None,
                "interval_reliable": False,
                "usable_for_calendar_delay": False,
                "tasks": ["change"],
            }
        ],
    }
    man_path = tmp_path / "manifest.yaml"
    man_path.write_text(yaml.safe_dump(manifest, allow_unicode=True), encoding="utf-8")
    loaded = load_manifest(man_path)
    labels = {
        "author_kind": "agent_preliminary",
        "leak_canary": "Жилой дом, 6 этажей | КСГ planned floors=6 | gold answer 2 этажа",
        "items": [
            {
                "sample_id": "s-b",
                "task": "floors",
                "author": "agent",
                "author_kind": "agent_preliminary",
                "review_status": "preliminary",
                "counts_toward_accuracy": False,
                "value": 2,
                "expected_outcome": "count",
                "notes": "preliminary",
            }
        ],
    }
    labels_path = tmp_path / "labels.yaml"
    labels_path.write_text(yaml.safe_dump(labels, allow_unicode=True), encoding="utf-8")
    model = {
        "id": "fake-a",
        "transport": "fixture",
        "model": "fixture-a",
        "structured_output": "enforced",
        "provider_order": [],
        "allow_fallbacks": False,
    }
    config = {
        "revision": "test",
        "concurrency": 1,
        "max_retries": 1,
        "timeout_seconds": 5,
        "response_modes": modes or ["text"],
        "generation": {"temperature": 0, "max_tokens": 40, "top_p": 1, "seed": 0},
        "preprocessing": {"max_side": 32, "jpeg_quality": 80},
        "estimate": {"prompt_text_tokens": 10, "tokens_per_image": 10},
        "catalog_snapshot": "validation/vlm_compare/openrouter_catalog_snapshot.json",
        "manifest": str(man_path),
        "labels": str(labels_path),
        "prompts": {
            "floors": "config/vlm_compare/prompts/floors_v1.txt",
            "elements": "config/vlm_compare/prompts/elements_v1.txt",
            "works": "config/vlm_compare/prompts/works_v1.txt",
            "change": "config/vlm_compare/prompts/change_v1.txt",
        },
        "schemas": {
            "floors": "config/vlm_compare/schemas/floors_v1.json",
            "elements": "config/vlm_compare/schemas/elements_v1.json",
            "works": "config/vlm_compare/schemas/works_v1.json",
            "change": "config/vlm_compare/schemas/change_v1.json",
        },
        "models": models or [model],
        "_path": str(tmp_path / "vlm_compare.yaml"),
    }
    Path(config["_path"]).write_text("revision: test\n", encoding="utf-8")
    catalog = {
        "fetched_at": "2026-09-26T21:31:53Z",
        "models": [
            {
                "id": "qwen/qwen3-vl-235b-a22b-instruct",
                "input_modalities": ["text", "image"],
                "pricing_usd_per_token": {"prompt": "0.00000021", "completion": "0.0000019"},
            }
        ],
    }
    return {"config": config, "manifest": loaded, "labels": labels_path, "catalog": catalog}


def test_real_manifest_prompts_do_not_contain_answers(tmp_path: Path):
    config = load_config(ROOT / "config" / "vlm_compare.yaml")
    manifest = load_manifest(ROOT / "validation" / "vlm_compare" / "manifest.yaml")
    labels = (ROOT / "validation" / "vlm_compare" / "labels.yaml").read_text(encoding="utf-8")
    assert "Жилой дом, 6 этажей" in labels
    image_dir = tmp_path / "images"
    for sample in manifest["samples"]:
        views = prepare_sample_views(sample, config, image_dir)
        for task in sample["applicable_tasks"]:
            prompt = render_prompt(task, "text", load_template(config, task), single_mapping(views))
            for banned in BANNED:
                assert banned not in prompt
            assert sample["image"] not in prompt
            assert Path(sample["image"]).name not in prompt
            assert "data:image" not in prompt
    pair = manifest["pairs"][0]
    samples = {item["sample_id"]: item for item in manifest["samples"]}
    earlier = prepare_sample_views(samples[pair["earlier"]], config, image_dir)
    later = prepare_sample_views(samples[pair["later"]], config, image_dir)
    prompt = render_prompt("change", "text", load_template(config, "change"), pair_mapping(earlier, later))
    assert len(earlier) + len(later) == 4
    assert "два вида одного кадра" in prompt
    for banned in BANNED:
        assert banned not in prompt


def test_package_does_not_import_product_pipeline():
    root = ROOT / "src" / "sitewatch" / "experiments" / "vlm_compare"
    banned_prefixes = (
        "sitewatch.storage",
        "sitewatch.pipeline",
        "sitewatch.inspector",
        "sitewatch.deviation",
        "sitewatch.works",
        "sitewatch.ksg",
    )
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith(banned_prefixes)


def test_experiment_does_not_create_product_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db = tmp_path / "sitewatch.db"
    monkeypatch.setenv("SITEWATCH_DB_PATH", str(db))
    world = _tiny_world(tmp_path)
    execute_run(
        world["config"],
        world["manifest"],
        world["catalog"],
        out_dir=tmp_path / "run",
        execute=True,
        labels_path=world["labels"],
        secrets=["sk-test-SHOULD-NOT-LEAK"],
    )
    assert not db.exists()
    blob = "\n".join(path.read_text(encoding="utf-8") for path in (tmp_path / "run").rglob("*") if path.suffix in {".json", ".html", ".csv"})
    assert "sk-test-SHOULD-NOT-LEAK" not in blob
    assert "base64," not in blob


def test_change_request_has_four_distinct_views(tmp_path: Path):
    world = _tiny_world(tmp_path)
    execute_run(
        world["config"],
        world["manifest"],
        world["catalog"],
        out_dir=tmp_path / "run",
        execute=True,
        split="dev",
        labels_path=world["labels"],
    )
    calls = list((tmp_path / "run" / "calls").glob("*.json"))
    change = [json.loads(path.read_text(encoding="utf-8")) for path in calls if '"change"' in path.read_text(encoding="utf-8")]
    assert change
    images = change[0]["images"]
    assert [item["role"] for item in images] == ["full_frame", "crop", "full_frame", "crop"]
    assert len({item["sha256"] for item in images}) == 4
    assert "два вида одного кадра" in change[0]["prompt_text"]
    assert change[0]["synthetic"] is True
    assert "FIXTURE" in (change[0].get("raw_text") or "")


def test_unknown_is_not_zero_and_truncated_is_not_complete():
    parsed = parse_provider_output(task="floors", response_mode="text", provider_status="completed", raw_text="count: unknown\nvisibility: none\nrefusal: yes")
    assert parsed["parsed"]["count"] is None
    zero = parse_provider_output(task="floors", response_mode="text", provider_status="completed", raw_text="count: 0\nvisibility: full\nrefusal: no")
    assert zero["parsed"]["count"] == 0
    usage, cost, status = usage_from_payload({})
    assert usage["prompt_tokens"] is None
    assert cost is None
    assert status == "unknown"
    explicit, explicit_cost, explicit_status = usage_from_payload({"prompt_tokens": 0, "cost": 0})
    assert explicit["prompt_tokens"] == 0
    assert explicit_cost == 0
    assert explicit_status == "api"
    status, completed, _, _, _ = classify_completion(
        {"choices": [{"finish_reason": "length", "message": {"content": "count: 2"}}]}
    )
    assert status == "truncated" and completed is False
    skipped = parse_provider_output(task="floors", response_mode="text", provider_status="truncated", raw_text="count: 2")
    assert skipped["parsed"] is None
    assert skipped["outcome"] == "truncated"
    elements = parse_provider_output(
        task="elements",
        response_mode="text",
        provider_status="completed",
        raw_text="window: presence=present; count=unknown; boxes=none\ngrounds: seen",
    )
    item = elements["parsed"]["items"][0]
    assert item["presence"] == "present"
    assert item["count"] is None
    assert item["localization"] == "not_provided"
    broken = classify_completion({"error": {"message": "provider failed"}, "choices": []})
    assert broken[1] is False


def test_cache_key_changes_with_input_but_resume_and_rescore_do_not_recall(tmp_path: Path):
    from sitewatch.experiments.vlm_compare.prepare import inference_cache_key

    base = dict(image_sha256=["a"], crops=[[1, 2, 3, 4]], preprocessing={"max_side": 8}, prompt_text="one", requested_model="m", route={}, generation={"temperature": 0}, response_mode="text", schema=None)
    first = inference_cache_key(**base)
    changed_prompt = dict(base, prompt_text="two")
    changed_image = dict(base, image_sha256=["b"])
    assert first != inference_cache_key(**changed_prompt)
    assert first != inference_cache_key(**changed_image)
    assert first == inference_cache_key(**base)

    world = _tiny_world(tmp_path)
    from sitewatch.experiments.vlm_compare.transport import FixtureTransport

    transport = FixtureTransport()
    out = tmp_path / "run"
    execute_run(world["config"], world["manifest"], world["catalog"], out_dir=out, execute=True, labels_path=world["labels"], transports={"fixture": transport})
    sent = len(transport.calls)
    assert sent > 0
    execute_run(world["config"], world["manifest"], world["catalog"], out_dir=out, execute=True, labels_path=world["labels"], transports={"fixture": transport})
    assert len(transport.calls) == sent
    world["labels"].write_text(
        yaml.safe_dump({"author_kind": "agent_preliminary", "leak_canary": "Жилой дом, 6 этажей", "items": []}, allow_unicode=True),
        encoding="utf-8",
    )
    rescore(out, world["labels"], scorer_version="2")
    assert len(transport.calls) == sent
    world["config"]["generation"]["temperature"] = 0.4
    execute_run(world["config"], world["manifest"], world["catalog"], out_dir=out, execute=True, labels_path=world["labels"], transports={"fixture": transport})
    assert len(transport.calls) > sent


def test_budget_and_retries(tmp_path: Path):
    client = _Client(
        [
            _Resp(429, {"error": {"message": "slow"}}, {"Retry-After": "0"}),
            _Resp(200, {"id": "gen-1", "model": "served-model", "choices": [{"finish_reason": "stop", "native_finish_reason": "stop", "message": {"content": "ok"}}], "usage": {"prompt_tokens": 3, "completion_tokens": 4}}),
        ]
    )
    transport = OpenRouterTransport(api_key="sk-test-SHOULD-NOT-LEAK", client=client, max_retries=1, sleep=lambda _s: None, lookup_generation=False)
    raw = transport.complete(_spec())
    assert client.posts == 2
    assert raw.completed is True
    assert raw.actual_model == "served-model"
    assert raw.actual_provider == "unknown"
    assert raw.cost_usd is None
    assert raw.cost_status == "unknown"
    assert "sk-test-SHOULD-NOT-LEAK" not in json.dumps(raw.errors)

    timeout_client = _Client([httpx.ReadTimeout("read timed out")])
    timeout_transport = OpenRouterTransport(api_key="sk-test-SHOULD-NOT-LEAK", client=timeout_client, max_retries=5, sleep=lambda _s: None, lookup_generation=False)
    ambiguous = timeout_transport.complete(_spec())
    assert timeout_client.posts == 1
    assert ambiguous.status == "ambiguous_after_send"

    forever = _Client([_Resp(429, {"error": {"message": "slow"}}, {"Retry-After": "0"}) for _ in range(5)])
    limited = OpenRouterTransport(api_key="k", client=forever, max_retries=1, sleep=lambda _s: None, lookup_generation=False)
    failed = limited.complete(_spec())
    assert forever.posts == 2
    assert failed.status == "http_error"

    world = _tiny_world(
        tmp_path,
        models=[
            {
                "id": "or-test",
                "transport": "openrouter",
                "model": "qwen/qwen3-vl-235b-a22b-instruct",
                "structured_output": "enforced",
                "provider_order": ["deepinfra/fp8"],
                "provider_only": ["deepinfra/fp8"],
                "allow_fallbacks": False,
            }
        ],
    )
    priced_calls = []

    class _Priced:
        billed = True

        def complete(self, spec: CallSpec):
            priced_calls.append(spec)
            from sitewatch.experiments.vlm_compare.transport import ProviderRaw

            return ProviderRaw(
                status="completed",
                completed=True,
                raw_text="count: unknown\nvisibility: none\nrefusal: yes",
                requested_model=spec.requested_model,
                actual_model="unknown",
                actual_provider="unknown",
                usage={"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
                cost_usd=0.01,
                cost_status="api",
                attempts=1,
            )

    out = tmp_path / "paid"
    execute_run(
        world["config"],
        world["manifest"],
        world["catalog"],
        out_dir=out,
        execute=True,
        budget_usd=5,
        max_requests=1,
        max_output_tokens=1000,
        labels_path=world["labels"],
        transports={"openrouter": _Priced()},
        split="dev",
    )
    assert len(priced_calls) == 1
    statuses = [json.loads(path.read_text(encoding="utf-8"))["status"] for path in (out / "calls").glob("*.json")]
    assert statuses.count("completed") == 1
    assert "not_sent" in statuses or "max_requests" in " ".join(
        json.loads(path.read_text(encoding="utf-8")).get("errors", [""])[0] for path in (out / "calls").glob("*.json")
    )


def test_resume_marks_ambiguous_send_without_retry(tmp_path: Path):
    from sitewatch.experiments.vlm_compare.transport import FixtureTransport

    world = _tiny_world(tmp_path)
    transport = FixtureTransport()
    out = tmp_path / "run"
    execute_run(world["config"], world["manifest"], world["catalog"], out_dir=out, execute=True, labels_path=world["labels"], transports={"fixture": transport}, split="check")
    sent = len(transport.calls)
    call_path = next((out / "calls").glob("*.json"))
    payload = json.loads(call_path.read_text(encoding="utf-8"))
    payload["status"] = "sending"
    call_path.write_text(json.dumps(payload), encoding="utf-8")
    execute_run(world["config"], world["manifest"], world["catalog"], out_dir=out, execute=True, labels_path=world["labels"], transports={"fixture": transport}, split="check")
    assert len(transport.calls) == sent
    updated = json.loads(call_path.read_text(encoding="utf-8"))
    assert updated["status"] == "ambiguous_after_send"


def test_confirmed_metrics_ignore_agent_and_fixture_rows():
    confirmed = {
        "author_kind": "human",
        "items": [
            {"sample_id": "s", "task": "floors", "author_kind": "human", "review_status": "confirmed", "counts_toward_accuracy": True, "value": 2, "expected_outcome": "count"},
            {"sample_id": "empty", "task": "floors", "author_kind": "human", "review_status": "confirmed", "counts_toward_accuracy": True, "value": None, "expected_outcome": "refusal"},
            {"sample_id": "agent", "task": "floors", "author_kind": "agent_preliminary", "review_status": "preliminary", "counts_toward_accuracy": False, "value": 2, "expected_outcome": "count"},
        ],
    }
    calls = [
        {"cache_key": "a", "sample_id": "s", "task": "floors", "status": "completed", "synthetic": False, "duration_ms": 10, "cost_usd": 0.2, "cost_status": "api", "requested_model": "m", "model_id": "m"},
        {"cache_key": "b", "sample_id": "empty", "task": "floors", "status": "completed", "synthetic": False, "duration_ms": 10, "cost_usd": None, "cost_status": "unknown", "requested_model": "m", "model_id": "m"},
        {"cache_key": "c", "sample_id": "agent", "task": "floors", "status": "completed", "synthetic": True, "duration_ms": 1, "cost_usd": None, "cost_status": "unknown", "requested_model": "m", "model_id": "m"},
    ]
    parses = {
        "a": {"outcome": "count", "parse_status": "ok", "parsed": {"count": 4}},
        "b": {"outcome": "count", "parse_status": "ok", "parsed": {"count": 0}},
        "c": {"outcome": "count", "parse_status": "ok", "parsed": {"count": 2}},
    }
    scores = score_calls(calls, parses, confirmed)
    assert scores["accuracy"]["count_support"] == 1
    assert scores["accuracy"]["mae"] == 2
    assert scores["empty_scene_error_rate"] == 1
    assert scores["synthetic_calls_excluded_from_metrics"] == 1


def test_provider_slug_is_serialized_and_empty_order_is_not_sent(tmp_path: Path):
    client = _Client(
        [
            _Resp(
                200,
                {
                    "id": "gen-pin",
                    "model": "qwen/qwen3-vl-235b-a22b-instruct",
                    "choices": [{"finish_reason": "stop", "message": {"content": "{\"count\": null}"}}],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 4, "cost": 0.001},
                },
            )
        ]
    )
    spec = _spec()
    spec.route = {
        "order": ["deepinfra/fp8"],
        "only": ["deepinfra/fp8"],
        "ignore": [],
        "allow_fallbacks": False,
    }
    transport = OpenRouterTransport(api_key="sk-test-SHOULD-NOT-LEAK", client=client, max_retries=0, sleep=lambda _s: None, lookup_generation=False)
    raw = transport.complete(spec)
    body = client.seen_json[0]
    assert body["provider"] == {
        "allow_fallbacks": False,
        "order": ["deepinfra/fp8"],
        "only": ["deepinfra/fp8"],
        "require_parameters": False,
    }
    assert "qwen/qwen3-vl-235b-a22b-instruct" not in body["provider"]["order"]
    assert raw.request_provider == body["provider"]
    assert "sk-test-SHOULD-NOT-LEAK" not in json.dumps(body["provider"])

    world = _tiny_world(
        tmp_path,
        models=[
            {
                "id": "or-test",
                "transport": "openrouter",
                "model": "qwen/qwen3-vl-235b-a22b-instruct",
                "structured_output": "enforced",
                "provider_order": [],
                "provider_only": [],
                "allow_fallbacks": False,
            }
        ],
    )
    calls = []

    class _Gate:
        def complete(self, spec: CallSpec):
            calls.append(spec)
            raise AssertionError("empty provider_order must not be sent")

    out = tmp_path / "unpinned"
    execute_run(
        world["config"],
        world["manifest"],
        world["catalog"],
        out_dir=out,
        execute=True,
        budget_usd=5,
        max_requests=3,
        max_output_tokens=1000,
        labels_path=world["labels"],
        transports={"openrouter": _Gate()},
        split="dev",
    )
    assert calls == []
    errors = []
    for path in (out / "calls").glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["status"] == "not_sent"
        assert payload["invoked"] is False
        errors.extend(payload["errors"])
    assert errors
    assert set(errors) == {"provider_order_empty"}


def test_endpoint_without_seed_does_not_send_seed():
    generation, omitted = generation_for_model(
        {"generation": {"temperature": 0, "max_tokens": 20, "top_p": 1, "seed": 0}},
        {"omit_generation": ["seed"]},
    )
    assert omitted == ["seed"]
    assert generation["seed"] is None
    client = _Client(
        [
            _Resp(
                200,
                {"id": "gen-2", "model": "moonshotai/kimi-k2.6", "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "cost": 0}},
            )
        ]
    )
    spec = _spec()
    spec.requested_model = "moonshotai/kimi-k2.6"
    spec.generation = generation
    spec.route = {"order": ["baidu/fp4"], "only": ["baidu/fp4"], "ignore": [], "allow_fallbacks": False}
    OpenRouterTransport(api_key="k", client=client, max_retries=0, sleep=lambda _s: None, lookup_generation=False).complete(spec)
    body = client.seen_json[0]
    assert "seed" not in body
    assert body["provider"]["only"] == ["baidu/fp4"]
    assert body["provider"]["allow_fallbacks"] is False


def test_retry_stops_when_attempt_room_is_one():
    client = _Client([_Resp(429, {"error": {"message": "slow"}}, {"Retry-After": "0"}) for _ in range(3)])
    transport = OpenRouterTransport(
        api_key="k",
        client=client,
        max_retries=2,
        max_http_attempts=1,
        sleep=lambda _s: None,
        lookup_generation=False,
    )
    raw = transport.complete(_spec())
    assert client.posts == 1
    assert raw.attempts == 1
    assert raw.status == "http_error"


def test_reasoning_controls_only_send_confirmed_enabled_flag():
    client = _Client(
        [
            _Resp(
                200,
                {
                    "id": "gen-r",
                    "model": "moonshotai/kimi-k2.6",
                    "choices": [{"finish_reason": "stop", "message": {"content": "{}", "reasoning": "hidden"}}],
                    "usage": {"prompt_tokens": 2, "completion_tokens": 4, "completion_tokens_details": {"reasoning_tokens": 0}, "cost": 0.01},
                },
            )
        ]
    )
    spec = _spec()
    spec.generation = {"temperature": 0, "max_tokens": 20, "top_p": 1, "seed": None, "reasoning": {"enabled": False, "effort": "none", "max_tokens": 50}}
    raw = OpenRouterTransport(api_key="k", client=client, max_retries=0, sleep=lambda _s: None, lookup_generation=False).complete(spec)
    assert client.seen_json[0]["reasoning"] == {"enabled": False}
    assert raw.usage["reasoning_tokens"] == 0
    assert raw.reasoning_text == "hidden"
    missing, _, status = usage_from_payload({"prompt_tokens": 1, "completion_tokens": 2})
    assert missing["reasoning_tokens"] is None
    assert status == "unknown"


def test_exhausted_attempt_ledger_blocks_another_http_call(tmp_path: Path):
    ledger_path = tmp_path / "attempts.json"
    ledger_path.write_text(
        json.dumps({"grants": [{"id": "old", "http_attempts": 1}], "events": [{"http_attempts": 1, "cost_usd": None, "cost_status": "unknown"}]}),
        encoding="utf-8",
    )
    world = _tiny_world(
        tmp_path,
        models=[
            {
                "id": "or-test",
                "transport": "openrouter",
                "model": "qwen/qwen3-vl-235b-a22b-instruct",
                "structured_output": "enforced",
                "provider_order": ["deepinfra/fp8"],
                "provider_only": ["deepinfra/fp8"],
                "allow_fallbacks": False,
            }
        ],
    )
    world["config"]["attempt_ledger"] = str(ledger_path)
    calls = []

    class _Gate:
        def complete(self, spec: CallSpec):
            calls.append(spec)
            raise AssertionError("exhausted attempt ledger must not send")

    execute_run(
        world["config"],
        world["manifest"],
        world["catalog"],
        out_dir=tmp_path / "blocked",
        execute=True,
        budget_usd=1,
        max_requests=3,
        max_output_tokens=100,
        labels_path=world["labels"],
        transports={"openrouter": _Gate()},
        split="dev",
    )
    assert calls == []
    saved = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert len(saved["events"]) == 1
    assert saved["events"][0]["cost_status"] == "unknown"


def test_floor_count_validation_checks_fields_not_the_number():
    consistent = validate_fields("floors", {"count": 5, "visibility": "full", "grounds": "ряды", "uncertainty": "low", "refusal": False})
    assert consistent == []
    clash = validate_fields("floors", {"count": 5, "visibility": "full", "grounds": "ряды", "uncertainty": "low", "refusal": True})
    assert "refusal_with_count" in clash
    parsed = parse_provider_output(task="floors", response_mode="structured", provider_status="completed", raw_text='{"count": null, "visibility": "none", "grounds": "не видно", "uncertainty": "high", "refusal": false}')
    assert "count_missing_without_refusal" in parsed["field_validation"]


def test_floors_v2_keeps_zero_unknown_and_not_applicable_apart():
    prompt = (ROOT / "config/vlm_compare/prompts/floors_v2.txt").read_text(encoding="utf-8")
    for banned in BANNED:
        assert banned not in prompt
    assert "visible_level_count" in prompt and "total_floor_count" in prompt
    ok = validate_fields(
        "floors",
        {
            "applicability": "applicable",
            "visible_level_count": 2,
            "total_floor_count": 2,
            "base_visibility": "visible",
            "upper_boundary_visibility": "visible",
            "uncertainty_reason": "границы видны",
            "grounds_source": "both",
            "grounds": "основание и верх в кадре",
        },
    )
    assert ok == []
    zero_for_absent = validate_fields(
        "floors",
        {
            "applicability": "not_applicable",
            "visible_level_count": 0,
            "total_floor_count": 0,
            "base_visibility": "not_applicable",
            "upper_boundary_visibility": "not_applicable",
            "uncertainty_reason": "корпуса нет",
            "grounds_source": "both",
            "grounds": "в области нет корпуса",
        },
    )
    assert "not_applicable_must_be_null" in zero_for_absent
    fragment = validate_fields(
        "floors",
        {
            "applicability": "applicable",
            "visible_level_count": 3,
            "total_floor_count": 5,
            "base_visibility": "visible",
            "upper_boundary_visibility": "partial",
            "uncertainty_reason": "верх срезан",
            "grounds_source": "crop",
            "grounds": "виден только фрагмент",
        },
    )
    assert "total_without_both_boundaries" in fragment
    parsed = parse_provider_output(
        task="floors",
        response_mode="structured",
        provider_status="completed",
        raw_text='{"applicability":"not_applicable","visible_level_count":null,"total_floor_count":null,"base_visibility":"not_applicable","upper_boundary_visibility":"not_applicable","uncertainty_reason":"нет корпуса","grounds_source":"both","grounds":"площадка"}',
    )
    assert parsed["outcome"] == "diagnostic"
    assert "count" not in parsed["parsed"]
    assert parsed["field_validation"] == []
    definite = validate_fields(
        "floors",
        {
            "applicability": "applicable",
            "visible_level_count": 3,
            "total_floor_count": 3,
            "base_visibility": "visible",
            "upper_boundary_visibility": "visible",
            "uncertainty_reason": "",
            "grounds_source": "full_frame",
            "grounds": "основание и верх видны",
        },
    )
    assert definite == []
    missing_reason = validate_fields(
        "floors",
        {
            "applicability": "not_applicable",
            "visible_level_count": None,
            "total_floor_count": None,
            "base_visibility": "not_applicable",
            "upper_boundary_visibility": "not_applicable",
            "uncertainty_reason": "",
            "grounds_source": "both",
            "grounds": "корпуса нет",
        },
    )
    assert "uncertainty_reason_required" in missing_reason
    readable_gap = validate_fields(
        "floors",
        {
            "applicability": "applicable",
            "visible_level_count": 5,
            "total_floor_count": None,
            "base_visibility": "visible",
            "upper_boundary_visibility": "visible",
            "uncertainty_reason": "блик мешает прочитать промежуточные уровни",
            "grounds_source": "full_frame",
            "grounds": "края корпуса в кадре",
        },
    )
    assert readable_gap == []
    v3 = (ROOT / "config/vlm_compare/prompts/floors_v3.txt").read_text(encoding="utf-8")
    for banned in BANNED:
        assert banned not in v3
    assert "строящийся объект" not in v3
    assert "завершённый вид не делает подсчёт неприменимым" in v3
    followed = parse_provider_output(
        task="floors",
        response_mode="structured",
        provider_status="completed",
        raw_text='{"applicability":"not_applicable","visible_level_count":null,"total_floor_count":null,"base_visibility":"not_applicable","upper_boundary_visibility":"not_applicable","uncertainty_reason":"видны только готовые здания","grounds_source":"full_frame","grounds":"только завершённые здания"}',
    )
    assert followed["result_kind"] == "task_spec_defect"
    assert followed["field_validation"] == []
    headers = safe_response_headers(
        {
            "Authorization": "Bearer secret",
            "Set-Cookie": "sid=1",
            "X-Request-Id": "req-1",
            "X-Api-Key": "hidden",
            "Content-Type": "application/json",
        }
    )
    assert headers.get("x-request-id") == "req-1"
    assert "authorization" not in headers
    assert "set-cookie" not in headers
    assert "x-api-key" not in headers


def test_paid_execute_without_budget_is_refused(tmp_path: Path):
    world = _tiny_world(
        tmp_path,
        models=[
            {
                "id": "or-test",
                "transport": "openrouter",
                "model": "qwen/qwen3-vl-235b-a22b-instruct",
                "structured_output": "enforced",
                "provider_order": [],
                "allow_fallbacks": False,
            }
        ],
    )
    with pytest.raises(RuntimeError, match="paid_run_requires_budget"):
        execute_run(world["config"], world["manifest"], world["catalog"], out_dir=tmp_path / "no", execute=True, labels_path=world["labels"])
