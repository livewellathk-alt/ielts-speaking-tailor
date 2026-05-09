from __future__ import annotations

from typing import Any

from .strategy import cluster_part2_blocks


def build_questionnaire_model(bank: dict[str, Any]) -> dict[str, Any]:
    clustered = cluster_part2_blocks(bank.get("part2_blocks", []))
    part1 = [
        {
            "topic_id": topic.get("id", ""),
            "topic_title": topic.get("title", topic.get("id", "Part 1 Topic")),
            "question_id": question.get("id", ""),
            "question": question.get("question", ""),
        }
        for topic in bank.get("part1_topics", [])
        for question in topic.get("questions", [])
    ]
    themes = sorted({block.get("theme", "general_experience") for block in clustered})
    umbrella_stories = []
    for theme in themes:
        theme_blocks = [block for block in clustered if block.get("theme") == theme]
        umbrella_stories.append(
            {
                "theme": theme,
                "part2_prompts": [
                    block.get("part2", {}).get("prompt", block.get("title_zh", block.get("id", "Part 2")))
                    for block in theme_blocks
                ],
                "part3_questions": [
                    {
                        "question_id": question.get("id", ""),
                        "question": question.get("question", ""),
                        "framework": question.get("framework", ""),
                    }
                    for block in theme_blocks
                    for question in block.get("part3", [])
                ],
            }
        )
    return {"part1": part1, "umbrella_stories": umbrella_stories}


def build_profile_questionnaire_markdown(bank: dict[str, Any]) -> str:
    model = build_questionnaire_model(bank)
    lines = [
        "# IELTS Speaking Tailor Profile Questions",
        "",
        "## Core",
        "",
        "- What do you study or do for work?",
        "- Where are you from, and what details can you comfortably repeat in answers?",
        "- Which topics should the system avoid?",
        "",
        "## Part 1 Answer Inputs",
        "",
        "Use these prompts to give the AI facts, preferences, and examples. Short notes are enough.",
        "",
    ]
    current_topic = None
    for question in model["part1"]:
        if question["topic_title"] != current_topic:
            current_topic = question["topic_title"]
            lines.extend([f"### {current_topic}", ""])
        lines.extend(
            [
                f"- Question: {question['question']}",
                "  - What is your direct answer?",
                "  - What reason or example should the AI use?",
                "  - Which details should the AI avoid or never invent?",
            ]
        )
    lines.extend(
        [
            "",
            "## Umbrella Story Inputs",
            "",
            "Give one real reusable story per theme. The AI will adapt these stories across matching Part 2 prompts and related Part 3 answers.",
            "",
        ]
    )
    for story in model["umbrella_stories"]:
        lines.extend(
            [
                f"### {story['theme']}",
                "",
                "- What real personal story could represent this theme for 1 minute 40 seconds to 1 minute 50 seconds?",
                "- When and where did it happen?",
                "- What 3 concrete details can the AI reuse?",
                "- What feeling, result, or lesson can the AI reuse?",
                "- Which details should the AI avoid or never invent?",
                "- Which English words or phrases do you already use comfortably for this theme?",
                "",
                "Matching Part 2 prompts:",
            ]
        )
        for prompt in story["part2_prompts"]:
            lines.append(f"- {prompt}")
        lines.extend(["", "Related Part 3 opinion inputs:", ""])
        for question in story["part3_questions"]:
            lines.extend(
                [
                    f"- Question: {question['question']}",
                    "  - What is your natural opinion?",
                    "  - What example or comparison can support it?",
                ]
            )
        lines.append("")
    return "\n".join(lines).strip() + "\n"
