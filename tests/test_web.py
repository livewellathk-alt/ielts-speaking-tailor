import time
from pathlib import Path

import yaml
from docx import Document

from ielts_tailor.bank import import_bank_text
from ielts_tailor.web import (
    generate_answers,
    generate_sample_answers,
    get_generation_job,
    import_uploaded_question_bank,
    load_web_state,
    save_profile_responses,
    save_result_markdown,
    save_settings,
    save_student_profile,
    start_generation_job,
)


REALISTIC_BANK_TEXT = """
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


def write_project(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    output_dir = tmp_path / "output"
    data_dir.mkdir()
    output_dir.mkdir()
    bank = {
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
    profile = {"name": "Alex", "current_status": "student", "hometown": "Hong Kong", "stories": []}
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
    (data_dir / "question_bank.yaml").write_text(yaml.safe_dump(bank, sort_keys=False, allow_unicode=True), encoding="utf-8")
    (tmp_path / "student_profile.yaml").write_text(yaml.safe_dump(profile, sort_keys=False, allow_unicode=True), encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return config_path


def write_realistic_project(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    output_dir = tmp_path / "output"
    data_dir.mkdir()
    output_dir.mkdir()
    import_bank_text(REALISTIC_BANK_TEXT, region="mainland", output_path=data_dir / "question_bank.yaml")
    profile = {"name": "Alex", "current_status": "student", "hometown": "Hong Kong", "stories": []}
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
    (tmp_path / "student_profile.yaml").write_text(yaml.safe_dump(profile, sort_keys=False, allow_unicode=True), encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return config_path


def realistic_responses() -> dict:
    return {
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
    }


class DeterministicClient:
    def __init__(self, **_kwargs):
        pass

    def complete_json(self, *, messages, schema_name, temperature):
        if schema_name == "style_guide":
            return {
                "student_voice": "clear, personal, and natural",
                "target_band_rules": ["answer directly", "use concrete examples"],
                "preferred_structures": ["A+R/E", "AREA"],
                "lexical_boundaries": ["comfortable vocabulary only"],
                "consistency_constraints": ["do not invent personal history"],
                "story_inventory": [{"id": "response_city_travel", "title": "Tokyo trip", "themes": ["city_travel"]}],
            }
        if schema_name == "checkpoint_samples":
            return {"samples": [{"theme": "city_travel", "answer": "Sample answer", "approved": True}]}
        if schema_name == "quality_review":
            return {"passed": True, "issues": [], "revision_instructions": ""}
        if schema_name in {"answer_batch", "revised_answer_batch"}:
            return self._answer_batch(messages)
        raise AssertionError(schema_name)

    def _answer_batch(self, messages):
        context = yaml.safe_load(messages[1]["content"].split("\n\n", 1)[1])
        bank = context["payloads"][0]
        part1 = [
            {
                "question_id": question["id"],
                "framework": question.get("framework", "A+R/E"),
                "answer_en": " ".join(["answer"] * 12),
                "answer_zh": f"我会结合自己的经历回答：{question['question']}",
                "memory_cues": ["personal", "specific"],
            }
            for topic in bank.get("part1_topics", [])
            for question in topic.get("questions", [])
        ]
        part2_blocks = []
        for block in bank.get("part2_blocks", []):
            part2_blocks.append(
                {
                    "block_id": block["id"],
                    "framework": "Umbrella Part 2",
                    "answer_en": " ".join(["story"] * 133),
                    "answer_zh": f"我会用真实经历回答这个题目：{block['part2']['prompt']}",
                    "memory_cues": ["real story", block.get("theme", "theme")],
                    "umbrella_story": f"response_{block.get('theme', 'general_experience')}",
                    "part3": [
                        {
                            "question_id": question["id"],
                            "framework": question.get("framework", "AREA-Alternative"),
                            "answer_en": " ".join(["reason"] * 42),
                            "answer_zh": f"答案：{question['question']} 原因：具体例子会让观点更清楚。",
                            "memory_cues": ["answer", "reason", "example"],
                        }
                        for question in block.get("part3", [])
                    ],
                }
            )
        return {"part1": part1, "part2_blocks": part2_blocks}


def test_load_web_state_includes_online_test_data_and_timing_targets(tmp_path: Path):
    config_path = write_project(tmp_path)

    state = load_web_state(config_path)

    assert state["word_targets"]["part1"]["words"] == 20
    assert state["word_targets"]["part2"]["min_words"] == 133
    assert state["word_targets"]["part2"]["max_words"] == 147
    assert state["word_targets"]["part3"]["words"] == 53
    assert state["questionnaire"]["part1"][0]["question"] == "Do you prefer sad or happy music?"
    assert state["questionnaire"]["collection_sequence"] == ["part2_scope_collection"]
    assert state["questionnaire"]["umbrella_stories"][0]["scope_id"] == "scope_places_visited_place"
    assert state["questionnaire"]["umbrella_stories"][0]["scope_label"] == "Places: visited place"
    assert state["questionnaire"]["umbrella_stories"][0]["part2_prompts"] == ["Describe your favorite city that you have visited"]
    assert state["questionnaire"]["umbrella_stories"][0]["why_reusable"]
    assert state["poll_progress"]["total"] == 1
    assert state["poll_progress"]["answered"] == 0
    assert state["poll_progress"]["percent"] == 0
    assert state["profile"]["name"] == "Alex"
    assert "name: Alex" in state["profile_yaml"]
    assert state["coverage"]["status"] == "资料不足"
    assert state["settings"]["speaking_speed_wpm"] == 80


def test_save_profile_responses_writes_editable_yaml(tmp_path: Path):
    config_path = write_project(tmp_path)

    path = save_profile_responses(
        config_path,
        {
            "part1": {"p1_music_q1": {"direct_answer": "Happy music", "example": "It helps me study."}},
            "umbrella_stories": {"scope_places_visited_place": {"story": "Tokyo trip", "details": ["metro", "food", "parks"]}},
        },
    )

    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert path == tmp_path / "output" / "profile_responses.yaml"
    assert saved["part1"]["p1_music_q1"]["direct_answer"] == "Happy music"
    assert saved["umbrella_stories"]["scope_places_visited_place"]["story"] == "Tokyo trip"


def test_web_poll_progress_counts_completed_scope_cards(tmp_path: Path):
    config_path = write_project(tmp_path)
    save_profile_responses(
        config_path,
        {
            "umbrella_stories": {
                "scope_places_visited_place": {
                    "story": "I visited Tokyo during a school break with classmates and used that trip in many examples.",
                    "details": "metro system, ramen shop, clean streets",
                    "lesson": "It made me appreciate organized public transport.",
                }
            }
        },
    )

    state = load_web_state(config_path)

    assert state["poll_progress"]["total"] == 1
    assert state["poll_progress"]["answered"] == 1
    assert state["poll_progress"]["percent"] == 100


def test_import_uploaded_pdf_question_bank_writes_configured_bank_path(tmp_path: Path, monkeypatch):
    config_path = write_project(tmp_path)
    calls = []

    def fake_import_bank(source_path, *, region, output_path):
        calls.append((Path(source_path), region, Path(output_path)))
        bank = {
            "metadata": {"region_filter": region},
            "part1_topics": [],
            "part2_blocks": [],
        }
        Path(output_path).write_text(yaml.safe_dump(bank, sort_keys=False, allow_unicode=True), encoding="utf-8")
        return bank

    monkeypatch.setattr("ielts_tailor.web.import_bank", fake_import_bank)

    result = import_uploaded_question_bank(config_path, filename="May-bank.PDF", content=b"%PDF-1.4", region="mainland")

    assert result["question_bank_path"] == str(tmp_path / "data" / "question_bank.yaml")
    assert result["uploaded_path"].endswith("May-bank.PDF")
    assert calls == [(tmp_path / "output" / "uploads" / "May-bank.PDF", "mainland", tmp_path / "data" / "question_bank.yaml")]
    assert (tmp_path / "data" / "question_bank.yaml").exists()


def test_save_result_markdown_writes_editable_answers_file(tmp_path: Path):
    config_path = write_project(tmp_path)

    path = save_result_markdown(config_path, "# Edited IELTS Answers\n\nEnglish: sample")

    assert path == tmp_path / "output" / "ielts_speaking_answers.md"
    assert path.read_text(encoding="utf-8").startswith("# Edited IELTS Answers")


def test_save_student_profile_updates_yaml_and_state(tmp_path: Path):
    config_path = write_project(tmp_path)

    path = save_student_profile(
        config_path,
        """
