from pathlib import Path

import pytest
import yaml

from ielts_tailor.generation import GenerationConfig, GenerationPipeline, TimingConfig, word_targets_for


class FakeLLMClient:
    def __init__(self):
        self.calls = []

    def complete_json(self, *, messages, schema_name, temperature):
        self.calls.append({"schema_name": schema_name, "messages": messages, "temperature": temperature})
        if schema_name == "style_guide":
            return {
                "student_voice": "clear, personal, and moderately academic",
                "target_band_rules": ["use flexible vocabulary", "avoid memorised phrasing"],
                "preferred_structures": ["A+R/E", "AREA"],
                "lexical_boundaries": ["natural idioms only"],
                "consistency_constraints": ["reuse the same hometown details"],
                "story_inventory": [{"id": "story_city_trip", "title": "A useful city trip", "themes": ["city", "travel"]}],
            }
        if schema_name == "checkpoint_samples":
            return {"samples": [{"theme": "city", "answer": "Sample city answer", "approved": False}]}
        if schema_name == "answer_batch":
            return {
                "part1": [
                    {
                        "question_id": "p1_music_q1",
                        "framework": "A+R",
                        "answer_en": "Yes, I prefer happy music because it lifts my mood before class and helps me focus.",
                        "answer_zh": "是的，我更喜欢快乐的音乐，因为它能改善我的心情。",
                        "memory_cues": ["happy music", "mood"],
                    }
                ],
                "part2_blocks": [
                    {
                        "block_id": "p2_1",
                        "framework": "Umbrella Part 2",
                        "answer_en": " ".join(f"story{i}" for i in range(133)),
                        "answer_zh": "我会讲一次城市旅行，它让我理解了城市生活。",
                        "memory_cues": ["city trip", "urban life"],
                        "umbrella_story": "story_city_trip",
                        "part3": [
                            {
                                "question_id": "p2_1_p3_1",
                                "framework": "AREA-Alternative",
                                "answer_en": "Answer: " + " ".join(f"reason{i}" for i in range(41)),
                                "answer_zh": "人们选择城市主要是为了便利，例如交通和餐饮选择。",
                                "memory_cues": ["convenience", "transport"],
                            }
                        ],
                    }
                ],
            }
        if schema_name == "quality_review":
            return {
                "passed": False,
                "issues": ["Part 3 needs clearer AREA labelling"],
                "revision_instructions": "Make the reasoning more explicit while keeping the same personal details.",
            }
        if schema_name == "revised_answer_batch":
            return {
                "part1": [],
                "part2_blocks": [
                    {
                        "block_id": "p2_1",
                        "framework": "Umbrella Part 2",
                        "answer_en": " ".join(f"revisedstory{i}" for i in range(133)),
                        "answer_zh": "我会讲一次城市旅行，它让我理解了城市生活。",
                        "memory_cues": ["city trip", "urban life"],
                        "umbrella_story": "story_city_trip",
                        "part3": [
                            {
                                "question_id": "p2_1_p3_1",
                                "framework": "AREA-Alternative",
                                "answer_en": "Answer: " + " ".join(f"revisedreason{i}" for i in range(41)),
                                "answer_zh": "答案：便利很重要。原因：城市节省时间。例子：地铁系统让出行更容易。替代观点：有些人仍然喜欢安静的小镇。",
                                "memory_cues": ["convenience", "metro", "quiet towns"],
                            }
                        ],
                    }
                ],
            }
        raise AssertionError(schema_name)


def small_bank():
    return {
        "metadata": {"region_filter": "mainland"},
        "part1_topics": [
            {
                "id": "p1_music",
                "title": "Music",
                "questions": [{"id": "p1_music_q1", "question": "Do you prefer sad or happy music?"}],
            }
        ],
        "part2_blocks": [
            {
                "id": "p2_1",
                "title_zh": "去过的最喜欢的城市",
                "part2": {"prompt": "Describe your favorite city that you have visited", "cue_points": ["Where it is"]},
                "part3": [{"id": "p2_1_p3_1", "question": "How do people choose a city to travel to?"}],
                "source_order": 1,
            }
        ],
    }


