from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

from .bank import import_bank, load_question_bank
from .generation import GenerationConfig, GenerationPipeline, TimingConfig
from .openai_client import OpenAICompatibleClient
from .questionnaire import build_profile_questionnaire_markdown
from .rendering import render_outputs
from .web import run_web_server


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
        "speaking_speed_wpm": 80,
        "answer_batch_size": 8,
        "max_revision_items": 20,
        "timing": {
            "part1_seconds": 15,
            "part2_min_seconds": 100,
            "part2_max_seconds": 110,
            "part3_seconds": 40,
        },
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
        if args.command == "web":
            return _cmd_web(args)
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
    generate.add_argument("--wpm", type=int, help="override speaking speed in words per minute for this run")
    generate.add_argument("--part1-seconds", type=int, help="override target Part 1 answer length in seconds")
    generate.add_argument("--part2-min-seconds", type=int, help="override minimum Part 2 answer length in seconds")
    generate.add_argument("--part2-max-seconds", type=int, help="override maximum Part 2 answer length in seconds")
    generate.add_argument("--part3-seconds", type=int, help="override target Part 3 answer length in seconds")

    web = subparsers.add_parser("web", help="open a local browser interface")
    web.add_argument("--config", default="config.yaml")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8765)
    web.add_argument("--no-open", action="store_true", help="start the server without opening a browser")

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
    Path(args.output).write_text(build_profile_questionnaire_markdown(bank), encoding="utf-8")
    return 0


def _cmd_generate(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    paths = config["paths"]
    generation = config["generation"]
    llm = config["llm"]
    timing = dict(generation.get("timing", {}))
    if args.wpm is not None:
        generation["speaking_speed_wpm"] = args.wpm
    if args.part1_seconds is not None:
        timing["part1_seconds"] = args.part1_seconds
    if args.part2_min_seconds is not None:
        timing["part2_min_seconds"] = args.part2_min_seconds
    if args.part2_max_seconds is not None:
        timing["part2_max_seconds"] = args.part2_max_seconds
    if args.part3_seconds is not None:
        timing["part3_seconds"] = args.part3_seconds
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
        timing=TimingConfig(
            part1_seconds=int(timing.get("part1_seconds", 15)),
            part2_min_seconds=int(timing.get("part2_min_seconds", 100)),
            part2_max_seconds=int(timing.get("part2_max_seconds", 110)),
            part3_seconds=int(timing.get("part3_seconds", 40)),
        ),
        checkpoint_mode=bool(generation.get("checkpoint_mode", True)),
        answer_batch_size=int(generation.get("answer_batch_size", 8)),
        max_revision_items=int(generation.get("max_revision_items", 20)),
        output_dir=root / paths["output_dir"],
    )
    result = GenerationPipeline(client=client, reviewer_client=reviewer_client, config=pipeline_config).run(bank=bank, profile=profile)
    render_outputs(result, output_dir=root / paths["output_dir"])
    return 0


def _cmd_web(args: argparse.Namespace) -> int:
    run_web_server(config_path=args.config, host=args.host, port=args.port, open_browser=not args.no_open)
    return 0


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