name: Maya
current_status: designer
hometown: Shenzhen
speaking_preferences:
  comfort_topics:
    - design
  avoid_topics:
    - Do not mention old school.
stories: []
""",
    )

    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    state = load_web_state(config_path)
    assert path == tmp_path / "student_profile.yaml"
    assert saved["name"] == "Maya"
    assert state["profile"]["current_status"] == "designer"
    assert "hometown: Shenzhen" in state["profile_yaml"]


def test_save_student_profile_rejects_invalid_yaml_and_non_mapping(tmp_path: Path):
    config_path = write_project(tmp_path)

    for profile_yaml in ["name: [", "- just\n- a list\n"]:
        try:
            save_student_profile(config_path, profile_yaml)
        except ValueError as exc:
            assert str(exc)
        else:
            raise AssertionError("Expected invalid student profile YAML to fail")

    profile = yaml.safe_load((tmp_path / "student_profile.yaml").read_text(encoding="utf-8"))
    assert profile["name"] == "Alex"


def test_save_settings_updates_config_yaml_for_nontechnical_ui(tmp_path: Path):
    config_path = write_project(tmp_path)

    save_settings(
        config_path,
        {
            "target_band": 6.5,
            "speaking_speed_wpm": 90,
            "part1_seconds": 18,
            "part2_min_seconds": 105,
            "part2_max_seconds": 115,
            "part3_seconds": 45,
            "base_url": "https://openrouter.ai/api/v1",
            "api_key_env": "OPENROUTER_API_KEY",
            "model": "deepseek/deepseek-v4-flash",
        },
    )

    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert config["generation"]["target_band"] == 6.5
    assert config["generation"]["speaking_speed_wpm"] == 90
    assert config["generation"]["timing"]["part1_seconds"] == 18
    assert config["generation"]["timing"]["part2_min_seconds"] == 105
    assert config["generation"]["timing"]["part2_max_seconds"] == 115
    assert config["generation"]["timing"]["part3_seconds"] == 45
    assert config["llm"]["base_url"] == "https://openrouter.ai/api/v1"
    assert config["llm"]["api_key_env"] == "OPENROUTER_API_KEY"
    assert config["llm"]["model"] == "deepseek/deepseek-v4-flash"


def test_web_assets_are_chinese_first():
    root = Path(__file__).parents[1]
    html = (root / "src" / "ielts_tailor" / "web_assets" / "index.html").read_text(encoding="utf-8")
    app = (root / "src" / "ielts_tailor" / "web_assets" / "app.js").read_text(encoding="utf-8")

    assert "雅思口语定制器" in html
    assert "设置" in html
    assert "生成测试样本" in html
    assert 'id="targetBandInput" type="number" min="5" max="9" step="0.5"' in html
    assert 'id="profileYamlInput"' in html
    assert 'id="saveProfileButton"' in html
    assert "资料不足" in app
    assert "请补充" in app
    assert "/api/student-profile" in app
    assert 'group: "part1"' not in app
    assert 'group: "part3_scope_defaults"' not in app
    assert "一套素材生成 Part 2、Part 3 和 Part 1" in app


def test_web_sample_and_full_generation_write_complete_outputs(tmp_path: Path, monkeypatch):
    config_path = write_realistic_project(tmp_path)
    save_profile_responses(config_path, realistic_responses())
    monkeypatch.setattr("ielts_tailor.web.OpenAICompatibleClient", DeterministicClient)

    sample = generate_sample_answers(config_path)
    sample_state = load_web_state(config_path)
    full = generate_answers(config_path)

    sample_markdown = Path(sample["rendered"]["markdown"])
    sample_docx = Path(sample["rendered"]["docx"])
    full_markdown = Path(full["rendered"]["markdown"])
    full_docx = Path(full["rendered"]["docx"])
    assert sample_markdown == tmp_path / "output" / "ielts_speaking_sample.md"
    assert sample_docx == tmp_path / "output" / "ielts_speaking_sample.docx"
    assert full_markdown == tmp_path / "output" / "ielts_speaking_answers.md"
    assert full_docx == tmp_path / "output" / "ielts_speaking_answers.docx"
    assert sample_state["result_markdown_source"] == "sample"
    assert "IELTS Speaking Tailor" in sample_state["result_markdown"]

    markdown = full_markdown.read_text(encoding="utf-8")
    assert "## Timing Targets" in markdown
    assert "## Umbrella Story Index" in markdown
    assert "Do you prefer sad or happy music?" in markdown
    assert "When do you listen to music?" in markdown
    assert "### Part 2: 去过的最喜欢的城市" in markdown
    assert "### Part 2: 有用的软件" in markdown
    assert "How do people choose a city to travel to?" in markdown
    assert "How has technology changed people's lives?" in markdown

    doc_text = "\n".join(paragraph.text for paragraph in Document(full_docx).paragraphs)
    assert "IELTS Speaking Tailor" in doc_text
    assert "Do you prefer sad or happy music?" in doc_text
    assert "有用的软件" in doc_text
    assert "How has technology changed people's lives?" in doc_text


def test_generation_job_exposes_stage_progress_and_final_state(tmp_path: Path, monkeypatch):
    config_path = write_realistic_project(tmp_path)
    save_profile_responses(config_path, realistic_responses())
    monkeypatch.setattr("ielts_tailor.web.OpenAICompatibleClient", DeterministicClient)

    job = start_generation_job(config_path, mode="sample")
    deadline = time.time() + 5
    status = get_generation_job(job["job_id"])
    while status["status"] not in {"completed", "failed"} and time.time() < deadline:
        time.sleep(0.05)
        status = get_generation_job(job["job_id"])

    assert status["status"] == "completed"
    assert status["percent"] == 100
    assert [event["stage"] for event in status["events"]] == [
        "scope_analysis",
        "style_guide",
        "checkpoint_samples",
        "answer_batch",
        "quality_review",
        "render_output",
    ]
    assert status["state"]["files"]["result_markdown_exists"] is False
    assert Path(status["result"]["rendered"]["markdown"]).name == "ielts_speaking_sample.md"