def two_block_bank():
    bank = small_bank()
    bank["part2_blocks"].append(
        {
            "id": "p2_2",
            "title_zh": "有用的软件",
            "part2": {"prompt": "Describe an app or website you often use", "cue_points": ["What it is"]},
            "part3": [{"id": "p2_2_p3_1", "question": "How has technology changed people's lives?"}],
            "source_order": 2,
        }
    )
    return bank


def multi_block_bank(count=5):
    bank = small_bank()
    bank["part2_blocks"] = []
    for index in range(1, count + 1):
        bank["part2_blocks"].append(
            {
                "id": f"p2_{index}",
                "title_zh": f"题块 {index}",
                "part2": {"prompt": f"Describe useful experience {index}", "cue_points": ["What it is"]},
                "part3": [{"id": f"p2_{index}_p3_1", "question": f"Why is experience {index} useful?"}],
                "source_order": index,
            }
        )
    return bank


def two_part1_question_bank():
    bank = small_bank()
    bank["part1_topics"][0]["questions"].append(
        {"id": "p1_music_q2", "question": "When do you listen to music?", "framework": "A+R/E"}
    )
    return bank


def test_generation_pipeline_creates_style_checkpoint_review_revision_and_cache(tmp_path: Path):
    client = FakeLLMClient()
    config = GenerationConfig(
        target_band=7,
        answer_length="medium",
        speaking_speed_wpm=80,
        checkpoint_mode=True,
        output_dir=tmp_path,
    )
    profile = {"name": "Alex", "hometown": "Hong Kong", "stories": [{"id": "city_trip", "detail": "visited Tokyo"}]}

    result = GenerationPipeline(client=client, config=config).run(bank=small_bank(), profile=profile)

    assert (tmp_path / "cache" / "style_guide.yaml").exists()
    assert (tmp_path / "checkpoints" / "samples.yaml").exists()
    assert result["word_targets"]["part1"]["words"] == 20
    assert result["word_targets"]["part2"]["min_words"] == 133
    assert result["word_targets"]["part2"]["max_words"] == 147
    assert result["word_targets"]["part3"]["words"] == 53
    assert result["review"]["passed"] is False
    assert result["answers"]["part2_blocks"][0]["part3"][0]["framework"] == "AREA-Alternative"
    assert result["answers"]["part2_blocks"][0]["part3"][0]["answer_en"].startswith("Answer:")
    assert [call["schema_name"] for call in client.calls] == [
        "checkpoint_samples",
        "answer_batch",
        "quality_review",
        "revised_answer_batch",
    ]
    assert all(call["temperature"] <= 0.3 for call in client.calls)

    style = yaml.safe_load((tmp_path / "cache" / "style_guide.yaml").read_text())
    assert set(style) == {
        "student_voice",
        "target_band_rules",
        "preferred_structures",
        "lexical_boundaries",
        "consistency_constraints",
        "story_inventory",
    }
    assert "Alex" in style["student_voice"]
    assert style["story_inventory"][0]["id"] == "city_trip"


def test_word_targets_use_speaking_speed_and_timing_requirements():
    targets = word_targets_for(
        80,
        TimingConfig(
            part1_seconds=15,
            part2_min_seconds=100,
            part2_max_seconds=110,
            part3_seconds=40,
        ),
    )

    assert targets == {
        "part1": {"seconds": 15, "words": 20},
        "part2": {"min_seconds": 100, "max_seconds": 110, "min_words": 133, "max_words": 147},
        "part3": {"seconds": 40, "words": 53},
    }


def test_generation_messages_include_word_targets(tmp_path: Path):
    client = FakeLLMClient()
    config = GenerationConfig(
        target_band=7,
        answer_length="timed",
        speaking_speed_wpm=80,
        timing=TimingConfig(),
        checkpoint_mode=False,
        output_dir=tmp_path,
    )

    GenerationPipeline(client=client, config=config).run(bank=small_bank(), profile={"name": "Alex"})

    message_content = client.calls[0]["messages"][1]["content"]
    system_content = client.calls[0]["messages"][0]["content"]
    assert "word_targets:" in message_content
    assert "part1:" in message_content
    assert "words: 20" in message_content
    assert "min_words: 133" in message_content
    assert "max_words: 147" in message_content
    assert "part3:" in message_content
    assert "Collect once from Part 2 scope cards" in system_content
    assert "write Part 2 first, then Part 3, then Part 1" in system_content


