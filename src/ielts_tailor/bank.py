from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

import yaml


SKIP_LINES = {
    "待补充",
    "（小问待补充）",
    "(小问待补充)",
}


def import_bank(source_path: str | Path, *, region: str, output_path: str | Path) -> dict[str, Any]:
    source = Path(source_path)
    if source.suffix.lower() == ".pdf":
        text = subprocess.check_output(["pdftotext", "-layout", str(source), "-"], text=True)
    else:
        text = source.read_text(encoding="utf-8")
    return import_bank_text(text, region=region, output_path=output_path)


def import_bank_text(text: str, *, region: str, output_path: str | Path) -> dict[str, Any]:
    if region not in {"mainland", "all"}:
        raise ValueError("region must be 'mainland' or 'all'")

    lines = _clean_lines(text)
    bank: dict[str, Any] = {
        "metadata": {"region_filter": region, "source_format": "text"},
        "part1_topics": [],
        "part2_blocks": [],
    }
    current_region = "mainland"
    mode: str | None = None
    p1_topic: dict[str, Any] | None = None
    p2_block: dict[str, Any] | None = None
    source_order = 0
    p1_question_order = 0
    p3_question_order = 0
    collecting_cues = False
    collecting_p3 = False

    def include_current_region() -> bool:
        return region == "all" or current_region == "mainland"

    def finish_p1_topic() -> None:
        nonlocal p1_topic
        if p1_topic and include_current_region() and p1_topic["questions"]:
            bank["part1_topics"].append(p1_topic)
        p1_topic = None

    def finish_p2_block() -> None:
        nonlocal p2_block
        if p2_block and include_current_region() and p2_block["part2"]["prompt"]:
            bank["part2_blocks"].append(p2_block)
        p2_block = None

    for line in lines:
        if "非大陆地区" in line:
            finish_p1_topic()
            finish_p2_block()
            current_region = "non_mainland"
            mode = None
            continue
        if "大陆地区" in line and "非大陆" not in line:
            finish_p1_topic()
            finish_p2_block()
            current_region = "mainland"
            mode = None
            continue
        if line.startswith("Part 1"):
            finish_p1_topic()
            finish_p2_block()
            mode = "part1"
            continue
        if line.startswith("Part 2&3"):
            finish_p1_topic()
            finish_p2_block()
            mode = "part2"
            continue

        p1_match = re.match(r"^\d+\s+P1\s+(.+)$", line)
        if p1_match and mode == "part1":
            finish_p1_topic()
            source_order += 1
            p1_question_order = 0
            title = p1_match.group(1).strip()
            p1_topic = {
                "id": f"p1_{_slug(title)}",
                "title": title,
                "region": current_region,
                "source_order": source_order,
                "questions": [],
            }
            continue

        p2_match = re.match(r"^\d+\s+P2\s+(.+)$", line)
        if p2_match and mode == "part2":
            finish_p2_block()
            source_order += 1
            p3_question_order = 0
            title_zh = p2_match.group(1).strip()
            p2_block = {
                "id": f"p2_{source_order}",
                "title_zh": title_zh,
                "region": current_region,
                "source_order": source_order,
                "part2": {"prompt": "", "cue_points": []},
                "part3": [],
            }
            collecting_cues = False
            collecting_p3 = False
            continue

        if mode == "part1" and p1_topic and _looks_like_question(line):
            p1_question_order += 1
            p1_topic["questions"].append(
                {
                    "id": f"{p1_topic['id']}_q{p1_question_order}",
                    "question": line,
                    "framework": "A+R/E",
                }
            )
            continue

        if mode != "part2" or not p2_block:
            continue
        if line == "You should say:":
            collecting_cues = True
            collecting_p3 = False
            continue
        if line == "P3":
            collecting_cues = False
            collecting_p3 = True
            continue
        if collecting_p3:
            if _looks_like_question(line):
                p3_question_order += 1
                p2_block["part3"].append(
                    {
                        "id": f"{p2_block['id']}_p3_{p3_question_order}",
                        "question": line,
                    }
                )
            elif p2_block["part3"]:
                p2_block["part3"][-1]["question"] = f"{p2_block['part3'][-1]['question']} {line}".strip()
            continue
        if collecting_cues:
            if line and not line.startswith("And explain"):
                p2_block["part2"]["cue_points"].append(line)
            elif line.startswith("And explain"):
                p2_block["part2"]["cue_points"].append(line)
            continue
        if not p2_block["part2"]["prompt"] and line.startswith("Describe "):
            p2_block["part2"]["prompt"] = line
        elif p2_block["part2"]["prompt"] and not collecting_cues:
            p2_block["part2"]["prompt"] = f"{p2_block['part2']['prompt']} {line}".strip()

    finish_p1_topic()
    finish_p2_block()
    _write_yaml(output_path, bank)
    return bank


def load_question_bank(path: str | Path) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def _clean_lines(text: str) -> list[str]:
    cleaned = []
    for raw in text.replace("\f", "\n").splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line or line in SKIP_LINES:
            continue
        if re.fullmatch(r"\d+", line):
            continue
        if line.startswith("2026 年") or line.startswith("截止"):
            continue
        cleaned.append(line)
    return cleaned


def _looks_like_question(line: str) -> bool:
    return line.endswith("?") or line.endswith("？")


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.lower()).strip("_")
    return slug or f"topic_{abs(hash(value))}"


def _write_yaml(path: str | Path, data: dict[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
