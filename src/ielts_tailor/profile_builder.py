from __future__ import annotations

from copy import deepcopy
from typing import Any


def build_generation_profile(base_profile: dict[str, Any], responses: dict[str, Any] | None) -> dict[str, Any]:
    responses = responses or {}
    profile = deepcopy(base_profile or {})
    profile["browser_responses"] = responses
    profile.setdefault("stories", [])
    profile.setdefault("theme_answers", {})
    avoid_details = []
    for theme, answer in responses.get("umbrella_stories", {}).items():
        story = {
            "id": f"response_{theme}",
            "title": f"Browser response for {theme}",
            "details": _story_details(answer),
            "themes": [theme],
        }
        profile["stories"] = [existing for existing in profile["stories"] if existing.get("id") != story["id"]]
        profile["stories"].append(story)
        profile["theme_answers"].setdefault(theme, {})
        profile["theme_answers"][theme]["umbrella_story"] = answer
        if answer.get("avoid"):
            avoid_details.append(str(answer["avoid"]))
    part3_by_theme = profile.setdefault("theme_answers", {})
    for question_id, answer in responses.get("part3", {}).items():
        theme = _theme_from_question_id(question_id)
        part3_by_theme.setdefault(theme, {}).setdefault("part3", {})[question_id] = answer
    if avoid_details:
        speaking_preferences = profile.setdefault("speaking_preferences", {})
        existing_avoid = speaking_preferences.get("avoid_topics", [])
        speaking_preferences["avoid_topics"] = list(dict.fromkeys([*existing_avoid, *avoid_details]))
    return profile


def _story_details(answer: dict[str, Any]) -> str:
    parts = [
        f"Story: {answer.get('story', '')}",
        f"Details: {answer.get('details', '')}",
        f"Feeling/result/lesson: {answer.get('lesson', '')}",
        f"Do not invent or mention: {answer.get('avoid', '')}",
    ]
    return "\n".join(part for part in parts if not part.endswith(": "))


def _theme_from_question_id(question_id: str) -> str:
    if "app" in question_id or "tech" in question_id or "website" in question_id:
        return "technology_media"
    if "city" in question_id or "travel" in question_id:
        return "city_travel"
    return "general_experience"