class MinimalValidClient(FakeLLMClient):
    pass


class ReviewerOnlyClient(FakeLLMClient):
    pass


def test_generation_pipeline_routes_quality_review_to_separate_reviewer(tmp_path: Path):
    generator = MinimalValidClient()
    reviewer = ReviewerOnlyClient()
    config = GenerationConfig(
        target_band=7,
        answer_length="medium",
        speaking_speed_wpm=80,
        checkpoint_mode=False,
        output_dir=tmp_path,
    )

    GenerationPipeline(client=generator, reviewer_client=reviewer, config=config).run(bank=small_bank(), profile={"name": "Alex"})

    assert [call["schema_name"] for call in generator.calls] == [
        "answer_batch",
        "revised_answer_batch",
    ]
    assert [call["schema_name"] for call in reviewer.calls] == ["quality_review"]


def test_generation_pipeline_regenerates_local_style_guide_from_profile_changes(tmp_path: Path):
    client = FakeLLMClient()
    config = GenerationConfig(
        target_band=7,
        answer_length="medium",
        speaking_speed_wpm=80,
        checkpoint_mode=False,
        output_dir=tmp_path,
    )

    GenerationPipeline(client=client, config=config).run(
        bank=small_bank(),
        profile={"name": "Alex", "stories": [{"id": "old_story", "title": "Old story"}]},
    )
    first_style = yaml.safe_load((tmp_path / "cache" / "style_guide.yaml").read_text())

    GenerationPipeline(client=client, config=config).run(
        bank=small_bank(),
        profile={"name": "Maya", "stories": [{"id": "new_story", "title": "New story"}]},
    )
    second_style = yaml.safe_load((tmp_path / "cache" / "style_guide.yaml").read_text())

    assert first_style["student_voice"] != second_style["student_voice"]
    assert "Maya" in second_style["student_voice"]
    assert second_style["story_inventory"][0]["id"] == "new_story"
    assert "style_guide" not in [call["schema_name"] for call in client.calls]


def test_generation_pipeline_builds_local_style_guide_from_browser_response_stories(tmp_path: Path):
    client = FakeLLMClient()
    config = GenerationConfig(
        target_band=6.5,
        answer_length="medium",
        speaking_speed_wpm=80,
        checkpoint_mode=False,
        output_dir=tmp_path,
    )
    profile = {
        "name": "Alex",
        "current_status": "student",
        "hometown": "Hong Kong",
        "speaking_preferences": {
            "comfort_topics": ["study apps", "travel"],
            "avoid_topics": ["Do not mention gaming."],
        },
        "stories": [
            {
                "id": "response_scope_places_visited_place",
                "title": "Tokyo trip",
                "details": "metro, ramen, clean streets",
                "themes": ["scope_places_visited_place"],
            }
        ],
    }

    result = GenerationPipeline(client=client, config=config).run(bank=small_bank(), profile=profile)

    assert "Alex" in result["style_guide"]["student_voice"]
    assert any("6.5" in rule for rule in result["style_guide"]["target_band_rules"])
    assert "study apps" in result["style_guide"]["lexical_boundaries"]
    assert "Do not mention gaming." in result["style_guide"]["consistency_constraints"]
    assert result["style_guide"]["story_inventory"][0]["id"] == "response_scope_places_visited_place"


class DirectCheckpointSamplesClient(FakeLLMClient):
    def complete_json(self, *, messages, schema_name, temperature):
        if schema_name == "checkpoint_samples":
            self.calls.append({"schema_name": schema_name, "messages": messages, "temperature": temperature})
            return {
                "part1": [{"id": "p1_music_q1", "answer": "Happy music helps me focus."}],
                "part2": [{"id": "p2_1", "answer": "I would describe Tokyo."}],
                "part3": [{"id": "p2_1_p3_1", "answer": "People choose cities for convenience."}],
            }
        return super().complete_json(messages=messages, schema_name=schema_name, temperature=temperature)


