from pathlib import Path

import yaml
from docx import Document

from ielts_tailor.cli import build_parser, main
from ielts_tailor.rendering import render_markdown, render_outputs


def answer_payload():
    return {
        "style_guide": {"student_voice": "clear and personal"},
        "word_targets": {
            "part1": {"seconds": 15, "words": 20},
            "part2": {"min_seconds": 100, "max_seconds": 110, "min_words": 133, "max_words": 147},
            "part3": {"seconds": 40, "words": 53},
        },
        "answers": {
            "part1": [
                {
                    "question_id": "p1_music_q1",
                    "question": "Do you prefer sad or happy music?",
                    "framework": "A+R",
                    "answer_en": "I prefer happy music because it lifts my mood.",
                    "answer_zh": "我更喜欢快乐的音乐，因为它能改善我的心情。",
                    "memory_cues": ["happy music", "mood"],
                }
            ],
            "part2_blocks": [
                {
                    "block_id": "p2_1",
                    "title_zh": "去过的最喜欢的城市",
                    "part2_prompt": "Describe your favorite city that you have visited",
                    "framework": "Umbrella Part 2",
                    "answer_en": "I would describe Tokyo as a flexible city story.",
                    "answer_zh": "我会把东京作为一个灵活的城市故事来讲。",
                    "memory_cues": ["Tokyo", "city story"],
                    "umbrella_story": "story_city_trip",
                    "part3": [
                        {
                            "question_id": "p2_1_p3_1",
                            "question": "How do people choose a city to travel to?",
                            "framework": "AREA-Alternative",
                            "answer_en": "People choose cities for convenience.",
                            "answer_zh": "人们因为便利而选择城市。",
                            "memory_cues": ["convenience"],
                        }
                    ],
                }
            ],
        },
    }


def test_render_markdown_keeps_part3_under_part2_and_includes_indexes():
    markdown = render_markdown(answer_payload())

    assert "# IELTS Speaking Tailor" in markdown
    assert "## Timing Targets" in markdown
    assert "Part 1: about 15 seconds / 20 words" in markdown
    assert "Part 2: 100-110 seconds / 133-147 words" in markdown
    assert "Part 3: about 40 seconds / 53 words" in markdown
    assert "## Umbrella Story Index" in markdown
    assert "### Part 2: 去过的最喜欢的城市" in markdown
    assert markdown.index("Describe your favorite city") < markdown.index("#### Part 3")
    assert "English:" in markdown
    assert "中文:" in markdown
    assert "Memory cues:" in markdown


def test_render_markdown_splits_string_memory_cues_into_readable_items():
    payload = answer_payload()
    payload["answers"]["part1"][0]["memory_cues"] = "happy music, morning, energy"

    markdown = render_markdown(payload)

    assert "Memory cues: happy music, morning, energy" in markdown
    assert "h, a, p, p, y" not in markdown


def test_render_markdown_handles_dict_umbrella_story_from_llm():
    payload = answer_payload()
    payload["answers"]["part2_blocks"][0]["umbrella_story"] = {
        "story": "Tokyo trip",
        "details": "metro, ramen, clean streets",
    }

    markdown = render_markdown(payload)

    assert "`Tokyo trip`" in markdown
    assert "unhashable" not in markdown


def test_render_outputs_writes_markdown_and_docx(tmp_path: Path):
    paths = render_outputs(answer_payload(), output_dir=tmp_path, basename="answers")

    assert paths["markdown"].exists()
    assert paths["docx"].exists()
    doc = Document(paths["docx"])
    text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
    assert "IELTS Speaking Tailor" in text
    assert "Do you prefer sad or happy music?" in text
    assert "How do people choose a city to travel to?" in text


def test_cli_init_creates_editable_templates(tmp_path: Path):
    exit_code = main(["init", "--root", str(tmp_path)])

    assert exit_code == 0
    assert (tmp_path / "config.yaml").exists()
    assert (tmp_path / "student_profile.yaml").exists()
    assert (tmp_path / "band_descriptors.yaml").exists()
    config = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert config["llm"]["api_key_env"] == "OPENAI_API_KEY"
    assert config["generation"]["speaking_speed_wpm"] == 80
    assert config["generation"]["timing"] == {
        "part1_seconds": 15,
        "part2_min_seconds": 100,
        "part2_max_seconds": 110,
        "part3_seconds": 40,
    }


def test_generate_parser_accepts_timing_overrides():
    args = build_parser().parse_args(
        [
            "generate",
            "--config",
            "config.yaml",
            "--wpm",
            "90",
            "--part1-seconds",
            "18",
            "--part2-min-seconds",
            "105",
            "--part2-max-seconds",
            "115",
            "--part3-seconds",
            "45",
        ]
    )

    assert args.wpm == 90
    assert args.part1_seconds == 18
    assert args.part2_min_seconds == 105
    assert args.part2_max_seconds == 115
    assert args.part3_seconds == 45


def test_web_parser_accepts_local_server_options():
    args = build_parser().parse_args(
        [
            "web",
            "--config",
            "config.yaml",
            "--host",
            "127.0.0.1",
            "--port",
            "8765",
            "--no-open",
        ]
    )

    assert args.command == "web"
    assert args.config == "config.yaml"
    assert args.host == "127.0.0.1"
    assert args.port == 8765
    assert args.no_open is True


def test_profile_questions_asks_for_part1_inputs_and_umbrella_stories(tmp_path: Path):
    bank = {
        "metadata": {"region_filter": "mainland"},
        "part1_topics": [
            {
                "id": "p1_music",
                "title": "Music",
                "questions": [
                    {"id": "p1_music_q1", "question": "Do you prefer sad or happy music?"},
                ],
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
    bank_path = tmp_path / "bank.yaml"
    output_path = tmp_path / "student_questionnaire.md"
    bank_path.write_text(yaml.safe_dump(bank, sort_keys=False, allow_unicode=True), encoding="utf-8")

    exit_code = main(["profile-questions", "--bank", str(bank_path), "--output", str(output_path)])

    assert exit_code == 0
    questionnaire = output_path.read_text(encoding="utf-8")
    assert "## One Collection For Parts 1, 2, and 3" in questionnaire
    assert "Do you prefer sad or happy music?" not in questionnaire
    assert "Related Part 3 questions" not in questionnaire
    assert "How do people choose a city to travel to?" not in questionnaire
    assert "### Places: visited place" in questionnaire
    assert "Describe your favorite city that you have visited" in questionnaire
    assert "What person, thing, place, or event can answer these prompts?" in questionnaire
    assert "What 3 concrete details can the AI reuse flexibly?" in questionnaire
    assert "Which details should the AI avoid or never invent?" in questionnaire
