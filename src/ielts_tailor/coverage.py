from __future__ import annotations

from typing import Any

from .questionnaire import build_questionnaire_model
from .strategy import SCOPE_LABELS


THEME_LABELS = {
    "city_travel": "城市/旅行",
    "people_relationships": "人物/关系",
    "technology_media": "科技/媒体",
    "work_study": "学习/工作",
    "rules_society": "规则/社会",
    "lifestyle_activity": "生活/活动",
    "general_experience": "通用经历",
}

LEGACY_THEME_ALIASES = {
    "scope_places_visited_place": ["city_travel"],
    "scope_objects_useful_object": ["technology_media"],
    "scope_people_known_person": ["people_relationships", "work_study"],
    "scope_people_famous_person": ["people_relationships"],
    "scope_personal_preference": ["lifestyle_activity"],
    "scope_general_experience": ["general_experience"],
}


def analyze_coverage(bank: dict[str, Any], responses: dict[str, Any] | None) -> dict[str, Any]:
    responses = responses or {}
    questionnaire = build_questionnaire_model(bank)
    part1_report = _part1_collection_coverage(questionnaire.get("part1", []))
    theme_reports = [
        _theme_coverage(
            story,
            responses.get("umbrella_stories", {}),
            responses.get("part3", {}),
            responses.get("part3_scope_defaults", {}),
        )
        for story in questionnaire.get("umbrella_stories", [])
    ]
    theme_score = _average([report["score"] for report in theme_reports])
    overall = round(part1_report["score"] * 0.15 + theme_score * 0.85)
    followups = []
    for report in theme_reports:
        for item in report["missing"]:
            followups.append(f"{report['label']}：请补充{item}。")
    can_generate_sample = overall >= 70 and not any(report["status"] == "资料不足" for report in theme_reports)
    can_generate_full = overall >= 85 and all(report["status"] == "资料充足" for report in theme_reports)
    if can_generate_full:
        status = "可以全量生成"
    elif can_generate_sample:
        status = "可以生成测试样本"
    else:
        status = "资料不足"
    return {
        "overall_percent": overall,
        "status": status,
        "can_generate_sample": can_generate_sample,
        "can_generate_full": can_generate_full,
        "part1": part1_report,
        "theme_reports": theme_reports,
        "followups": followups[:8],
    }


def _part1_coverage(questions: list[dict[str, Any]], responses: dict[str, Any]) -> dict[str, Any]:
    total = len(questions)
    answered = 0
    for question in questions:
        answer = responses.get(question.get("question_id", ""), {})
        if _has_text(answer.get("direct_answer")) and _has_text(answer.get("example")):
            answered += 1
    score = 100 if total == 0 else round(answered / total * 100)
    return {"total": total, "answered": answered, "missing_count": max(total - answered, 0), "score": score}


def _part1_collection_coverage(questions: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(questions)
    return {
        "total": total,
        "answered": total,
        "missing_count": 0,
        "score": 100,
        "collection_strategy": "generated_from_part2_scope_collection",
    }


def _theme_coverage(
    story: dict[str, Any],
    story_responses: dict[str, Any],
    part3_responses: dict[str, Any],
    part3_scope_defaults: dict[str, Any],
) -> dict[str, Any]:
    theme = story.get("scope_id", story["theme"])
    response = _response_for_scope(story_responses, theme)
    missing = []
    story_score = 0
    if _has_text(response.get("story"), min_chars=20):
        story_score += 35
    else:
        missing.append("一个真实、可复用的 Part 2 故事")
    if _detail_count(response.get("details")) >= 3:
        story_score += 30
    else:
        missing.append("三个具体细节")
    if _has_text(response.get("lesson"), min_chars=10):
        story_score += 25
    else:
        missing.append("感受、结果或收获")
    if _has_text(response.get("avoid")):
        story_score += 10
    part3_total = len(story.get("part3_questions", []))
    part3_answered = part3_total
    part3_score = 100
    combined = story_score
    if combined >= 85:
        status = "资料充足"
    elif combined >= 70:
        status = "可以测试"
    else:
        status = "资料不足"
    return {
        "theme": theme,
        "scope_id": theme,
        "label": SCOPE_LABELS.get(theme, THEME_LABELS.get(theme, theme.replace("_", "/"))),
        "score": combined,
        "story_score": story_score,
        "part3_score": part3_score,
        "part3_answered": part3_answered,
        "part3_total": part3_total,
        "status": status,
        "missing": missing,
    }


def _response_for_scope(responses: dict[str, Any], scope_id: str) -> dict[str, Any]:
    if not isinstance(responses, dict):
        return {}
    if isinstance(responses.get(scope_id), dict):
        return responses[scope_id]
    for alias in LEGACY_THEME_ALIASES.get(scope_id, []):
        if isinstance(responses.get(alias), dict):
            return responses[alias]
    return {}


def _average(values: list[int]) -> int:
    return 100 if not values else round(sum(values) / len(values))


def _has_text(value: Any, min_chars: int = 3) -> bool:
    return isinstance(value, str) and len(value.strip()) >= min_chars


def _detail_count(value: Any) -> int:
    if isinstance(value, list):
        return len([item for item in value if str(item).strip()])
    if not isinstance(value, str):
        return 0
    separators = [",", "，", "、", ";", "；", "\n"]
    normalized = value
    for separator in separators[1:]:
        normalized = normalized.replace(separator, separators[0])
    return len([item for item in normalized.split(",") if item.strip()])
