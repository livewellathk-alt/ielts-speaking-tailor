from pathlib import Path

import yaml
from docx import Document

from ielts_tailor.cli import main
from ielts_tailor.rendering import render_markdown, render_outputs


def answer_payload():
    return {
        "style_guide": {"student_voice": "clear and personal"},
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
    assert "## Umbrella Story Index" in markdown
    assert "### Part 2: 去过的最喜欢的城市" in markdown
    assert markdown.index("Describe your favorite city") < markdown.index("#### Part 3")
    assert "English:" in markdown
    assert "中文:" in markdown
    assert "Memory cues:" in markdown


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
