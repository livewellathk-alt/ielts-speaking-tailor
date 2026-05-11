# IELTS Speaking Tailor

Python CLI for generating personalized bilingual IELTS speaking study documents from a replaceable question bank.

## Quick Start

```bash
python3 -m pip install -e ".[dev]"
python3 -m ielts_tailor.cli init
python3 -m ielts_tailor.cli import-bank --source "/path/to/question-bank.pdf" --region mainland --output data/question_bank.yaml
python3 -m ielts_tailor.cli profile-questions --bank data/question_bank.yaml --output student_questionnaire.md
python3 -m ielts_tailor.cli generate --config config.yaml
```

The generator expects an OpenAI-compatible chat completions API. Set the environment variable named by `config.yaml`, for example `OPENAI_API_KEY`.

If `ielts-tailor` is on your shell PATH, you can use it instead of `python3 -m ielts_tailor.cli`.

To use the local browser interface instead of the CLI-only workflow:

```bash
python3 -m ielts_tailor.cli web --config config.yaml
```

This starts a local server at `http://127.0.0.1:8765/`. The interface is an online-test style workspace for setup, student answer inputs, generation, and editable results saved on your computer.

Default answer timing is IELTS-speaking focused: Part 1 is about 15 seconds, Part 2 is 1:40-1:50, and Part 3 is about 40 seconds at 80 words per minute. Edit `generation.speaking_speed_wpm` and `generation.timing` in `config.yaml`, or override one run:

```bash
python3 -m ielts_tailor.cli generate --config config.yaml \
  --wpm 90 \
  --part1-seconds 18 \
  --part2-min-seconds 105 \
  --part2-max-seconds 115 \
  --part3-seconds 45
```

## Pipeline

The CLI keeps intermediate artifacts explicit so large banks can be debugged and regenerated:

1. Import the PDF/text bank into normalized YAML.
2. Preserve Part 2 blocks with their related Part 3 questions.
3. Identify each Part 2 prompt's exam scope and group compatible prompts into reusable scope cards.
4. Build a global style guide from the student profile.
5. Generate checkpoint samples when enabled.
6. Generate answers, review against IELTS descriptors and local frameworks, revise once, then render Markdown and DOCX.

Run `profile-questions` before generation to create a questionnaire for the student. It now collects only Part 2 scope-card material, so one flexible real story can cover compatible prompts such as an admired person, a great teacher, and an important influence. The generator writes Part 2 first, then adapts the same collection for Part 3 discussion and Part 1 short answers.

The web interface saves editable files under the configured output directory, including `profile_responses.yaml`, `ielts_speaking_answers.md`, and `ielts_speaking_answers.docx`. While generation runs, the Results view shows live stages for scope analysis, style guide, answer batches, quality review, and output rendering.

## Quality Controls

- OpenAI-compatible JSON mode is requested for every LLM call.
- The pipeline validates required JSON keys for each schema and retries incomplete responses.
- A separate reviewer model can be set with `llm.reviewer_model`.
- Low generation temperature is used by default.
- `output/cache/style_guide.yaml` keeps the student voice stable across large batches.
