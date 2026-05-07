from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

from .bank import import_bank, load_question_bank
from .generation import GenerationConfig, GenerationPipeline
from .openai_client import OpenAICompatibleClient
from .rendering import render_outputs
from .strategy import cluster_part2_blocks


DEFAULT_CONFIG = {
    "llm": {
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
        "model": "gpt-4.1-mini",
        "reviewer_model": None,
    },
    "generation": {
        "target_band": 7,
        "answer_length": "medium",
        "speaking_speed_wpm": 120,
        "checkpoint_mode": True,
        "region": "mainland",
    },
    "paths": {
        "question_bank": "data/question_bank.yaml",
        "student_profile": "student_profile.yaml",
        "output_dir": "output",
    },
}

DEFAULT_PROFILE = {
    "name": "Student name",
    "current_status": "student or worker",
    "hometown": "City or region",
    "speaking_preferences": {
        "comfort_topics": ["study", "travel", "technology"],
        "avoid_topics": [],
    },
    "stories": [
        {
            "id": "story_city_trip",
            "title": "A memorable city trip",
            "details": "Replace with a real reusable experience.",
            "themes": ["city_travel"],
        }
    ],
    "theme_answers": {},
}

DEFAULT_BAND_DESCRIPTORS = {
    6: {
        "summary": "Speaks at length with some repetition; uses enough vocabulary; mixes simple and complex structures.",
    },
    7: {
        "summary": "Speaks at length without noticeable effort; uses flexible vocabulary and complex structures with some errors.",
    },
    8: {
        "summary": "Speaks fluently with only occasional hesitation; uses idiomatic language and flexible grammar.",
    },
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            return _cmd_init(args)
        if args.command == "import-bank":
            return _cmd_import_bank(args)
        if args.command == "profile-questions":
            return _cmd_profile_questions(args)
        if args.command == "generate":
            return _cmd_generate(args)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    parser.print_help()
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ielts-tailor")
    subparsers = parser.add_subparsers(dest="command")

    init = subparsers.add_parser("init", help="create editable config and profile templates")
    init.add_argument("--root", default=".", help="project root for generated templates")

    import_parser = subparsers.add_parser("import-bank", help="parse a PDF or text bank into normalized YAML")
    import_parser.add_argument("--source", required=True)
    import_parser.add_argument("--region", choices=["mainland", "all"], default="mainland")
    import_parser.add_argument("--output", default="data/question_bank.yaml")

    profile = subparsers.add_parser("profile-questions", help="write a theme-based student questionnaire")
    profile.add_argument("--bank", required=True)
    profile.add_argument("--output", default="student_questionnaire.md")

    generate = subparsers.add_parser("generate", help="generate Markdown and DOCX answer documents")
    generate.add_argument("--config", default="config.yaml")

    return parser


def _cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.root)
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "output").mkdir(parents=True, exist_ok=True)
    _write_yaml(root / "config.yaml", DEFAULT_CONFIG)
    _write_yaml(root / "student_profile.yaml", DEFAULT_PROFILE)
    _write_yaml(root / "band_descriptors.yaml", DEFAULT_BAND_DESCRIPTORS)
    return 0


def _cmd_import_bank(args: argparse.Namespace) -> int:
    import_bank(args.source, region=args.region, output_path=args.output)
    return 0


def _cmd_profile_questions(args: argparse.Namespace) -> int:
    bank = load_question_bank(args.bank)
    clustered = cluster_part2_blocks(bank.get("part2_blocks", []))
    themes = sorted({block.get("theme", "general_experience") for block in clustered})
    lines = [
        "# IELTS Speaking Tailor Profile Questions",
        "",
        "## Core",
        "",
        "- What do you study or do for work?",
        "- Where are you from, and what details can you comfortably repeat in answers?",
        "- Which topics should the system avoid?",
        "",
        "## Theme Questions",
        "",
    ]
    for theme in themes:
        lines.extend(
            [
                f"### {theme}",
                "",
                "- What real personal story could represent this theme?",
                "- What opinion do you naturally hold about this theme?",
                "- Which English words or phrases do you already use comfortably for this theme?",
                "",
            ]
        )
    Path(args.output).write_text("\n".join(lines), encoding="utf-8")
    return 0


def _cmd_generate(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    paths = config["paths"]
    generation = config["generation"]
    llm = config["llm"]
    root = config_path.parent
    bank = load_question_bank(root / paths["question_bank"])
    profile = yaml.safe_load((root / paths["student_profile"]).read_text(encoding="utf-8"))
    client = OpenAICompatibleClient(
        base_url=llm["base_url"],
        api_key_env=llm["api_key_env"],
        model=llm["model"],
    )
    reviewer_client = None
    if llm.get("reviewer_model"):
        reviewer_client = OpenAICompatibleClient(
            base_url=llm["base_url"],
            api_key_env=llm["api_key_env"],
            model=llm["reviewer_model"],
        )
    pipeline_config = GenerationConfig(
        target_band=int(generation["target_band"]),
        answer_length=str(generation["answer_length"]),
        speaking_speed_wpm=int(generation["speaking_speed_wpm"]),
        checkpoint_mode=bool(generation.get("checkpoint_mode", True)),
        output_dir=root / paths["output_dir"],
    )
    result = GenerationPipeline(client=client, reviewer_client=reviewer_client, config=pipeline_config).run(bank=bank, profile=profile)
    render_outputs(result, output_dir=root / paths["output_dir"])
    return 0


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
