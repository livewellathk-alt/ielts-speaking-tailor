from ielts_tailor.strategy import (
    cluster_part2_blocks,
    framework_for_part3_question,
    sort_blocks_for_study,
)


def block(block_id, title, prompt, part3_questions):
    return {
        "id": block_id,
        "title_zh": title,
        "source_order": int(block_id.split("_")[-1]),
        "part2": {"prompt": prompt, "cue_points": []},
        "part3": [{"id": f"{block_id}_p3_{i}", "question": q} for i, q in enumerate(part3_questions, 1)],
    }


def test_framework_for_part3_question_selects_area_variant():
    assert framework_for_part3_question("What are the advantages and disadvantages of apps?") == "AREA-Pivot"
    assert framework_for_part3_question("How can we solve traffic problems?") == "AREA-Assessment"
    assert framework_for_part3_question("What is the difference between cities and villages?") == "AREA-Adjustment"
    assert framework_for_part3_question("Do you think this will change in the future?") == "AREA-Alternative"
    assert framework_for_part3_question("Why do people like online videos?") == "AREA-Alternative"


def test_cluster_and_sort_keep_part3_under_part2_and_group_memory_reuse():
    blocks = [
        block("p2_2", "有趣视频", "Describe an interesting video", ["What kind of videos do people like?"]),
        block("p2_1", "喜欢的城市", "Describe your favorite city that you have visited", ["How do people choose a city to travel to?"]),
        block("p2_3", "有趣城市", "Describe an interesting city", ["Do tourists prefer modern or historical cities?"]),
    ]

    clustered = cluster_part2_blocks(blocks)
    sorted_blocks = sort_blocks_for_study(clustered)

    assert [item["id"] for item in sorted_blocks] == ["p2_1", "p2_3", "p2_2"]
    assert sorted_blocks[0]["umbrella_story"] == sorted_blocks[1]["umbrella_story"]
    assert sorted_blocks[0]["part3"][0]["question"] == "How do people choose a city to travel to?"


def test_people_scope_groups_known_person_teacher_admired_and_influence_prompts():
    blocks = [
        block("p2_1", "敬佩的人", "Describe a person you admire", ["Why do people admire teachers?"]),
        block("p2_2", "好老师", "Describe your favourite teacher from school", ["What makes a teacher great?"]),
        block("p2_3", "重要影响", "Describe someone who has had an important influence on your life", ["Do families influence children?"]),
    ]

    clustered = cluster_part2_blocks(blocks)

    assert {item["scope_id"] for item in clustered} == {"scope_people_known_person"}
    assert all(item["umbrella_story"] == "story_scope_people_known_person" for item in clustered)
    assert {"known_person", "teacher", "admired_person", "important_influence"} <= {
        tag for item in clustered for tag in item["compatibility_tags"]
    }


def test_people_scope_keeps_famous_person_separate_from_known_person():
    blocks = [
        block("p2_1", "敬佩的人", "Describe a person you admire", []),
        block("p2_2", "名人", "Describe a famous person you would like to meet", []),
    ]

    clustered = cluster_part2_blocks(blocks)

    assert {item["id"]: item["scope_id"] for item in clustered} == {
        "p2_1": "scope_people_known_person",
        "p2_2": "scope_people_famous_person",
    }


def test_scope_classification_does_not_merge_objects_places_and_events():
    blocks = [
        block("p2_1", "有用的软件", "Describe an app or website you often use", []),
        block("p2_2", "喜欢的城市", "Describe your favorite city that you have visited", []),
        block("p2_3", "难忘事件", "Describe a memorable event from your childhood", []),
    ]

    clustered = cluster_part2_blocks(blocks)

    assert {item["id"]: item["scope_id"] for item in clustered} == {
        "p2_1": "scope_objects_useful_object",
        "p2_2": "scope_places_visited_place",
        "p2_3": "scope_events_memorable_event",
    }


def test_scale_sorting_handles_many_linked_part2_part3_blocks():
    blocks = [
        block(f"p2_{i}", f"Topic {i}", f"Describe a city experience number {i}", [
            f"Why do people visit city {i}?",
            f"What are the advantages and disadvantages of city travel {i}?",
            f"How can cities improve tourism {i}?",
        ])
        for i in range(1, 61)
    ]

    sorted_blocks = sort_blocks_for_study(cluster_part2_blocks(blocks))

    assert len(sorted_blocks) == 60
    assert sum(len(item["part3"]) for item in sorted_blocks) == 180
    assert all("part3" in item and len(item["part3"]) == 3 for item in sorted_blocks)
