# IELTS Speaking Tailor Usage Notes

## Source Banks

Use `import-bank` to convert each new IELTS question bank into `question_bank.yaml`. The generation pipeline only answers questions present in that normalized bank.

```bash
python3 -m ielts_tailor.cli import-bank \
  --source "/path/to/question-bank.pdf" \
  --region mainland \
  --output data/question_bank.yaml
```

Use `--region all` when the student wants mainland and non-mainland sections together.

## Student Profile

Run `init`, then edit `student_profile.yaml`. Keep entries factual and reusable: hometown, study/work status, comfortable topics, topics to avoid, and real stories that can cover several Part 2 cue cards.

Run `profile-questions` after importing a bank to create a scope-card questionnaire:

```bash
python3 -m ielts_tailor.cli profile-questions \
  --bank data/question_bank.yaml \
  --output student_questionnaire.md
```

The questionnaire asks for:

- One reusable umbrella story per Part 2 scope card.
- Concrete story details the AI may reuse across related cue cards.
- Details the AI should avoid inventing or mentioning.

Use the completed questionnaire to fill `output/profile_responses.yaml` through the web interface or your own YAML editing. The generator uses this one Part 2 collection to write Part 2 first, then Part 3, then Part 1.

## Timing Settings

Defaults are based on 80 words per minute:

- Part 1: about 15 seconds, roughly 20 words.
- Part 2: 1 minute 40 seconds to 1 minute 50 seconds, roughly 133-147 words.
- Part 3: about 40 seconds, roughly 53 words.

Edit `config.yaml` for repeat use:

```yaml
generation:
  speaking_speed_wpm: 80
  timing:
    part1_seconds: 15
    part2_min_seconds: 100
    part2_max_seconds: 110
    part3_seconds: 40
```

Override timing for one run without editing `config.yaml`:

```bash
python3 -m ielts_tailor.cli generate --config config.yaml \
  --wpm 90 \
  --part1-seconds 18 \
  --part2-min-seconds 105 \
  --part2-max-seconds 115 \
  --part3-seconds 45
```

## Full Generation

Set `OPENAI_API_KEY` or the environment variable named in `config.yaml`, then run:

```bash
python3 -m ielts_tailor.cli generate --config config.yaml
```

Outputs are written to the configured output directory:

- `ielts_speaking_answers.md`
- `ielts_speaking_answers.docx`
- `cache/style_guide.yaml`
- `checkpoints/samples.yaml` when checkpoint mode is enabled

## Testing the Pipeline

Automated tests use deterministic fake LLM clients, so they can stress import, coverage, generation validation, Markdown, and DOCX output without spending API credits:

```bash
pytest -q
```

For a manual live smoke test, use a small imported bank first, fill `output/profile_responses.yaml` through the web interface, set the API key environment variable from `config.yaml`, then generate a test sample before full generation:

```bash
python3 -m ielts_tailor.cli web --config config.yaml --no-open
```

The live sample should create `output/ielts_speaking_sample.md` and `output/ielts_speaking_sample.docx`. Review those files for complete Part 1, Part 2, and nested Part 3 coverage before running full generation.

For larger banks, full answer generation is automatically split into smaller Part 2 batches. Adjust `generation.answer_batch_size` if your model is slow or has a small context window:

```yaml
generation:
  answer_batch_size: 8
  max_revision_items: 20
```

`max_revision_items` keeps large full-bank runs usable: small samples can be automatically revised after review, while large complete batches keep the first complete answer set and record the review issues instead of risking another long request.

## Local Web Interface

Start the local browser interface:

```bash
python3 -m ielts_tailor.cli web --config config.yaml
```

By default it opens `http://127.0.0.1:8765/`. Use `--host`, `--port`, or `--no-open` when needed:

```bash
python3 -m ielts_tailor.cli web --config config.yaml --port 9000 --no-open
```

The interface is organized like an online speaking test:

- Setup shows file paths, student profile status, and timing targets.
- Test asks one input question at a time for Part 2 scope-card stories only.
- Results shows live generation progress, then editable Markdown answers after validated output exists.

Autosaved profile responses are written to `output/profile_responses.yaml`. Edited results are saved to `output/ielts_speaking_answers.md`; full generation also writes the existing DOCX output.

## Large Bank Behavior

Part 2 is the primary study unit. The importer keeps Part 3 under each cue card, then the strategy layer identifies the exam scope of each Part 2 prompt and groups compatible prompts into scope cards. This keeps the user input small while still letting generation adapt one true story across many IELTS cue cards.
