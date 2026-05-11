from __future__ import annotations

import re
from copy import deepcopy
from typing import Any


SCOPE_LABELS = {
    "scope_people_known_person": "People: known person",
    "scope_people_famous_person": "People: famous person",
    "scope_objects_useful_object": "Objects: useful object",
    "scope_events_memorable_event": "Events and moments: memorable event",
    "scope_places_visited_place": "Places: visited place",
    "scope_personal_preference": "Personal: preference or habit",
    "scope_general_experience": "General: flexible experience",
}

SCOPE_SORT_ORDER = {
    "scope_people_known_person": 10,
    "scope_people_famous_person": 11,
    "scope_places_visited_place": 20,
    "scope_objects_useful_object": 30,
    "scope_events_memorable_event": 40,
    "scope_personal_preference": 50,
    "scope_general_experience": 90,
}


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
        scope = analyze_part2_scope(item)
        item.update(scope)
        item["theme"] = scope["scope_id"]
        item["umbrella_story"] = f"story_{scope['scope_id']}"
        for question in item.get("part3", []):
            question["framework"] = framework_for_part3_question(question["question"])
        clustered.append(item)
    return clustered


def sort_blocks_for_study(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        blocks,
        key=lambda block: (
            SCOPE_SORT_ORDER.get(block.get("scope_id", ""), 99),
            block.get("umbrella_story", ""),
            block.get("source_order", 0),
        ),
    )


def analyze_part2_scope(block: dict[str, Any]) -> dict[str, Any]:
    text = _scope_text(block)
    words = set(re.findall(r"[a-z]+", text))
    tags = _compatibility_tags(text, words)
    if {"person", "people", "someone", "friend", "family", "teacher", "child", "elderly", "celebrity", "famous", "star"} & words:
        if {"famous", "celebrity", "star", "news", "foreign"} & words:
            scope_id = "scope_people_famous_person"
        else:
            scope_id = "scope_people_known_person"
            tags.add("known_person")
    elif {"city", "cities", "place", "travel", "visited", "tourist", "country", "building", "home"} & words:
        scope_id = "scope_places_visited_place"
        tags.add("visited_place")
    elif {"app", "website", "phone", "technology", "object", "thing", "gift", "item", "book", "video"} & words:
        scope_id = "scope_objects_useful_object"
        tags.add("useful_object")
    elif {"event", "moment", "experience", "childhood", "celebration", "party", "competition", "situation"} & words:
        scope_id = "scope_events_memorable_event"
        tags.add("memorable_event")
    elif {"music", "sport", "hobby", "food", "morning", "habit", "routine"} & words:
        scope_id = "scope_personal_preference"
        tags.add("personal_preference")
    else:
        scope_id = "scope_general_experience"
        tags.add("general_experience")
    return {
        "scope_id": scope_id,
        "scope_label": SCOPE_LABELS[scope_id],
        "scope_category": scope_id.split("_", 2)[1],
        "compatibility_tags": sorted(tags),
        "why_reusable": _why_reusable(scope_id),
    }


def _theme_for_block(block: dict[str, Any]) -> str:
    if block.get("theme"):
        return str(block["theme"])
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


def _scope_text(block: dict[str, Any]) -> str:
    part2 = block.get("part2", {}) if isinstance(block.get("part2"), dict) else {}
    return " ".join(
        [
            str(block.get("title_zh", "")),
            str(part2.get("prompt", "")),
            " ".join(str(point) for point in part2.get("cue_points", [])),
        ]
    ).lower()


def _compatibility_tags(text: str, words: set[str]) -> set[str]:
    tags: set[str] = set()
    if {"teacher", "professor", "mentor"} & words:
        tags.add("teacher")
    if {"admire", "admired"} & words:
        tags.add("admired_person")
    if "important influence" in text or {"influence", "influenced"} & words:
        tags.add("important_influence")
    if {"family", "father", "mother", "parent", "brother", "sister"} & words:
        tags.add("family")
    if {"friend", "classmate"} & words:
        tags.add("friend")
    if {"famous", "celebrity", "star", "news"} & words:
        tags.add("famous_person")
    if {"city", "cities", "travel", "visited", "tourist"} & words:
        tags.add("visited_place")
    if {"app", "website", "technology", "phone"} & words:
        tags.add("digital_tool")
    if {"useful", "helpful"} & words:
        tags.add("useful_object")
    if {"event", "moment", "childhood", "memorable"} & words:
        tags.add("memorable_event")
    return tags


def _why_reusable(scope_id: str) -> str:
    reasons = {
        "scope_people_known_person": "One real known person can be adapted for admired person, teacher, helper, family, friend, or influence prompts when the details fit.",
        "scope_people_famous_person": "Famous-person prompts need public facts and should stay separate from personal stories about people the student knows.",
        "scope_objects_useful_object": "One useful object or digital tool can answer prompts about apps, websites, technology, gifts, or helpful things.",
        "scope_events_memorable_event": "One memorable event can be reshaped around what happened, why it mattered, and what the student learned.",
        "scope_places_visited_place": "One visited place can cover city, travel, tourist, and favorite-place prompts by changing the emphasis.",
        "scope_personal_preference": "One personal habit or preference can support prompts about hobbies, routines, music, sport, or food.",
        "scope_general_experience": "This prompt needs a flexible real experience because it does not strongly match a narrower IELTS scope.",
    }
    return reasons.get(scope_id, reasons["scope_general_experience"])
