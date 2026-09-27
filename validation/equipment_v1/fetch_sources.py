"""Download external images for construction_equipment_v1. Never reads house6."""

from __future__ import annotations

import json
import subprocess
import time
import urllib.parse
from pathlib import Path

ROOT = Path("/home/dimk/my_project/LCT2026/data/external/construction_equipment_v1")
UA = "SkripkaResearch/1.0 (local taxonomy experiment; educational)"

# Category is a search hint, not a ground-truth label.
SOURCES = [
    ("excavator", "Category:Excavators", 80),
    ("bulldozer", "Category:Bulldozers", 80),
    ("loader", "Category:Wheel loaders", 60),
    ("dump_truck", "Category:Dump trucks", 60),
    ("truck", "Category:Flatbed trucks", 50),
    ("tower_crane", "Category:Tower cranes", 70),
    ("mobile_crane", "Category:Mobile cranes", 80),
    ("concrete_pump", "Category:Concrete pumps", 80),
    ("aerial_work_platform", "Category:Aerial work platforms", 60),
    ("concrete_mixer", "Category:Cement mixer trucks", 50),
    ("person", "Category:Construction workers", 40),
    ("negative", "Category:Intermodal containers", 25),
    ("negative", "Category:Portable buildings", 20),
]

SKIP_NAME = (
    "toy", "lego", "model", "diagram", "icon", "map", "drawing", "illustration",
    "svg", "logo", "poster", "stamp", "coin", "painting", "sketch",
)


PROXY = "socks5h://127.0.0.1:1080"


def _curl(url: str, dest: Path | None = None) -> bytes:
    own = dest is None
    target = dest or Path("/tmp/commons_curl_body")
    for attempt in range(2):
        proc = subprocess.run(
            [
                "curl", "-sS", "-L", "--max-time", "60",
                "--proxy", PROXY, "-A", UA,
                "-o", str(target), "-w", "%{http_code}", url,
            ],
            check=False,
            capture_output=True,
        )
        status = proc.stdout.decode().strip()
        if status == "200" and target.exists() and target.stat().st_size > 20:
            data = target.read_bytes() if own else b""
            return data
        if status in {"429", "503"}:
            time.sleep(4)
            continue
        raise RuntimeError(f"curl {status} {url[:90]} {proc.stderr[:180]!r}")
    raise RuntimeError(f"curl gave up {url[:90]}")


def api(params: dict) -> dict:
    params = {"format": "json", **params}
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)
    return json.loads(_curl(url).decode())


def members(category: str, limit: int) -> list[str]:
    titles: list[str] = []
    cont: dict = {}
    while len(titles) < limit * 3:
        data = api({
            "action": "query",
            "list": "categorymembers",
            "cmtitle": category,
            "cmtype": "file",
            "cmlimit": "50",
            **cont,
        })
        batch = data.get("query", {}).get("categorymembers", [])
        for item in batch:
            title = item["title"]
            low = title.lower()
            if not low.endswith((".jpg", ".jpeg", ".png", ".webp")):
                continue
            if any(word in low for word in SKIP_NAME):
                continue
            titles.append(title)
        if "continue" not in data:
            break
        cont = {"cmcontinue": data["continue"]["cmcontinue"]}
        time.sleep(1.0)
    return titles[: limit * 2]


def imageinfo(titles: list[str]) -> list[dict]:
    out = []
    for i in range(0, len(titles), 20):
        chunk = titles[i : i + 20]
        data = api({
            "action": "query",
            "prop": "imageinfo",
            "titles": "|".join(chunk),
            "iiprop": "url|size|mime|extmetadata",
            "iiurlwidth": "1280",
        })
        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            info = (page.get("imageinfo") or [None])[0]
            if not info:
                continue
            if info.get("width", 0) < 480 or info.get("height", 0) < 320:
                continue
            mime = info.get("mime", "")
            if not mime.startswith("image/"):
                continue
            meta = info.get("extmetadata") or {}
            lic = (meta.get("LicenseShortName") or {}).get("value", "")
            out.append({
                "title": page.get("title"),
                "url": info.get("thumburl") or info.get("url"),
                "source_url": info.get("descriptionurl", ""),
                "width": info.get("thumbwidth") or info.get("width"),
                "height": info.get("thumbheight") or info.get("height"),
                "license": lic,
            })
        time.sleep(1.0)
    return out


def download(url: str, dest: Path) -> None:
    _curl(url, dest)


def main() -> None:
    raw = ROOT / "raw"
    manifest = []
    for label, category, limit in SOURCES:
        dest_dir = raw / label
        dest_dir.mkdir(parents=True, exist_ok=True)
        have = [p for p in dest_dir.iterdir() if p.is_file() and p.stat().st_size > 1000]
        if len(have) >= limit:
            print(f"skip {label} already {len(have)}")
            continue
        titles = members(category, limit)
        infos = imageinfo(titles)
        kept = 0
        for info in infos:
            if kept >= limit:
                break
            name = urllib.parse.unquote(info["url"].split("/")[-1].split("?")[0])
            name = name.replace("/", "_")
            if not name.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                name += ".jpg"
            dest = dest_dir / name
            if dest.exists() and dest.stat().st_size > 1000:
                kept += 1
                continue
            try:
                download(info["url"], dest)
            except Exception as exc:  # noqa: BLE001
                print("skip", name, exc)
                continue
            rec = {
                "file": str(dest.relative_to(ROOT)),
                "hint": label,
                "category": category,
                "title": info["title"],
                "source_url": info["source_url"],
                "license": info["license"],
                "width": info["width"],
                "height": info["height"],
            }
            manifest.append(rec)
            kept += 1
            print(f"{label} {kept}/{limit} {name[:60]}")
            time.sleep(0.15)
    path = ROOT / "fetch_manifest.jsonl"
    with path.open("a") as fh:
        for rec in manifest:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("wrote", len(manifest), "new files")


if __name__ == "__main__":
    main()
