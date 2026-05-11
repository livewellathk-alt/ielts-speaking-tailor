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
    themes = sorted({block.get("scope_id", block.get("theme", "scope_general_experience")) for block in clustered})
    umbrella_stories = []
    for theme in themes:
        theme_blocks = [block for block in clustered if block.get("scope_id", block.get("theme")) == theme]
        first = theme_blocks[0] if theme_blocks else {}
        umbrella_stories.append(
            {
                "theme": theme,
                "scope_id": theme,
                "scope_label": first.get("scope_label", theme.replace("_", " ").title()),
                "scope_category": first.get("scope_category", "general"),
                "compatibility_tags": sorted(
                    {tag for block in theme_blocks for tag in block.get("compatibility_tags", [])}
                ),
                "why_reusable": first.get("why_reusable", "One real story can be adapted across these related prompts."),
                "matched_prompts": [
                    {
                        "block_id": block.get("id", ""),
                        "title_zh": block.get("title_zh", ""),
                        "prompt": block.get("part2", {}).get("prompt", block.get("title_zh", block.get("id", "Part 2"))),
                        "cue_points": block.get("part2", {}).get("cue_points", []),
                    }
                    for block in theme_blocks
                ],
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
    return {
        "part1": part1,
        "umbrella_stories": umbrella_stories,
        "collection_sequence": ["part2_scope_collection"],
        "collection_strategy": "collect_part2_scope_cards_then_generate_part2_part3_part1",
    }


def build_balanced_questionnaire_model(bank: dict[str, Any], *, max_questions: int = 24, max_part1: int = 6) -> dict[str, Any]:
    """Build a localhost input poll from Part 2 themes only."""
    full = build_questionnaire_model(bank)
    balanced_stories = []
    for story in full["umbrella_stories"][:max_questions]:
        balanced = dict(story)
        balanced["part3_questions"] = []
        balanced_stories.append(balanced)
    total = len(balanced_stories)
    return {
        "metadata": {
            "source": "part2_only",
            "max_questions": max_questions,
            "total_questions": total,
            "part1_questions": 0,
            "part2_story_questions": len(balanced_stories),
            "part3_questions": 0,
        },
        "part1": [],
        "umbrella_stories": balanced_stories,
    }


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
        "## One Collection For Parts 1, 2, and 3",
        "",
        "Collect only Part 2 scope-card material. The AI will write Part 2 first, then adapt the same material for related Part 3 discussion and Part 1 short answers.",
        "",
    ]
    for story in model["umbrella_stories"]:
        lines.extend(
            [
                f"### {story.get('scope_label', story['theme'])}",
                "",
                f"- Scope id: `{story.get('scope_id', story['theme'])}`",
                f"- Why this is reusable: {story.get('why_reusable', '')}",
                "- What person, thing, place, or event can answer these prompts?",
                "- What happened, or what do you usually do with it?",
                "- What 3 concrete details can the AI reuse flexibly?",
                "- What feeling, result, or lesson can the AI reuse?",
                "- Which details should the AI avoid or never invent?",
                "",
                "Matching Part 2 prompts:",
            ]
        )
        for prompt in story["matched_prompts"]:
            cue_points = prompt.get("cue_points", [])
            cue_text = f" Cue points: {'; '.join(cue_points)}" if cue_points else ""
            lines.append(f"- {prompt.get('prompt', '')}{cue_text}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"
