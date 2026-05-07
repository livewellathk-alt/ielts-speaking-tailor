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

## Pipeline

The CLI keeps intermediate artifacts explicit so large banks can be debugged and regenerated:

1. Import the PDF/text bank into normalized YAML.
2. Preserve Part 2 blocks with their related Part 3 questions.
3. Cluster Part 2 topics by reusable umbrella-story potential.
4. Build a global style guide from the student profile.
5. Generate checkpoint samples when enabled.
6. Generate answers, review against IELTS descriptors and local frameworks, revise once, then render Markdown and DOCX.

## Quality Controls

- OpenAI-compatible JSON mode is requested for every LLM call.
- The pipeline validates required JSON keys for each schema and retries incomplete responses.
- A separate reviewer model can be set with `llm.reviewer_model`.
- Low generation temperature is used by default.
- `output/cache/style_guide.yaml` keeps the student voice stable across large batches.
