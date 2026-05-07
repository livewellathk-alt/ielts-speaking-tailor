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
