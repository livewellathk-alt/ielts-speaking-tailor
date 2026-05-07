from pathlib import Path

import yaml

from ielts_tailor.bank import import_bank_text, load_question_bank


SAMPLE_BANK = """
一、大陆地区新题

Part 1 5 月在考新题（10 道）

1 P1 Music

Do you prefer sad or happy music?
Does happy music make you feel more excited?

Part 2&3 5 月在考新题（12 道）

1 P2 喜欢或不喜欢的高建筑

Describe a tall building you like or dislike
You should say:
What it is used for
Where it is
What it looks like
And explain why you like/dislike it

P3
Are there many tall buildings in your country?
What are the differences between those tall buildings in your country?

2 P2 有趣视频

Describe an interesting video
You should say:
When and where you watched it
What it is about
Why you watched it
And explain how you feel about it

P3
What kind of videos do people in your country like to watch?
Which is more helpful, watching videos or reading books?

三、 非大陆地区新题

Part 1 5 月在考新题（2 道）

1 P1 Dream and ambition

What was your childhood dream?
"""


def test_import_bank_text_links_part3_to_part2_and_filters_region(tmp_path: Path):
    output = tmp_path / "question_bank.yaml"

    bank = import_bank_text(SAMPLE_BANK, region="mainland", output_path=output)

    assert output.exists()
    assert bank["metadata"]["region_filter"] == "mainland"
    assert [topic["title"] for topic in bank["part1_topics"]] == ["Music"]
    assert len(bank["part2_blocks"]) == 2
    assert bank["part2_blocks"][0]["title_zh"] == "喜欢或不喜欢的高建筑"
    assert bank["part2_blocks"][0]["part2"]["prompt"] == "Describe a tall building you like or dislike"
    assert bank["part2_blocks"][0]["part3"][0]["question"] == "Are there many tall buildings in your country?"
    assert bank["part2_blocks"][0]["source_order"] < bank["part2_blocks"][1]["source_order"]
    assert "Dream and ambition" not in yaml.safe_dump(bank, allow_unicode=True)


def test_load_question_bank_round_trips_yaml(tmp_path: Path):
    output = tmp_path / "question_bank.yaml"
    expected = import_bank_text(SAMPLE_BANK, region="all", output_path=output)

    loaded = load_question_bank(output)

    assert loaded == expected
    assert any(topic["region"] == "non_mainland" for topic in loaded["part1_topics"])