def test_generation_pipeline_wraps_direct_checkpoint_outputs_as_samples(tmp_path: Path):
    client = DirectCheckpointSamplesClient()
    config = GenerationConfig(
        target_band=7,
        answer_length="medium",
        speaking_speed_wpm=80,
        checkpoint_mode=True,
        output_dir=tmp_path,
    )

    result = GenerationPipeline(client=client, config=config).run(bank=small_bank(), profile={"name": "Alex"})

    assert result["checkpoint_samples"]["samples"][0]["part1"][0]["id"] == "p1_music_q1"


class FlatAnswerBatchClient(FakeLLMClient):
    def complete_json(self, *, messages, schema_name, temperature):
        if schema_name == "answer_batch":
            self.calls.append({"schema_name": schema_name, "messages": messages, "temperature": temperature})
            return {
                "part1": {
                    "p1_music": [
                        {"id": "p1_music_q1", "answer": "I prefer happy music because it lifts my mood before every morning lecture."},
                    ]
                },
                "part2": [
                    {
                        "id": "p2_1",
                        "answer": " ".join(f"flatstory{i}" for i in range(133)),
                    }
                ],
                "part3": [
                    {
                        "id": "p2_1_p3_1",
                        "answer": " ".join(f"flatreason{i}" for i in range(42)),
                    }
                ],
            }
        return super().complete_json(messages=messages, schema_name=schema_name, temperature=temperature)


def test_generation_pipeline_normalizes_flat_answer_batches(tmp_path: Path):
    client = FlatAnswerBatchClient()
    config = GenerationConfig(
        target_band=7,
        answer_length="medium",
        speaking_speed_wpm=80,
        checkpoint_mode=False,
        output_dir=tmp_path,
    )

    result = GenerationPipeline(client=client, config=config).run(bank=small_bank(), profile={"name": "Alex"})

    assert result["answers"]["part1"][0]["question_id"] == "p1_music_q1"
    assert result["answers"]["part1"][0]["answer_en"].startswith("I prefer happy")
    assert result["answers"]["part2_blocks"][0]["block_id"] == "p2_1"
    assert result["answers"]["part2_blocks"][0]["part3"][0]["question_id"] == "p2_1_p3_1"


class FlakyIncompleteAnswerClient(FakeLLMClient):
    def complete_json(self, *, messages, schema_name, temperature):
        if schema_name == "answer_batch" and not any(call["schema_name"] == "answer_batch" for call in self.calls):
            result = super().complete_json(messages=messages, schema_name=schema_name, temperature=temperature)
            result["part2_blocks"][0]["part3"] = []
            return result
        return super().complete_json(messages=messages, schema_name=schema_name, temperature=temperature)


def test_generation_pipeline_retries_answer_batches_missing_required_questions(tmp_path: Path):
    client = FlakyIncompleteAnswerClient()
    config = GenerationConfig(
        target_band=7,
        answer_length="medium",
        speaking_speed_wpm=80,
        checkpoint_mode=False,
        output_dir=tmp_path,
    )

    result = GenerationPipeline(client=client, config=config).run(bank=small_bank(), profile={"name": "Alex"})

    assert result["answers"]["part2_blocks"][0]["part3"][0]["question_id"] == "p2_1_p3_1"
    assert [call["schema_name"] for call in client.calls].count("answer_batch") == 2


