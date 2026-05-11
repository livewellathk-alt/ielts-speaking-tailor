import pytest
import yaml

from ielts_tailor.bank import import_bank_text
from ielts_tailor.coverage import analyze_coverage
from ielts_tailor.profile_builder import build_generation_profile
from ielts_tailor.web import generate_sample_answers


IMPORTED_BANK_TEXT = """
一、大陆地区新题

Part 1 5 月在考新题（10 道）

1 P1 Music

Do you prefer sad or happy music?
When do you listen to music?

Part 2&3 5 月在考新题（12 道）

1 P2 去过的最喜欢的城市

Describe your favorite city that you have visited
You should say:
Where it is
When you went there
What you did there
And explain why you liked it

P3
How do people choose a city to travel to?
What are the differences between travelling to cities and natural places?

2 P2 有用的软件

Describe an app or website you often use
You should say:
What it is
When you use it
Why it is useful
And explain how you feel about it

P3
How has technology changed people's lives?
Which is more helpful, using apps or asking teachers?
"""


def two_theme_bank():
    return {
        "part1_topics": [
            {
                "id": "p1_music",
                "title": "Music",
                "questions": [
                    {"id": "p1_music_q1", "question": "Do you prefer sad or happy music?"},
                    {"id": "p1_music_q2", "question": "When do you listen to music?"},
                ],
            }
        ],
        "part2_blocks": [
            {
                "id": "p2_city",
                "title_zh": "喜欢的城市",
                "part2": {"prompt": "Describe a city you visited and liked", "cue_points": []},
                "part3": [{"id": "p2_city_p3_1", "question": "Why do people like visiting cities?"}],
                "source_order": 1,
            },
            {
                "id": "p2_app",
                "title_zh": "有用的软件",
                "part2": {"prompt": "Describe an app or website you often use", "cue_points": []},
                "part3": [{"id": "p2_app_p3_1", "question": "How has technology changed people's lives?"}],
                "source_order": 2,
            },
        ],
    }


def strong_responses():
    return {
        "part1": {
            "p1_music_q1": {"direct_answer": "Happy music", "example": "It helps me focus before class."},
            "p1_music_q2": {"direct_answer": "In the evening", "example": "I listen while walking home."},
        },
        "umbrella_stories": {
            "city_travel": {
                "story": "I visited Tokyo during a school break with my classmates.",
                "details": "metro system, ramen shop, clean streets",
                "lesson": "It made me appreciate organized public transport.",
                "avoid": "Do not say I lived there.",
            },
            "technology_media": {
                "story": "I started using a study app before my final exams.",
                "details": "flashcards, reminders, progress chart",
                "lesson": "It helped me study more consistently.",
                "avoid": "Do not mention gaming.",
            },
        },
        "part3": {
            "p2_city_p3_1": {"opinion": "Cities offer convenience.", "example": "Transport and food choices are easy to find."},
            "p2_app_p3_1": {"opinion": "Technology saves time.", "example": "Apps help students organize revision."},
        },
    }


def minimal_scope_responses():
    return {
        "part1": {
            "p1_music_q1": {"direct_answer": "Happy music", "example": "It helps me focus before class."},
            "p1_music_q2": {"direct_answer": "In the evening", "example": "I listen while walking home."},
        },
        "umbrella_stories": {
            "scope_places_visited_place": {
                "story": "I visited Tokyo during a school break with my classmates.",
                "details": "metro system, ramen shop, clean streets",
                "lesson": "It made me appreciate organized public transport.",
                "avoid": "Do not say I lived there.",
            },
            "scope_objects_useful_object": {
                "story": "I started using a study app before my final exams.",
                "details": "flashcards, reminders, progress chart",
                "lesson": "It helped me study more consistently.",
                "avoid": "Do not mention gaming.",
            },
        },
        "part3_scope_defaults": {
            "scope_places_visited_place": {
                "opinion": "Cities are convenient but can feel crowded.",
                "example": "Tokyo was easy to explore because the metro was clear.",
            },
            "scope_objects_useful_object": {
                "opinion": "Technology is useful when it saves time.",
                "example": "A flashcard app helped me revise more consistently.",
            },
        },
    }


