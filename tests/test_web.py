from pathlib import Path

import yaml

from ielts_tailor.web import load_web_state, save_profile_responses, save_result_markdown, save_settings


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


def test_load_web_state_includes_online_test_data_and_timing_targets(tmp_path: Path):
    config_path = write_project(tmp_path)

    state = load_web_state(config_path)

    assert state["word_targets"]["part1"]["words"] == 20
    assert state["word_targets"]["part2"]["min_words"] == 133
    assert state["word_targets"]["part2"]["max_words"] == 147
    assert state["word_targets"]["part3"]["words"] == 53
    assert state["questionnaire"]["part1"][0]["question"] == "Do you prefer sad or happy music?"
    assert state["questionnaire"]["umbrella_stories"][0]["theme"] == "city_travel"
    assert state["questionnaire"]["umbrella_stories"][0]["part2_prompts"] == ["Describe your favorite city that you have visited"]
    assert state["profile"]["name"] == "Alex"
    assert state["coverage"]["status"] == "资料不足"
    assert state["settings"]["speaking_speed_wpm"] == 80


def test_save_profile_responses_writes_editable_yaml(tmp_path: Path):
    config_path = write_project(tmp_path)

    path = save_profile_responses(
        config_path,
        {
            "part1": {"p1_music_q1": {"direct_answer": "Happy music", "example": "It helps me study."}},
            "umbrella_stories": {"city_travel": {"story": "Tokyo trip", "details": ["metro", "food", "parks"]}},
        },
    )

    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert path == tmp_path / "output" / "profile_responses.yaml"
    assert saved["part1"]["p1_music_q1"]["direct_answer"] == "Happy music"
    assert saved["umbrella_stories"]["city_travel"]["story"] == "Tokyo trip"


def test_save_result_markdown_writes_editable_answers_file(tmp_path: Path):
    config_path = write_project(tmp_path)

    path = save_result_markdown(config_path, "# Edited IELTS Answers\n\nEnglish: sample")

    assert path == tmp_path / "output" / "ielts_speaking_answers.md"
    assert path.read_text(encoding="utf-8").startswith("# Edited IELTS Answers")


def test_save_settings_updates_config_yaml_for_nontechnical_ui(tmp_path: Path):
    config_path = write_project(tmp_path)

    save_settings(
        config_path,
        {
            "target_band": 8,
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
    assert config["generation"]["target_band"] == 8
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
    assert "资料不足" in app
    assert "请补充" in app