class ShortThenTimedAnswerClient(FakeLLMClient):
    def complete_json(self, *, messages, schema_name, temperature):
        if schema_name == "quality_review":
            self.calls.append({"schema_name": schema_name, "messages": messages, "temperature": temperature})
            return {"passed": True, "issues": [], "revision_instructions": ""}
        if schema_name == "answer_batch":
            previous_answer_calls = [call for call in self.calls if call["schema_name"] == "answer_batch"]
            result = super().complete_json(messages=messages, schema_name=schema_name, temperature=temperature)
            if not previous_answer_calls:
                result["part2_blocks"][0]["answer_en"] = "I would describe Tokyo because it was convenient and memorable."
                return result
            result["part1"][0]["answer_en"] = "I prefer happy music because it helps me feel energetic before morning lectures every day."
            result["part2_blocks"][0]["answer_en"] = " ".join(f"word{i}" for i in range(133))
            result["part2_blocks"][0]["part3"][0]["answer_en"] = " ".join(f"reason{i}" for i in range(42))
            return result
        return super().complete_json(messages=messages, schema_name=schema_name, temperature=temperature)


def test_generation_pipeline_records_answer_timing_issues(tmp_path: Path):
    client = FakeLLMClient()
    config = GenerationConfig(
        target_band=7,
        answer_length="medium",
        speaking_speed_wpm=80,
        checkpoint_mode=False,
        output_dir=tmp_path,
    )

    result = GenerationPipeline(client=client, config=config).run(bank=small_bank(), profile={"name": "Alex"})

    assert result["review"]["timing_issues"] == []


class BankAwareClient(FakeLLMClient):
    def complete_json(self, *, messages, schema_name, temperature):
        if schema_name != "answer_batch":
            return super().complete_json(messages=messages, schema_name=schema_name, temperature=temperature)
        self.calls.append({"schema_name": schema_name, "messages": messages, "temperature": temperature})
        context = yaml.safe_load(messages[1]["content"].split("\n\n", 1)[1])
        bank = context["payloads"][0]
        return {
            "part1": [
                {
                    "question_id": question["id"],
                    "framework": "A+R/E",
                    "answer_en": " ".join(["answer"] * 12),
                    "answer_zh": f"{question['id']} 的答案",
                    "memory_cues": ["answer"],
                }
                for topic in bank.get("part1_topics", [])
                for question in topic.get("questions", [])
            ],
            "part2_blocks": [
                {
                    "block_id": block["id"],
                    "framework": "Umbrella Part 2",
                    "answer_en": " ".join(["story"] * 133),
                    "answer_zh": f"{block['id']} 的答案",
                    "memory_cues": ["story"],
                    "umbrella_story": "story_general",
                    "part3": [
                        {
                            "question_id": question["id"],
                            "framework": question.get("framework", "AREA-Alternative"),
                            "answer_en": " ".join(["reason"] * 42),
                            "answer_zh": f"{question['id']} 的答案",
                            "memory_cues": ["part3"],
                        }
                        for question in block.get("part3", [])
                    ],
                }
                for block in bank.get("part2_blocks", [])
            ],
        }


def test_generation_pipeline_splits_large_answer_batches_and_merges_results(tmp_path: Path):
    client = BankAwareClient()
    config = GenerationConfig(
        target_band=7,
        answer_length="medium",
        speaking_speed_wpm=80,
        checkpoint_mode=False,
        answer_batch_size=2,
        output_dir=tmp_path,
    )

    result = GenerationPipeline(client=client, config=config).run(bank=multi_block_bank(5), profile={"name": "Alex"})

    answer_calls = [call for call in client.calls if call["schema_name"] == "answer_batch"]
    assert len(answer_calls) == 4
    assert len(result["answers"]["part1"]) == 1
    assert [block["block_id"] for block in result["answers"]["part2_blocks"]] == ["p2_1", "p2_2", "p2_3", "p2_4", "p2_5"]


def test_generation_pipeline_rejects_incomplete_answer_batches(tmp_path: Path):
    client = FakeLLMClient()
    config = GenerationConfig(
        target_band=7,
        answer_length="medium",
        speaking_speed_wpm=80,
        checkpoint_mode=False,
        output_dir=tmp_path,
    )

    with pytest.raises(RuntimeError, match="Missing generated answers.*p2_2.*p2_2_p3_1"):
        GenerationPipeline(client=client, config=config).run(bank=two_block_bank(), profile={"name": "Alex"})


