#!/usr/bin/env python3
"""Minimal OpenAI-compatible /v1/chat/completions for Qwen3-VL via transformers.

Use when vLLM + local transformers versions conflict. Same contract as Скрипка (package sitewatch)
QwenVlProvider expects (messages with image_url + optional json_schema).

Example:
  CUDA_VISIBLE_DEVICES=1 /home/dimk/my_project/myenv/bin/python \\
    scripts/qwen_vl_openai_server.py --port 8001 --device cuda:0
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import re
import time
import uuid
from typing import Any

import torch
import uvicorn
from fastapi import FastAPI, HTTPException
from PIL import Image
from pydantic import BaseModel, Field


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Qwen3-VL OpenAI-compatible server")
    p.add_argument("--model", default="Qwen/Qwen3-VL-8B-Instruct")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8001)
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--max-new-tokens", type=int, default=2048)
    p.add_argument("--dtype", default="bfloat16", choices=["bfloat16", "float16", "float32"])
    return p.parse_args()


class ChatMessage(BaseModel):
    role: str
    content: Any


class ChatRequest(BaseModel):
    model: str | None = None
    messages: list[ChatMessage]
    temperature: float = 0.1
    max_tokens: int = 2048
    response_format: dict[str, Any] | None = None


def _dtype(name: str) -> torch.dtype:
    return {"bfloat16": torch.bfloat16, "float16": torch.float16, "float32": torch.float32}[name]


def _decode_image_url(url: str) -> Image.Image:
    if url.startswith("data:"):
        # data:image/jpeg;base64,...
        _, _, payload = url.partition(",")
        raw = base64.b64decode(payload)
        return Image.open(io.BytesIO(raw)).convert("RGB")
    raise ValueError("only data:image URLs supported in this shim")


def _extract_text_and_images(messages: list[ChatMessage]) -> tuple[list[dict[str, Any]], list[Image.Image]]:
    """Build Qwen chat messages + collect PIL images in order."""
    out: list[dict[str, Any]] = []
    images: list[Image.Image] = []
    for msg in messages:
        role = msg.role
        content = msg.content
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        if not isinstance(content, list):
            out.append({"role": role, "content": str(content)})
            continue
        parts: list[dict[str, Any]] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            ptype = part.get("type")
            if ptype == "text":
                parts.append({"type": "text", "text": part.get("text") or ""})
            elif ptype == "image_url":
                url = (part.get("image_url") or {}).get("url") or ""
                images.append(_decode_image_url(url))
                parts.append({"type": "image"})
        out.append({"role": role, "content": parts if parts else ""})
    return out, images


def _force_json_instruction(response_format: dict[str, Any] | None) -> str:
    if not response_format:
        return ""
    if response_format.get("type") != "json_schema":
        return "\nReturn a single JSON object only."
    schema = (response_format.get("json_schema") or {}).get("schema") or {}
    return (
        "\nReturn ONLY one JSON object matching this schema (no markdown):\n"
        + json.dumps(schema, ensure_ascii=False)
    )


def _strip_json(text: str) -> str:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        return fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return text


def build_app(args: argparse.Namespace) -> FastAPI:
    from transformers import AutoModelForImageTextToText, AutoProcessor

    print(f"Loading {args.model} on {args.device} …", flush=True)
    processor = AutoProcessor.from_pretrained(args.model, trust_remote_code=True)
    model = AutoModelForImageTextToText.from_pretrained(
        args.model,
        torch_dtype=_dtype(args.dtype),
        device_map=args.device,
        trust_remote_code=True,
    )
    model.eval()
    print("Model ready.", flush=True)

    app = FastAPI(title="qwen-vl-openai-shim")
    served = args.model

    @app.get("/v1/models")
    def list_models() -> dict[str, Any]:
        return {
            "object": "list",
            "data": [{"id": served, "object": "model", "owned_by": "local"}],
        }

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/chat/completions")
    def chat(req: ChatRequest) -> dict[str, Any]:
        t0 = time.perf_counter()
        try:
            chat_msgs, images = _extract_text_and_images(req.messages)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"bad_messages:{exc}") from exc

        # Append schema instruction to last user text part
        json_hint = _force_json_instruction(req.response_format)
        if json_hint and chat_msgs:
            last = chat_msgs[-1]
            content = last.get("content")
            if isinstance(content, list):
                for part in content:
                    if part.get("type") == "text":
                        part["text"] = (part.get("text") or "") + json_hint
                        break
                else:
                    content.append({"type": "text", "text": json_hint.strip()})
            elif isinstance(content, str):
                last["content"] = content + json_hint

        try:
            prompt = processor.apply_chat_template(
                chat_msgs,
                tokenize=False,
                add_generation_prompt=True,
            )
            inputs = processor(
                text=[prompt],
                images=images or None,
                return_tensors="pt",
                padding=True,
            )
            inputs = {k: v.to(model.device) if hasattr(v, "to") else v for k, v in inputs.items()}
            with torch.inference_mode():
                generated = model.generate(
                    **inputs,
                    max_new_tokens=min(int(req.max_tokens or args.max_new_tokens), args.max_new_tokens),
                    do_sample=float(req.temperature or 0) > 1e-6,
                    temperature=max(float(req.temperature or 0.1), 1e-5),
                )
            # trim prompt tokens
            in_len = inputs["input_ids"].shape[-1]
            out_ids = generated[:, in_len:]
            text = processor.batch_decode(out_ids, skip_special_tokens=True)[0]
            if req.response_format:
                text = _strip_json(text)
                # validate JSON; if broken, wrap error for client
                try:
                    json.loads(text)
                except json.JSONDecodeError:
                    text = json.dumps(
                        {
                            "professional_observation": text[:2000],
                            "limitations": ["vlm_json_parse_failed"],
                            "uncertainties": [],
                            "entities": [],
                        },
                        ensure_ascii=False,
                    )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"generate_failed:{exc}") from exc

        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": req.model or served,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "sitewatch_latency_ms": latency_ms,
        }

    return app


def main() -> None:
    args = _parse_args()
    app = build_app(args)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
