from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

import yaml

from .strategy import cluster_part2_blocks, sort_blocks_for_study


class LLMClient(Protocol):
    def complete_json(self, *, messages: list[dict[str, str]], schema_name: str, temperature: float) -> dict[str, Any]:
        ...


ProgressCallback = Callable[[dict[str, Any]], None]


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
    answer_batch_size: int = 8
    max_revision_items: int = 20
    temperature: float = 0.2


class GenerationPipeline:
    def __init__(
        self,
        *,
        client: LLMClient,
        config: GenerationConfig,
        reviewer_client: LLMClient | None = None,
        progress_callback: ProgressCallback | None = None,
    ):
        self.client = client
        self.reviewer_client = reviewer_client or client
        self.config = config
        self.progress_callback = progress_callback
        self.cache_dir = config.output_dir / "cache"
        self.checkpoint_dir = config.output_dir / "checkpoints"

    def run(self, *, bank: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        prepared_bank = self._prepare_bank(bank)
        self._emit(
            "scope_analysis",
            "Analyzed Part 2 prompt scopes and reusable story cards.",
            part2_blocks=len(prepared_bank.get("part2_blocks", [])),
            scope_count=len({block.get("scope_id") for block in prepared_bank.get("part2_blocks", [])}),
        )
        style_guide = self._style_guide(prepared_bank, profile)
        self._emit("style_guide", "Prepared the student style guide.")
        checkpoint_samples = None
        if self.config.checkpoint_mode:
            checkpoint_samples = self._checkpoint_samples(prepared_bank, profile, style_guide)
            self._emit("checkpoint_samples", "Generated checkpoint calibration samples.")
        answers = self._answer_batches(prepared_bank, profile, style_guide, checkpoint_samples)
        self._validate_answer_completeness(prepared_bank, answers)
        review = self._quality_review(prepared_bank, profile, style_guide, answers)
        self._emit("quality_review", "Reviewed answer quality and timing.")
        review["timing_issues"] = _timing_issues(answers, word_targets_for(self.config.speaking_speed_wpm, self.config.timing))
        if not review.get("passed", False):
            revision_bank, revision_answers, revision_ids = _revision_scope(prepared_bank, answers, review)
            if revision_ids and len(revision_ids) <= self.config.max_revision_items:
                try:
                    revised = self._revised_answer_batch(revision_bank, profile, style_guide, revision_answers, review)
                    answers = self._merge_revision(answers, revised)
                    review["revision_status"] = "revised"
                    review["revision_target_ids"] = sorted(revision_ids)
                    self._emit("revision", "Revised answers flagged by quality review.", target_ids=sorted(revision_ids))
                except Exception as exc:
                    review["revision_status"] = "failed_original_answers_kept"
                    review["revision_error"] = str(exc)
            elif _answer_item_count(answers) > self.config.max_revision_items:
                review["revision_status"] = "skipped_large_batch_original_answers_kept"
                review["revision_error"] = f"Skipped revision because answer count exceeded {self.config.max_revision_items} and no small target set was available."
            else:
                try:
                    revised = self._revised_answer_batch(prepared_bank, profile, style_guide, answers, review)
                    answers = self._merge_revision(answers, revised)
                    review["revision_status"] = "revised"
                    self._emit("revision", "Revised answers flagged by quality review.")
                except Exception as exc:
                    review["revision_status"] = "failed_original_answers_kept"
                    review["revision_error"] = str(exc)
            self._validate_answer_completeness(prepared_bank, answers)
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

    def _emit(self, stage: str, message: str, **details: Any) -> None:
        if self.progress_callback:
            self.progress_callback({"stage": stage, "message": message, "details": details})

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
        last_error: RuntimeError | None = None
        for _ in range(3):
            result = self._complete_schema(
                self.client,
                messages=self._messages("Generate IELTS speaking answers as strict JSON.", bank, profile, style_guide, checkpoint_samples),
                schema_name="answer_batch",
                temperature=self.config.temperature,
            )
            result = _filter_answers_to_bank(result, bank)
            try:
                self._validate_answer_completeness(bank, result)
                return result
            except RuntimeError as exc:
                last_error = exc
        raise RuntimeError(f"LLM returned incomplete answer_batch coverage after retries: {last_error}")

    def _answer_batches(
        self,
        bank: dict[str, Any],
        profile: dict[str, Any],
        style_guide: dict[str, Any],
        checkpoint_samples: dict[str, Any] | None,
    ) -> dict[str, Any]:
        blocks = bank.get("part2_blocks", [])
        if len(blocks) <= self.config.answer_batch_size:
            result = self._answer_batch(bank, profile, style_guide, checkpoint_samples)
            self._emit("answer_batch", "Generated answer batch 1/1.", batch_index=1, batch_total=1)
            return result

        part1_result = self._answer_batch(
            _bank_slice(bank, part1_topics=bank.get("part1_topics", []), part2_blocks=[]),
            profile,
            style_guide,
            checkpoint_samples,
        )
        merged = {"part1": part1_result.get("part1", []), "part2_blocks": []}
        batch_total = (len(blocks) + self.config.answer_batch_size - 1) // self.config.answer_batch_size
        for start in range(0, len(blocks), self.config.answer_batch_size):
            chunk = blocks[start : start + self.config.answer_batch_size]
            chunk_result = self._answer_batch(
                _bank_slice(bank, part1_topics=[], part2_blocks=chunk),
                profile,
                style_guide,
                checkpoint_samples,
            )
            merged["part2_blocks"].extend(chunk_result.get("part2_blocks", []))
            batch_index = start // self.config.answer_batch_size + 1
            self._emit(
                "answer_batch",
                f"Generated answer batch {batch_index}/{batch_total}.",
                batch_index=batch_index,
                batch_total=batch_total,
                part2_blocks=[block.get("id") for block in chunk],
            )
        return merged

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
            "part2_scope_cards": _scope_cards_from_payloads(payloads),
            "payloads": payloads,
        }
        return [
            {
                "role": "system",
                "content": (
                    "You are an IELTS speaking answer architect. Use first principles: first identify the real scope "
                    "of each Part 2 cue card, map it to the closest supplied scope card, then decide how to adapt the "
                    "student's reusable material. Answer only bank questions, preserve one student voice, use Part 1 "
                    "A+R/E, Part 2 umbrella stories, and Part 3 AREA variants. IELTS answers may adapt one true story "
                    "across compatible prompts, but must not invent personal facts. The supplied examples are pattern "
                    "inspiration only; do not copy wording from examples verbatim. "
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
        messages = _with_schema_instructions(messages, schema_name)
        for _ in range(3):
            result = _normalize_schema_response(schema_name, client.complete_json(messages=messages, schema_name=schema_name, temperature=temperature))
            last_result = result
            if _schema_is_complete(schema_name, result):
                return result
        raise RuntimeError(f"LLM returned incomplete {schema_name} response: {last_result}")

    def _merge_revision(self, answers: dict[str, Any], revised: dict[str, Any]) -> dict[str, Any]:
        merged = {
            "part1": answers.get("part1", []),
            "part2_blocks": answers.get("part2_blocks", []),
        }
        revised_part1 = {answer["question_id"]: answer for answer in revised.get("part1", []) if answer.get("question_id")}
        if revised_part1:
            merged["part1"] = [revised_part1.get(answer.get("question_id"), answer) for answer in merged["part1"]]
        revised_blocks = {block["block_id"]: block for block in revised.get("part2_blocks", [])}
        merged["part2_blocks"] = [_merge_block_revision(block, revised_blocks.get(block.get("block_id"))) for block in merged["part2_blocks"]]
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

    def _validate_answer_completeness(self, bank: dict[str, Any], answers: dict[str, Any]) -> None:
        expected_part1 = {
            question["id"]: question.get("question", "")
            for topic in bank.get("part1_topics", [])
            for question in topic.get("questions", [])
        }
        expected_blocks = {
            block["id"]: block.get("title_zh") or block.get("part2", {}).get("prompt", "")
            for block in bank.get("part2_blocks", [])
        }
        expected_part3 = {
            question["id"]: question.get("question", "")
            for block in bank.get("part2_blocks", [])
            for question in block.get("part3", [])
        }
        actual_part1 = {answer.get("question_id") for answer in answers.get("part1", [])}
        actual_blocks = {block.get("block_id") for block in answers.get("part2_blocks", [])}
        actual_part3 = {
            answer.get("question_id")
            for block in answers.get("part2_blocks", [])
            for answer in block.get("part3", [])
        }
        missing = [
            *_format_missing("Part 1", expected_part1, actual_part1),
            *_format_missing("Part 2", expected_blocks, actual_blocks),
            *_format_missing("Part 3", expected_part3, actual_part3),
        ]
        unexpected = [
            *_format_unexpected("Part 1", actual_part1, expected_part1),
            *_format_unexpected("Part 2", actual_blocks, expected_blocks),
            *_format_unexpected("Part 3", actual_part3, expected_part3),
        ]
        if missing or unexpected:
            details = []
            if missing:
                details.append(f"Missing generated answers: {'; '.join(missing)}")
            if unexpected:
                details.append(f"Unexpected generated answers: {'; '.join(unexpected)}")
            raise RuntimeError(" ".join(details))

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


SCHEMA_INSTRUCTIONS = {
    "style_guide": (
        "Return exactly these top-level keys: student_voice, target_band_rules, preferred_structures, "
        "lexical_boundaries, consistency_constraints, story_inventory."
    ),
    "checkpoint_samples": "Return exactly this top-level key: samples. samples must be a list.",
    "answer_batch": (
        "Return exactly these top-level keys: part1, part2_blocks. part1 must be a list of objects with "
        "question_id, framework, answer_en, answer_zh, memory_cues. part2_blocks must be a list of objects "
        "with block_id, framework, answer_en, answer_zh, memory_cues, umbrella_story, part3. Each part3 item "
        "must have question_id, framework, answer_en, answer_zh, memory_cues. Include every supplied bank question."
    ),
    "quality_review": "Return exactly these top-level keys: passed, issues, revision_instructions.",
    "revised_answer_batch": (
        "Return exactly these top-level keys: part1, part2_blocks. Include only revised items, but use the same "
        "item field names as answer_batch."
    ),
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


def _scope_cards_from_payloads(payloads: tuple[Any, ...]) -> list[dict[str, Any]]:
    if not payloads or not isinstance(payloads[0], dict):
        return []
    cards: dict[str, dict[str, Any]] = {}
    for block in payloads[0].get("part2_blocks", []):
        scope_id = block.get("scope_id") or block.get("theme")
        if not scope_id:
            continue
        card = cards.setdefault(
            scope_id,
            {
                "scope_id": scope_id,
                "scope_label": block.get("scope_label", scope_id),
                "compatibility_tags": set(),
                "why_reusable": block.get("why_reusable", ""),
                "matched_prompts": [],
            },
        )
        card["compatibility_tags"].update(block.get("compatibility_tags", []))
        card["matched_prompts"].append(
            {
                "block_id": block.get("id", ""),
                "prompt": block.get("part2", {}).get("prompt", ""),
                "cue_points": block.get("part2", {}).get("cue_points", []),
            }
        )
    return [
        {
            **card,
            "compatibility_tags": sorted(card["compatibility_tags"]),
        }
        for card in cards.values()
    ]


def _schema_is_complete(schema_name: str, result: dict[str, Any]) -> bool:
    required = REQUIRED_SCHEMA_KEYS.get(schema_name, set())
    return required.issubset(result.keys())


def _normalize_schema_response(schema_name: str, result: dict[str, Any]) -> dict[str, Any]:
    if schema_name == "style_guide" and "student_style_guide" in result:
        return _normalize_style_guide(result["student_style_guide"])
    if schema_name == "checkpoint_samples" and "samples" not in result and any(key in result for key in ["part1", "part2", "part3"]):
        return {"samples": [result]}
    if schema_name in {"answer_batch", "revised_answer_batch"} and ("part2" in result or isinstance(result.get("part1"), dict)):
        return _normalize_answer_batch(result)
    return result


def _with_schema_instructions(messages: list[dict[str, str]], schema_name: str) -> list[dict[str, str]]:
    instruction = SCHEMA_INSTRUCTIONS.get(schema_name)
    if not instruction or not messages:
        return messages
    adjusted = [dict(message) for message in messages]
    adjusted[-1]["content"] = f"{adjusted[-1]['content']}\n\nJSON schema contract:\n{instruction}"
    return adjusted


def _normalize_style_guide(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    profile = raw.get("student_profile", {}) if isinstance(raw.get("student_profile"), dict) else {}
    stories = raw.get("umbrella_stories", {}) if isinstance(raw.get("umbrella_stories"), dict) else {}
    structures = [
        value.get("structure")
        for key, value in raw.items()
        if key.endswith("_style") and isinstance(value, dict) and value.get("structure")
    ]
    story_inventory = []
    for story_id, story in stories.items():
        story_inventory.append(
            {
                "id": story_id,
                "title": story.get("story", story_id) if isinstance(story, dict) else story_id,
                "themes": [story_id],
                "details": story.get("details", "") if isinstance(story, dict) else "",
            }
        )
    return {
        "student_voice": raw.get("student_voice") or profile.get("name", "clear, personal, and natural"),
        "target_band_rules": raw.get("target_band_rules", []),
        "preferred_structures": raw.get("preferred_structures") or structures,
        "lexical_boundaries": raw.get("lexical_boundaries", []),
        "consistency_constraints": raw.get("consistency_constraints", []),
        "story_inventory": raw.get("story_inventory") or story_inventory,
    }


def _normalize_answer_batch(raw: dict[str, Any]) -> dict[str, Any]:
    flat_part3 = [_normalize_answer_item(item, id_key="question_id", default_framework="AREA-Alternative") for item in raw.get("part3", [])]
    part3_by_block: dict[str, list[dict[str, Any]]] = {}
    for item in flat_part3:
        question_id = item.get("question_id", "")
        block_id = question_id.split("_p3_", 1)[0] if "_p3_" in question_id else ""
        part3_by_block.setdefault(block_id, []).append(item)
    return {
        "part1": [
            _normalize_answer_item(item, id_key="question_id", default_framework="A+R/E")
            for item in _flatten_part1(raw.get("part1", []))
        ],
        "part2_blocks": [
            _normalize_block_answer(item, part3_by_block)
            for item in raw.get("part2_blocks", raw.get("part2", []))
        ],
    }


def _answer_item_count(answers: dict[str, Any]) -> int:
    return len(answers.get("part1", [])) + sum(
        1 + len(block.get("part3", []))
        for block in answers.get("part2_blocks", [])
    )


def _revision_scope(bank: dict[str, Any], answers: dict[str, Any], review: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], set[str]]:
    target_ids = _target_ids_from_review(review)
    if not target_ids:
        return bank, answers, set()
    scoped_bank = _filter_bank_to_targets(bank, target_ids)
    scoped_answers = _filter_answers_to_targets(answers, target_ids)
    return scoped_bank, scoped_answers, target_ids


def _target_ids_from_review(review: dict[str, Any]) -> set[str]:
    timing_ids = _ids_from_text("\n".join(str(item) for item in review.get("timing_issues", [])))
    if timing_ids:
        return timing_ids
    text_parts = []
    for issue in review.get("issues", []):
        if isinstance(issue, dict):
            text_parts.append(str(issue.get("detail", "")))
        else:
            text_parts.append(str(issue))
    text_parts.append(str(review.get("revision_instructions", "")))
    return _ids_from_text("\n".join(text_parts))


def _ids_from_text(text: str) -> set[str]:
    return set(re.findall(r"\b(?:p1_[a-z0-9_]+_q\d+|p2_\d+_p3_\d+|p2_\d+)\b", text, flags=re.IGNORECASE))


def _filter_bank_to_targets(bank: dict[str, Any], target_ids: set[str]) -> dict[str, Any]:
    scoped = dict(bank)
    scoped["part1_topics"] = []
    for topic in bank.get("part1_topics", []):
        questions = [question for question in topic.get("questions", []) if question.get("id") in target_ids]
        if questions:
            scoped_topic = dict(topic)
            scoped_topic["questions"] = questions
            scoped["part1_topics"].append(scoped_topic)
    scoped["part2_blocks"] = []
    for block in bank.get("part2_blocks", []):
        block_id = block.get("id")
        part3 = [question for question in block.get("part3", []) if question.get("id") in target_ids]
        if block_id in target_ids or part3:
            scoped_block = dict(block)
            scoped_block["part3"] = part3
            scoped["part2_blocks"].append(scoped_block)
    return scoped


def _filter_answers_to_targets(answers: dict[str, Any], target_ids: set[str]) -> dict[str, Any]:
    filtered = {
        "part1": [answer for answer in answers.get("part1", []) if answer.get("question_id") in target_ids],
        "part2_blocks": [],
    }
    for block in answers.get("part2_blocks", []):
        block_id = block.get("block_id")
        part3 = [answer for answer in block.get("part3", []) if answer.get("question_id") in target_ids]
        if block_id in target_ids or part3:
            filtered_block = dict(block)
            if block_id not in target_ids:
                filtered_block.pop("answer_en", None)
                filtered_block.pop("answer_zh", None)
                filtered_block.pop("memory_cues", None)
                filtered_block.pop("umbrella_story", None)
                filtered_block.pop("framework", None)
            filtered_block["part3"] = part3
            filtered["part2_blocks"].append(filtered_block)
    return filtered


def _merge_block_revision(original: dict[str, Any], revised: dict[str, Any] | None) -> dict[str, Any]:
    if not revised:
        return original
    merged = dict(original)
    for key, value in revised.items():
        if key not in {"part3", "block_id"} and value not in (None, "", []):
            merged[key] = value
    revised_part3 = {answer["question_id"]: answer for answer in revised.get("part3", []) if answer.get("question_id")}
    if revised_part3:
        merged["part3"] = [revised_part3.get(answer.get("question_id"), answer) for answer in original.get("part3", [])]
    return merged


def _filter_answers_to_bank(answers: dict[str, Any], bank: dict[str, Any]) -> dict[str, Any]:
    expected_part1 = {
        question["id"]
        for topic in bank.get("part1_topics", [])
        for question in topic.get("questions", [])
    }
    expected_blocks = {block["id"] for block in bank.get("part2_blocks", [])}
    expected_part3 = {
        question["id"]
        for block in bank.get("part2_blocks", [])
        for question in block.get("part3", [])
    }
    return {
        "part1": [
            answer
            for answer in answers.get("part1", [])
            if answer.get("question_id") in expected_part1
        ],
        "part2_blocks": [
            {
                **block,
                "part3": [
                    answer
                    for answer in block.get("part3", [])
                    if answer.get("question_id") in expected_part3
                ],
            }
            for block in answers.get("part2_blocks", [])
            if block.get("block_id") in expected_blocks
        ],
    }


def _timing_issues(answers: dict[str, Any], word_targets: dict[str, Any]) -> list[str]:
    issues = []
    part1_target = int(word_targets.get("part1", {}).get("words", 20))
    part1_min = max(1, round(part1_target * 0.6))
    part1_max = round(part1_target * 1.1)
    part2_min = int(word_targets.get("part2", {}).get("min_words", 0))
    part2_max = int(word_targets.get("part2", {}).get("max_words", 9999))
    part3_target = int(word_targets.get("part3", {}).get("words", 53))
    part3_min = max(1, round(part3_target * 0.8))
    part3_max = round(part3_target * 1.15)

    for answer in answers.get("part1", []):
        count = _word_count(answer.get("answer_en", ""))
        if count < part1_min or count > part1_max:
            issues.append(f"Part 1 {answer.get('question_id', '')} has {count} words; target range is {part1_min}-{part1_max}.")
    for block in answers.get("part2_blocks", []):
        count = _word_count(block.get("answer_en", ""))
        if count < part2_min or count > part2_max:
            issues.append(f"Part 2 {block.get('block_id', '')} has {count} words; target range is {part2_min}-{part2_max}.")
        for answer in block.get("part3", []):
            count = _word_count(answer.get("answer_en", ""))
            if count < part3_min or count > part3_max:
                issues.append(f"Part 3 {answer.get('question_id', '')} has {count} words; target range is {part3_min}-{part3_max}.")
    return issues


def _word_count(value: str) -> int:
    return len(re.findall(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)?", value))


def _bank_slice(bank: dict[str, Any], *, part1_topics: list[dict[str, Any]], part2_blocks: list[dict[str, Any]]) -> dict[str, Any]:
    sliced = dict(bank)
    sliced["part1_topics"] = part1_topics
    sliced["part2_blocks"] = part2_blocks
    return sliced


def _flatten_part1(raw_part1: Any) -> list[dict[str, Any]]:
    if isinstance(raw_part1, dict):
        return [item for group in raw_part1.values() if isinstance(group, list) for item in group if isinstance(item, dict)]
    if isinstance(raw_part1, list):
        return [item for item in raw_part1 if isinstance(item, dict)]
    return []


def _normalize_block_answer(raw: dict[str, Any], part3_by_block: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    block_id = raw.get("block_id") or raw.get("id", "")
    nested_part3 = [
        _normalize_answer_item(item, id_key="question_id", default_framework="AREA-Alternative")
        for item in raw.get("part3", [])
        if isinstance(item, dict)
    ]
    return {
        "block_id": block_id,
        "framework": raw.get("framework", "Umbrella Part 2"),
        "answer_en": raw.get("answer_en") or raw.get("answer") or raw.get("english", ""),
        "answer_zh": raw.get("answer_zh") or raw.get("zh") or raw.get("chinese", ""),
        "memory_cues": _normalize_memory_cues(raw.get("memory_cues", [])),
        "umbrella_story": raw.get("umbrella_story", "story_general"),
        "part3": nested_part3 or part3_by_block.get(block_id, []),
    }


def _normalize_answer_item(raw: dict[str, Any], *, id_key: str, default_framework: str) -> dict[str, Any]:
    return {
        id_key: raw.get(id_key) or raw.get("id", ""),
        "framework": raw.get("framework", default_framework),
        "answer_en": raw.get("answer_en") or raw.get("answer") or raw.get("english", ""),
        "answer_zh": raw.get("answer_zh") or raw.get("zh") or raw.get("chinese", ""),
        "memory_cues": _normalize_memory_cues(raw.get("memory_cues", [])),
    }


def _normalize_memory_cues(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        normalized = value
        for separator in ["，", "、", ";", "；", "\n"]:
            normalized = normalized.replace(separator, ",")
        return [item.strip() for item in normalized.split(",") if item.strip()]
    return []


def _format_missing(label: str, expected: dict[str, str], actual: set[Any]) -> list[str]:
    return [f"{label} {item_id}: {expected[item_id]}" for item_id in expected if item_id not in actual]


def _format_unexpected(label: str, actual: set[Any], expected: dict[str, str]) -> list[str]:
    return [f"{label} {item_id}" for item_id in sorted(str(item_id) for item_id in actual if item_id and item_id not in expected)]