class PartialPart1RevisionClient(FakeLLMClient):
    def complete_json(self, *, messages, schema_name, temperature):
        if schema_name == "answer_batch":
            result = super().complete_json(messages=messages, schema_name=schema_name, temperature=temperature)
            result["part1"].append(
                {
                    "question_id": "p1_music_q2",
                    "framework": "A+R/E",
                    "answer_en": "I usually listen to music in the evening while walking home after class.",
                    "answer_zh": "我通常晚上走路回家时听音乐。",
                    "memory_cues": ["evening", "walking home"],
                }
            )
            return result
        if schema_name == "revised_answer_batch":
            return {
                "part1": [
                    {
                        "question_id": "p1_music_q1",
                        "framework": "A+R/E",
                        "answer_en": "Yes, I prefer happy music because it gives me energy before class every morning.",
                        "answer_zh": "是的，我更喜欢快乐的音乐，因为它让我上课前更有精神。",
                        "memory_cues": ["happy music", "energy"],
                    }
                ],
                "part2_blocks": [],
            }
        return super().complete_json(messages=messages, schema_name=schema_name, temperature=temperature)


def test_generation_pipeline_merges_partial_part1_revisions_by_question_id(tmp_path: Path):
    client = PartialPart1RevisionClient()
    config = GenerationConfig(
        target_band=7,
        answer_length="medium",
        speaking_speed_wpm=80,
        checkpoint_mode=False,
        output_dir=tmp_path,
    )

    result = GenerationPipeline(client=client, config=config).run(bank=two_part1_question_bank(), profile={"name": "Alex"})

    part1_by_id = {answer["question_id"]: answer for answer in result["answers"]["part1"]}
    assert part1_by_id["p1_music_q1"]["answer_en"].endswith("every morning.")
    assert part1_by_id["p1_music_q2"]["answer_en"].startswith("I usually listen")


class FailingRevisionClient(FakeLLMClient):
    def complete_json(self, *, messages, schema_name, temperature):
        if schema_name == "revised_answer_batch":
            raise RuntimeError("The read operation timed out")
        return super().complete_json(messages=messages, schema_name=schema_name, temperature=temperature)


def test_generation_pipeline_keeps_complete_answers_when_revision_fails(tmp_path: Path):
    client = FailingRevisionClient()
    config = GenerationConfig(
        target_band=7,
        answer_length="medium",
        speaking_speed_wpm=80,
        checkpoint_mode=False,
        output_dir=tmp_path,
    )

    result = GenerationPipeline(client=client, config=config).run(bank=small_bank(), profile={"name": "Alex"})

    assert result["review"]["passed"] is False
    assert result["review"]["revision_status"] == "failed_original_answers_kept"
    assert "timed out" in result["review"]["revision_error"]
    assert result["answers"]["part1"][0]["question_id"] == "p1_music_q1"
    assert result["answers"]["part2_blocks"][0]["block_id"] == "p2_1"


class PartialPart3RevisionClient(BankAwareClient):
    def complete_json(self, *, messages, schema_name, temperature):
        if schema_name == "quality_review":
            self.calls.append({"schema_name": schema_name, "messages": messages, "temperature": temperature})
            return {
                "passed": False,
                "issues": ["Part 3 p2_1_p3_1 needs clearer AREA structure."],
                "revision_instructions": "Revise only the flagged Part 3 answer.",
            }
        if schema_name == "revised_answer_batch":
            self.calls.append({"schema_name": schema_name, "messages": messages, "temperature": temperature})
            return {
                "part1": [],
                "part2_blocks": [
                    {
                        "block_id": "p2_1",
                        "part3": [
                            {
                                "question_id": "p2_1_p3_1",
                                "framework": "AREA-Alternative",
                                "answer_en": " ".join(["revised"] * 42),
                                "answer_zh": "修订后的 Part 3 答案。",
                                "memory_cues": ["revised"],
                            }
                        ],
                    }
                ],
            }
        return super().complete_json(messages=messages, schema_name=schema_name, temperature=temperature)


