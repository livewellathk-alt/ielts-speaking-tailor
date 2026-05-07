from __future__ import annotations

import re
from copy import deepcopy
from typing import Any


THEME_KEYWORDS = [
    ("city_travel", {"city", "cities", "urban", "tourist", "travel", "visited", "place"}),
    ("people_relationships", {"person", "people", "friend", "family", "child", "teacher"}),
    ("technology_media", {"video", "app", "technology", "phone", "social", "media", "website"}),
    ("work_study", {"job", "work", "school", "student", "teacher", "career"}),
    ("rules_society", {"law", "rule", "government", "society"}),
    ("lifestyle_activity", {"music", "sport", "hobby", "food", "morning", "team"}),
]


def framework_for_part3_question(question: str) -> str:
    q = question.lower()
    if any(phrase in q for phrase in ["advantage", "disadvantage", "pros", "cons", "positive and negative", "benefits and drawbacks"]):
        return "AREA-Pivot"
    if any(phrase in q for phrase in ["how can", "what can be done", "solve", "measures", "should governments", "should parents"]):
        return "AREA-Assessment"
    if any(phrase in q for phrase in ["difference", "compare", "which is more", "better than", "young and old"]):
        return "AREA-Adjustment"
    return "AREA-Alternative"


def cluster_part2_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clustered = []
    for block in blocks:
        item = deepcopy(block)
        theme = _theme_for_block(item)
        item["theme"] = theme
        item["umbrella_story"] = f"story_{theme}"
        for question in item.get("part3", []):
            question["framework"] = framework_for_part3_question(question["question"])
        clustered.append(item)
    return clustered


def sort_blocks_for_study(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(blocks, key=lambda block: (block.get("umbrella_story", ""), block.get("source_order", 0)))


def _theme_for_block(block: dict[str, Any]) -> str:
    text = " ".join(
        [
            str(block.get("title_zh", "")),
            str(block.get("part2", {}).get("prompt", "")),
            " ".join(question.get("question", "") for question in block.get("part3", [])),
        ]
    ).lower()
    words = set(re.findall(r"[a-z]+", text))
    best_theme = "general_experience"
    best_score = 0
    for theme, keywords in THEME_KEYWORDS:
        score = len(words & keywords)
        if score > best_score:
            best_theme = theme
            best_score = score
    return best_theme
