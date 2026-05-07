from pathlib import Path

import yaml

from ielts_tailor.generation import GenerationConfig, GenerationPipeline


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
                        "answer_en": "Yes, I prefer happy music because it lifts my mood.",
                        "answer_zh": "是的，我更喜欢快乐的音乐，因为它能改善我的心情。",
                        "memory_cues": ["happy music", "mood"],
                    }
                ],
                "part2_blocks": [
                    {
                        "block_id": "p2_1",
                        "framework": "Umbrella Part 2",
                        "answer_en": "I would talk about a city trip that helped me understand urban life.",
                        "answer_zh": "我会讲一次城市旅行，它让我理解了城市生活。",
                        "memory_cues": ["city trip", "urban life"],
                        "umbrella_story": "story_city_trip",
                        "part3": [
                            {
                                "question_id": "p2_1_p3_1",
                                "framework": "AREA-Alternative",
                                "answer_en": "People choose cities mainly for convenience, for example transport and food options.",
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
                        "answer_en": "I would talk about a city trip that helped me understand urban life.",
                        "answer_zh": "我会讲一次城市旅行，它让我理解了城市生活。",
                        "memory_cues": ["city trip", "urban life"],
                        "umbrella_story": "story_city_trip",
                        "part3": [
                            {
                                "question_id": "p2_1_p3_1",
                                "framework": "AREA-Alternative",
                                "answer_en": "Answer: convenience matters. Reason: cities save time. Example: metro systems make travel easier. Alternative: some people still prefer quiet towns.",
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


def test_generation_pipeline_creates_style_checkpoint_review_revision_and_cache(tmp_path: Path):
    client = FakeLLMClient()
    config = GenerationConfig(
        target_band=7,
        answer_length="medium",
        speaking_speed_wpm=120,
        checkpoint_mode=True,
        output_dir=tmp_path,
    )
    profile = {"name": "Alex", "hometown": "Hong Kong", "stories": [{"id": "city_trip", "detail": "visited Tokyo"}]}

    result = GenerationPipeline(client=client, config=config).run(bank=small_bank(), profile=profile)

    assert (tmp_path / "cache" / "style_guide.yaml").exists()
    assert (tmp_path / "checkpoints" / "samples.yaml").exists()
    assert result["review"]["passed"] is False
    assert result["answers"]["part2_blocks"][0]["part3"][0]["framework"] == "AREA-Alternative"
    assert result["answers"]["part2_blocks"][0]["part3"][0]["answer_en"].startswith("Answer:")
    assert [call["schema_name"] for call in client.calls] == [
        "style_guide",
        "checkpoint_samples",
        "answer_batch",
        "quality_review",
        "revised_answer_batch",
    ]
    assert all(call["temperature"] <= 0.3 for call in client.calls)

    style = yaml.safe_load((tmp_path / "cache" / "style_guide.yaml").read_text())
    assert style["student_voice"].startswith("clear")


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
        speaking_speed_wpm=120,
        checkpoint_mode=False,
        output_dir=tmp_path,
    )

    GenerationPipeline(client=generator, reviewer_client=reviewer, config=config).run(bank=small_bank(), profile={"name": "Alex"})

    assert [call["schema_name"] for call in generator.calls] == [
        "style_guide",
        "answer_batch",
        "revised_answer_batch",
    ]
    assert [call["schema_name"] for call in reviewer.calls] == ["quality_review"]


class FlakyStyleGuideClient(FakeLLMClient):
    def complete_json(self, *, messages, schema_name, temperature):
        if schema_name == "style_guide" and not any(call["schema_name"] == "style_guide" for call in self.calls):
            self.calls.append({"schema_name": schema_name, "messages": messages, "temperature": temperature})
            return {"student_voice": "missing required fields"}
        return super().complete_json(messages=messages, schema_name=schema_name, temperature=temperature)


def test_generation_pipeline_retries_incomplete_schema_response(tmp_path: Path):
    client = FlakyStyleGuideClient()
    config = GenerationConfig(
        target_band=7,
        answer_length="medium",
        speaking_speed_wpm=120,
        checkpoint_mode=False,
        output_dir=tmp_path,
    )

    result = GenerationPipeline(client=client, config=config).run(bank=small_bank(), profile={"name": "Alex"})

    assert result["style_guide"]["story_inventory"][0]["id"] == "story_city_trip"
    assert [call["schema_name"] for call in client.calls].count("style_guide") == 2