def test_generation_pipeline_merges_partial_part3_revisions_without_replacing_block(tmp_path: Path):
    client = PartialPart3RevisionClient()
    config = GenerationConfig(
        target_band=7,
        answer_length="medium",
        speaking_speed_wpm=80,
        checkpoint_mode=False,
        output_dir=tmp_path,
    )

    result = GenerationPipeline(client=client, config=config).run(bank=small_bank(), profile={"name": "Alex"})

    block = result["answers"]["part2_blocks"][0]
    assert block["answer_en"] == " ".join(["story"] * 133)
    assert block["part3"][0]["answer_en"] == " ".join(["revised"] * 42)
    assert result["review"]["revision_status"] == "revised"


class LargeTargetedRevisionClient(BankAwareClient):
    def complete_json(self, *, messages, schema_name, temperature):
        if schema_name == "answer_batch":
            result = super().complete_json(messages=messages, schema_name=schema_name, temperature=temperature)
            if result["part2_blocks"]:
                result["part2_blocks"][0]["answer_en"] = "short answer"
            return result
        if schema_name == "quality_review":
            self.calls.append({"schema_name": schema_name, "messages": messages, "temperature": temperature})
            return {"passed": False, "issues": ["Part 2 p2_1 is too short."], "revision_instructions": "Expand p2_1 only."}
        if schema_name == "revised_answer_batch":
            self.calls.append({"schema_name": schema_name, "messages": messages, "temperature": temperature})
            content = messages[1]["content"]
            return {
                "part1": [],
                "part2_blocks": [
                    {
                        "block_id": "p2_1",
                        "framework": "Umbrella Part 2",
                        "answer_en": " ".join(["expanded"] * 133),
                        "answer_zh": "扩展后的 Part 2 答案。",
                        "memory_cues": ["expanded"],
                        "umbrella_story": "story_general",
                        "part3": [],
                    }
                ],
                "_message_content": content,
            }
        return super().complete_json(messages=messages, schema_name=schema_name, temperature=temperature)


def test_generation_pipeline_uses_targeted_revision_for_large_answer_sets(tmp_path: Path):
    client = LargeTargetedRevisionClient()
    config = GenerationConfig(
        target_band=7,
        answer_length="medium",
        speaking_speed_wpm=80,
        checkpoint_mode=False,
        max_revision_items=5,
        output_dir=tmp_path,
    )

    result = GenerationPipeline(client=client, config=config).run(bank=multi_block_bank(3), profile={"name": "Alex"})

    assert result["review"]["revision_status"] == "revised"
    assert result["answers"]["part2_blocks"][0]["answer_en"] == " ".join(["expanded"] * 133)
    assert [call["schema_name"] for call in client.calls].count("revised_answer_batch") == 1


def test_generation_pipeline_prefers_timing_targets_over_broad_review_mentions(tmp_path: Path):
    client = LargeTargetedRevisionClient()
    config = GenerationConfig(
        target_band=7,
        answer_length="medium",
        speaking_speed_wpm=80,
        checkpoint_mode=False,
        max_revision_items=5,
        output_dir=tmp_path,
    )

    result = GenerationPipeline(client=client, config=config).run(bank=multi_block_bank(3), profile={"name": "Alex"})

    assert result["review"]["revision_target_ids"] == ["p2_1"]


def test_generation_pipeline_skips_revision_for_large_answer_sets(tmp_path: Path):
    client = BankAwareClient()
    config = GenerationConfig(
        target_band=7,
        answer_length="medium",
        speaking_speed_wpm=80,
        checkpoint_mode=False,
        max_revision_items=5,
        output_dir=tmp_path,
    )

    result = GenerationPipeline(client=client, config=config).run(bank=multi_block_bank(3), profile={"name": "Alex"})

    assert result["review"]["passed"] is False
    assert result["review"]["revision_status"] == "skipped_large_batch_original_answers_kept"
    assert "exceeded 5" in result["review"]["revision_error"]
    assert "revised_answer_batch" not in [call["schema_name"] for call in client.calls]
    assert [block["block_id"] for block in result["answers"]["part2_blocks"]] == ["p2_1", "p2_2", "p2_3"]