def write_project(tmp_path):
    data_dir = tmp_path / "data"
    output_dir = tmp_path / "output"
    data_dir.mkdir()
    output_dir.mkdir()
    config = {
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
    (data_dir / "question_bank.yaml").write_text(yaml.safe_dump(two_theme_bank(), sort_keys=False, allow_unicode=True), encoding="utf-8")
    (tmp_path / "student_profile.yaml").write_text(
        yaml.safe_dump({"name": "Alex", "current_status": "student", "hometown": "Hong Kong", "stories": []}, sort_keys=False),
        encoding="utf-8",
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return config_path


def test_coverage_flags_missing_inputs_with_chinese_followups():
    report = analyze_coverage(two_theme_bank(), {"part1": {"p1_music_q1": {"direct_answer": "Happy music"}}})

    assert report["overall_percent"] < 70
    assert report["can_generate_sample"] is False
    assert report["can_generate_full"] is False
    assert any("请补充" in item for item in report["followups"])
    assert any(item["theme"] == "scope_places_visited_place" and item["status"] == "资料不足" for item in report["theme_reports"])
    assert any(item["theme"] == "scope_objects_useful_object" and item["status"] == "资料不足" for item in report["theme_reports"])


def test_coverage_allows_sample_and_full_when_inputs_have_coverage_and_depth():
    report = analyze_coverage(two_theme_bank(), strong_responses())

    assert report["overall_percent"] >= 85
    assert report["can_generate_sample"] is True
    assert report["can_generate_full"] is True
    assert report["status"] == "可以全量生成"


def test_coverage_allows_full_generation_with_minimal_scope_defaults():
    report = analyze_coverage(two_theme_bank(), minimal_scope_responses())

    assert report["overall_percent"] >= 85
    assert report["can_generate_sample"] is True
    assert report["can_generate_full"] is True
    assert {item["theme"] for item in report["theme_reports"]} == {
        "scope_places_visited_place",
        "scope_objects_useful_object",
    }


def test_coverage_allows_full_generation_for_imported_bank_ids(tmp_path):
    bank = import_bank_text(IMPORTED_BANK_TEXT, region="mainland", output_path=tmp_path / "question_bank.yaml")
    responses = {
        "part1": {
            "p1_music_q1": {"direct_answer": "Happy music", "example": "It helps me focus before class."},
            "p1_music_q2": {"direct_answer": "In the evening", "example": "I listen while walking home."},
        },
        "umbrella_stories": {
            "city_travel": {
                "story": "I visited Tokyo during a school break with my classmates.",
                "details": "metro system, ramen shop, clean streets",
                "lesson": "It made me appreciate organized public transport.",
                "avoid": "Do not say I lived there.",
            },
            "technology_media": {
                "story": "I started using a study app before my final exams.",
                "details": "flashcards, reminders, progress chart",
                "lesson": "It helped me study more consistently.",
                "avoid": "Do not mention gaming.",
            },
        },
        "part3": {
            "p2_1_p3_1": {"opinion": "Cities offer convenience.", "example": "Transport and food choices are easy to find."},
            "p2_1_p3_2": {"opinion": "Natural places are quieter.", "example": "A mountain trip is calmer than shopping downtown."},
            "p2_2_p3_1": {"opinion": "Technology saves time.", "example": "Apps help students organize revision."},
            "p2_2_p3_2": {"opinion": "Teachers are better for feedback.", "example": "An app cannot always explain mistakes clearly."},
        },
    }

    report = analyze_coverage(bank, responses)

    assert report["overall_percent"] >= 85
    assert report["can_generate_sample"] is True
    assert report["can_generate_full"] is True
    assert report["status"] == "可以全量生成"


def test_generation_profile_merges_browser_responses_into_student_profile():
    responses = minimal_scope_responses()
    profile = build_generation_profile({"name": "Alex", "stories": [{"id": "existing", "title": "Existing story"}]}, responses)

    assert profile["name"] == "Alex"
    assert "browser_responses" in profile
    assert any(story["id"] == "response_scope_places_visited_place" for story in profile["stories"])
    assert profile["theme_answers"]["scope_objects_useful_object"]["part3_default"]["opinion"] == "Technology is useful when it saves time."
    assert profile["speaking_preferences"]["avoid_topics"] == ["Do not say I lived there.", "Do not mention gaming."]


def test_generate_sample_refuses_when_coverage_is_too_weak(tmp_path):
    config_path = write_project(tmp_path)

    with pytest.raises(RuntimeError, match="资料不足"):
        generate_sample_answers(config_path)
