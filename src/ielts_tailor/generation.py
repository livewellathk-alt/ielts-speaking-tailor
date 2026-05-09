from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import yaml

from .strategy import cluster_part2_blocks, sort_blocks_for_study


class LLMClient(Protocol):
    def complete_json(self, *, messages: list[dict[str, str]], schema_name: str, temperature: float) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class TimingConfig:
    part1_seconds: int = 15
    part2_min_seconds: int = 100
    part2_max_seconds: int = 110
    part3_seconds: int = 40


@dataclass(frozen=True)
class GenerationConfig:
    target_band: int
    answer_length: str
    speaking_speed_wpm: int
    output_dir: Path
    timing: TimingConfig = field(default_factory=TimingConfig)
    checkpoint_mode: bool = True
    temperature: float = 0.2


class GenerationPipeline:
    def __init__(self, *, client: LLMClient, config: GenerationConfig, reviewer_client: LLMClient | None = None):
        self.client = client
        self.reviewer_client = reviewer_client or client
        self.config = config
        self.cache_dir = config.output_dir / "cache"
        self.checkpoint_dir = config.output_dir / "checkpoints"

    def run(self, *, bank: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        prepared_bank = self._prepare_bank(bank)
        style_guide = self._style_guide(prepared_bank, profile)
        checkpoint_samples = None
        if self.config.checkpoint_mode:
            checkpoint_samples = self._checkpoint_samples(prepared_bank, profile, style_guide)
        answers = self._answer_batch(prepared_bank, profile, style_guide, checkpoint_samples)
        review = self._quality_review(prepared_bank, profile, style_guide, answers)
        if not review.get("passed", False):
            revised = self._revised_answer_batch(prepared_bank, profile, style_guide, answers, review)
            answers = self._merge_revision(answers, revised)
        answers = self._enrich_answers(prepared_bank, answers)
        payload = {
            "style_guide": style_guide,
            "checkpoint_samples": checkpoint_samples,
            "word_targets": word_targets_for(self.config.speaking_speed_wpm, self.config.timing),
            "answers": answers,
            "review": review,
            "bank": prepared_bank,
        }
        self._write_yaml(self.cache_dir / "generation_result.yaml", payload)
        return payload

    def _prepare_bank(self, bank: dict[str, Any]) -> dict[str, Any]:
        prepared = dict(bank)
        prepared["part2_blocks"] = sort_blocks_for_study(cluster_part2_blocks(bank.get("part2_blocks", [])))
        return prepared

    def _style_guide(self, bank: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
        path = self.cache_dir / "style_guide.yaml"
        if path.exists():
            return yaml.safe_load(path.read_text(encoding="utf-8"))
        result = self._complete_schema(
            self.client,
            messages=self._messages("Create a durable student style guide.", bank, profile),
            schema_name="style_guide",
            temperature=self.config.temperature,
        )
        self._write_yaml(path, result)
        return result

    def _checkpoint_samples(self, bank: dict[str, Any], profile: dict[str, Any], style_guide: dict[str, Any]) -> dict[str, Any]:
        path = self.checkpoint_dir / "samples.yaml"
        if path.exists():
            return yaml.safe_load(path.read_text(encoding="utf-8"))
        result = self._complete_schema(
            self.client,
            messages=self._messages("Generate calibration samples for checkpoint review.", bank, profile, style_guide),
            schema_name="checkpoint_samples",
            temperature=self.config.temperature,
        )
        self._write_yaml(path, result)
        return result

    def _answer_batch(
        self,
        bank: dict[str, Any],
        profile: dict[str, Any],
        style_guide: dict[str, Any],
        checkpoint_samples: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return self._complete_schema(
            self.client,
            messages=self._messages("Generate IELTS speaking answers as strict JSON.", bank, profile, style_guide, checkpoint_samples),
            schema_name="answer_batch",
            temperature=self.config.temperature,
        )

    def _quality_review(
        self,
        bank: dict[str, Any],
        profile: dict[str, Any],
        style_guide: dict[str, Any],
        answers: dict[str, Any],
    ) -> dict[str, Any]:
        return self._complete_schema(
            self.reviewer_client,
            messages=self._messages("Review answer quality against descriptors and frameworks.", bank, profile, style_guide, answers),
            schema_name="quality_review",
            temperature=0.0,
        )

    def _revised_answer_batch(
        self,
        bank: dict[str, Any],
        profile: dict[str, Any],
        style_guide: dict[str, Any],
        answers: dict[str, Any],
        review: dict[str, Any],
    ) -> dict[str, Any]:
        return self._complete_schema(
            self.client,
            messages=self._messages("Revise only the answers flagged by the quality review.", bank, profile, style_guide, answers, review),
            schema_name="revised_answer_batch",
            temperature=self.config.temperature,
        )

    def _messages(self, instruction: str, *payloads: Any) -> list[dict[str, str]]:
        context = {
            "target_band": self.config.target_band,
            "answer_length": self.config.answer_length,
            "speaking_speed_wpm": self.config.speaking_speed_wpm,
            "timing_requirements": {
                "part1_seconds": self.config.timing.part1_seconds,
                "part2_min_seconds": self.config.timing.part2_min_seconds,
                "part2_max_seconds": self.config.timing.part2_max_seconds,
                "part3_seconds": self.config.timing.part3_seconds,
            },
            "word_targets": word_targets_for(self.config.speaking_speed_wpm, self.config.timing),
            "payloads": payloads,
        }
        return [
            {
                "role": "system",
                "content": (
                    "You are an IELTS speaking answer architect. Use first principles: answer only bank questions, "
                    "preserve one student voice, use Part 1 A+R/E, Part 2 umbrella stories, and Part 3 AREA variants. "
                    "Follow the supplied word_targets for spoken answer length. "
                    "Return valid JSON only."
                ),
            },
            {"role": "user", "content": f"{instruction}\n\n{yaml.safe_dump(context, sort_keys=False, allow_unicode=True)}"},
        ]

    def _complete_schema(
        self,
        client: LLMClient,
        *,
        messages: list[dict[str, str]],
        schema_name: str,
        temperature: float,
    ) -> dict[str, Any]:
        last_result: dict[str, Any] | None = None
        for _ in range(3):
            result = client.complete_json(messages=messages, schema_name=schema_name, temperature=temperature)
            last_result = result
            if _schema_is_complete(schema_name, result):
                return result
        raise RuntimeError(f"LLM returned incomplete {schema_name} response: {last_result}")

    def _merge_revision(self, answers: dict[str, Any], revised: dict[str, Any]) -> dict[str, Any]:
        merged = {
            "part1": revised.get("part1") or answers.get("part1", []),
            "part2_blocks": answers.get("part2_blocks", []),
        }
        revised_blocks = {block["block_id"]: block for block in revised.get("part2_blocks", [])}
        merged["part2_blocks"] = [revised_blocks.get(block.get("block_id"), block) for block in merged["part2_blocks"]]
        return merged

    def _enrich_answers(self, bank: dict[str, Any], answers: dict[str, Any]) -> dict[str, Any]:
        p1_questions = {
            question["id"]: question["question"]
            for topic in bank.get("part1_topics", [])
            for question in topic.get("questions", [])
        }
        blocks = {block["id"]: block for block in bank.get("part2_blocks", [])}
        for answer in answers.get("part1", []):
            answer.setdefault("question", p1_questions.get(answer.get("question_id"), ""))
        for block_answer in answers.get("part2_blocks", []):
            source = blocks.get(block_answer.get("block_id"), {})
            block_answer.setdefault("title_zh", source.get("title_zh", ""))
            block_answer.setdefault("part2_prompt", source.get("part2", {}).get("prompt", ""))
            p3_questions = {question["id"]: question for question in source.get("part3", [])}
            for p3_answer in block_answer.get("part3", []):
                source_question = p3_questions.get(p3_answer.get("question_id"), {})
                p3_answer.setdefault("question", source_question.get("question", ""))
                p3_answer.setdefault("framework", source_question.get("framework", "AREA-Alternative"))
        return answers

    def _write_yaml(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


REQUIRED_SCHEMA_KEYS = {
    "style_guide": {
        "student_voice",
        "target_band_rules",
        "preferred_structures",
        "lexical_boundaries",
        "consistency_constraints",
        "story_inventory",
    },
    "checkpoint_samples": {"samples"},
    "answer_batch": {"part1", "part2_blocks"},
    "quality_review": {"passed", "issues", "revision_instructions"},
    "revised_answer_batch": {"part1", "part2_blocks"},
}


def word_targets_for(speaking_speed_wpm: int, timing: TimingConfig) -> dict[str, Any]:
    if speaking_speed_wpm <= 0:
        raise ValueError("speaking_speed_wpm must be greater than 0")
    if timing.part2_max_seconds < timing.part2_min_seconds:
        raise ValueError("part2_max_seconds must be greater than or equal to part2_min_seconds")
    return {
        "part1": {"seconds": timing.part1_seconds, "words": _seconds_to_words(timing.part1_seconds, speaking_speed_wpm)},
        "part2": {
            "min_seconds": timing.part2_min_seconds,
            "max_seconds": timing.part2_max_seconds,
            "min_words": _seconds_to_words(timing.part2_min_seconds, speaking_speed_wpm),
            "max_words": _seconds_to_words(timing.part2_max_seconds, speaking_speed_wpm),
        },
        "part3": {"seconds": timing.part3_seconds, "words": _seconds_to_words(timing.part3_seconds, speaking_speed_wpm)},
    }


def _seconds_to_words(seconds: int, speaking_speed_wpm: int) -> int:
    return round(seconds * speaking_speed_wpm / 60)


def _schema_is_complete(schema_name: str, result: dict[str, Any]) -> bool:
    required = REQUIRED_SCHEMA_KEYS.get(schema_name, set())
    return required.issubset(result.keys())
