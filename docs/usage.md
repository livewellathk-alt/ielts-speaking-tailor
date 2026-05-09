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

Run `profile-questions` after importing a bank to create a theme-specific questionnaire:

```bash
python3 -m ielts_tailor.cli profile-questions \
  --bank data/question_bank.yaml \
  --output student_questionnaire.md
```

The questionnaire asks for:

- Part 1 direct answers, reasons, examples, and details to avoid.
- One reusable umbrella story per Part 2 theme.
- Concrete story details the AI may reuse across related cue cards.
- Natural opinions and examples for related Part 3 questions.

Use the completed questionnaire to fill `student_profile.yaml` before running full generation.

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
- Test asks one input question at a time for Part 1, Part 2 umbrella stories, and Part 3 opinions.
- Results shows editable Markdown answers and saves edits locally.

Autosaved profile responses are written to `output/profile_responses.yaml`. Edited results are saved to `output/ielts_speaking_answers.md`; full generation also writes the existing DOCX output.

## Large Bank Behavior

Part 2 is the primary study unit. Related Part 3 questions remain directly under each Part 2 cue card, and adjacent Part 2 blocks are sorted by reusable umbrella-story themes when possible. This preserves exam flow while reducing memory load.
