"""Проверка публичных источников кандидатов. Не скачивает веса и не вызывает inference."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import httpx

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "validation" / "model_selection" / "source_evidence.json"

HF = [
    "Qwen/Qwen3-VL-8B-Instruct",
    "Qwen/Qwen3-VL-235B-A22B-Instruct",
    "Qwen/Qwen3.5-397B-A17B",
    "moonshotai/Kimi-K2.6",
    "OpenGVLab/InternVL3_5-14B",
    "OpenGVLab/InternVL3_5-8B",
    "OpenGVLab/InternVL3_5-241B-A28B",
    "allenai/MolmoPoint-8B",
    "allenai/Molmo2-8B",
    "facebook/sam3.1",
    "IDEA-Research/grounding-dino-base",
]
HF_SEARCH = [
    "InternVL3_5-8B",
    "ProgressLM",
    "FloorLevel",
    "CountGD",
    "YOLOE",
]
GITHUB = [
    "QwenLM/Qwen3-VL",
    "QwenLM/Qwen3.5",
    "QwenLM/Qwen3",
    "OpenGVLab/InternVL",
    "wumengyangok/FloorLevelNet",
    "allenai/molmo",
    "allenai/molmo2",
    "niki-amini-naieni/CountGD",
    "niki-amini-naieni/CountGDPlusPlus",
    "bbvisual/CountEx",
    "THU-MIG/yoloe",
    "moonshotai/Kimi-K2",
    "facebookresearch/sam3",
    "IDEA-Research/GroundingDINO",
]
ARXIV = [
    "2511.21631",
    "2602.02276",
    "2508.18265",
    "2107.02462",
    "2603.28069",
    "2407.04619",
    "2602.19432",
    "2503.07465",
    "2601.10611",
    "2601.15224",
    "2605.11863",
    "2603.10978",
    "2607.05859",
    "2412.16108",
]
PAGES = [
    "https://openrouter.ai/qwen/qwen3-vl-235b-a22b-instruct",
    "https://openrouter.ai/qwen/qwen3.5-397b-a17b",
    "https://openrouter.ai/moonshotai/kimi-k2.6",
    "https://huggingface.co/collections/Raymond-Qiancx/progresslm",
    "https://github.com/wumengyangok/FloorLevelNet",
    "https://github.com/QwenLM/Qwen3-VL",
    "https://github.com/allenai/molmo2",
    "https://github.com/bbvisual/CountEx",
    "https://github.com/THU-MIG/yoloe",
    "https://github.com/niki-amini-naieni/CountGD",
    "https://github.com/niki-amini-naieni/CountGDPlusPlus",
]
OR_IDS = [
    "qwen/qwen3-vl-8b-instruct",
    "qwen/qwen3-vl-235b-a22b-instruct",
    "qwen/qwen3.5-397b-a17b",
    "moonshotai/kimi-k2.6",
    "opengvlab/internvl3.5-8b",
    "opengvlab/internvl3_5-8b",
    "opengvlab/internvl3.5-14b",
    "opengvlab/internvl3_5-14b",
    "opengvlab/internvl3.5-241b-a28b",
    "openrouter/internvl3.5-241b",
]


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get(client: httpx.Client, url: str, *, accept: str | None = None) -> dict:
    headers = {"User-Agent": "sitewatch-source-check"}
    if accept:
        headers["Accept"] = accept
    try:
        response = client.get(url, headers=headers, follow_redirects=True)
    except Exception as exc:  # noqa: BLE001
        return {"url": url, "error": type(exc).__name__, "detail": str(exc)[:300]}
    text = response.text or ""
    return {
        "url": url,
        "status": response.status_code,
        "final_url": str(response.url),
        "content_type": response.headers.get("content-type"),
        "bytes": len(response.content),
        "text_head": text[:4000],
        "text": text,
    }


def hf_summary(payload: dict) -> dict:
    siblings = payload.get("siblings") or []
    names = [item.get("rfilename") for item in siblings if isinstance(item, dict)]
    weights = [name for name in names if name and re.search(r"\.(safetensors|bin|pt|pth|gguf|onnx)$", name, re.I)]
    card = payload.get("cardData") or {}
    return {
        "id": payload.get("id"),
        "sha": payload.get("sha"),
        "private": payload.get("private"),
        "gated": payload.get("gated"),
        "disabled": payload.get("disabled"),
        "pipeline_tag": payload.get("pipeline_tag"),
        "library_name": payload.get("library_name"),
        "tags": payload.get("tags"),
        "license_tag": next((tag.split(":", 1)[1] for tag in (payload.get("tags") or []) if str(tag).startswith("license:")), None),
        "card_license": card.get("license") if isinstance(card, dict) else None,
        "card_base_model": card.get("base_model") if isinstance(card, dict) else None,
        "downloads": payload.get("downloads"),
        "last_modified": payload.get("lastModified"),
        "weight_files": weights[:40],
        "weight_file_count": len(weights),
        "sibling_count": len(names),
    }


def main() -> None:
    evidence: dict = {"checked_at": now(), "hf": {}, "hf_missing": {}, "hf_search": {}, "github": {}, "arxiv": {}, "pages": {}, "openrouter": {}}
    with httpx.Client(timeout=45) as client:
        catalog = get(client, "https://openrouter.ai/api/v1/models")
        if catalog.get("status") == 200:
            try:
                data = json.loads(catalog["text"])
            except Exception as exc:  # noqa: BLE001
                evidence["openrouter_error"] = str(exc)
                data = {}
            models = data.get("data") if isinstance(data, dict) else []
            wanted = {item.lower() for item in OR_IDS}
            needles = ("internvl", "molmo", "qwen3-vl", "qwen3.5", "kimi-k2", "countgd", "yoloe", "progresslm")
            matched = []
            for row in models or []:
                mid = str(row.get("id") or "")
                low = mid.lower()
                if low in wanted or any(needle in low for needle in needles):
                    arch = row.get("architecture") or {}
                    matched.append(
                        {
                            "id": mid,
                            "input_modalities": arch.get("input_modalities"),
                            "output_modalities": arch.get("output_modalities"),
                            "pricing": row.get("pricing"),
                            "context_length": row.get("context_length"),
                            "supported_parameters": row.get("supported_parameters"),
                        }
                    )
            evidence["openrouter"] = {
                "fetched_at": now(),
                "source": "https://openrouter.ai/api/v1/models",
                "catalog_count": len(models or []),
                "matched": matched,
            }
        else:
            evidence["openrouter"] = {"error": catalog}

        for repo in HF:
            url = f"https://huggingface.co/api/models/{quote(repo)}"
            raw = get(client, url)
            item = {"request": {k: raw.get(k) for k in ("url", "status", "final_url", "error", "detail")}}
            if raw.get("status") == 200:
                try:
                    item["summary"] = hf_summary(json.loads(raw["text"]))
                except Exception as exc:  # noqa: BLE001
                    item["parse_error"] = str(exc)
            else:
                evidence["hf_missing"][repo] = item["request"]
            evidence["hf"][repo] = item

        for query in HF_SEARCH:
            url = f"https://huggingface.co/api/models?search={quote(query)}&limit=8"
            raw = get(client, url)
            ids = []
            if raw.get("status") == 200:
                try:
                    payload = json.loads(raw["text"])
                    ids = [row.get("id") for row in payload if isinstance(row, dict)]
                except Exception as exc:  # noqa: BLE001
                    ids = [f"parse_error:{exc}"]
            evidence["hf_search"][query] = {"status": raw.get("status"), "ids": ids, "error": raw.get("error")}

        for repo in GITHUB:
            url = f"https://api.github.com/repos/{repo}"
            raw = get(client, url, accept="application/vnd.github+json")
            item = {"status": raw.get("status"), "final_url": raw.get("final_url"), "error": raw.get("error")}
            if raw.get("status") == 200:
                body = json.loads(raw["text"])
                license_info = body.get("license") or {}
                item.update(
                    {
                        "full_name": body.get("full_name"),
                        "html_url": body.get("html_url"),
                        "default_branch": body.get("default_branch"),
                        "pushed_at": body.get("pushed_at"),
                        "license_spdx": license_info.get("spdx_id"),
                        "license_url": license_info.get("url"),
                        "archived": body.get("archived"),
                        "description": body.get("description"),
                    }
                )
                readme_url = f"https://raw.githubusercontent.com/{repo}/{body.get('default_branch')}/README.md"
                readme = get(client, readme_url)
                item["readme"] = {
                    "url": readme_url,
                    "status": readme.get("status"),
                    "final_url": readme.get("final_url"),
                    "text_head": (readme.get("text_head") or "")[:3500],
                }
            evidence["github"][repo] = item

        for arxiv_id in ARXIV:
            url = f"https://export.arxiv.org/api/query?id_list={arxiv_id}"
            raw = get(client, url)
            title = published = comment = None
            if raw.get("status") == 200:
                text = raw["text"]
                title_m = re.search(r"<title>(.*?)</title>", text, re.S)
                titles = re.findall(r"<title>(.*?)</title>", text, re.S)
                published_m = re.search(r"<published>(.*?)</published>", text)
                comment_m = re.search(r"<arxiv:comment[^>]*>(.*?)</arxiv:comment>", text, re.S)
                title = titles[-1].strip().replace("\n", " ") if len(titles) > 1 else (titles[0].strip() if titles else None)
                published = published_m.group(1) if published_m else None
                comment = re.sub(r"\s+", " ", comment_m.group(1)).strip() if comment_m else None
                _ = title_m
            evidence["arxiv"][arxiv_id] = {
                "url": f"https://arxiv.org/abs/{arxiv_id}",
                "api": url,
                "status": raw.get("status"),
                "title": title,
                "published": published,
                "comment": comment,
                "error": raw.get("error"),
            }

        for page in PAGES:
            raw = get(client, page)
            evidence["pages"][page] = {k: raw.get(k) for k in ("status", "final_url", "content_type", "error", "detail")}

    def strip_text(node):
        if isinstance(node, dict):
            return {key: strip_text(value) for key, value in node.items() if key != "text"}
        if isinstance(node, list):
            return [strip_text(value) for value in node]
        return node

    OUT.write_text(json.dumps(strip_text(evidence), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"wrote": str(OUT), "hf": len(evidence["hf"]), "github": len(evidence["github"]), "arxiv": len(evidence["arxiv"]), "openrouter_matched": len(evidence.get("openrouter", {}).get("matched") or [])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
