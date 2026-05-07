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

## Large Bank Behavior

Part 2 is the primary study unit. Related Part 3 questions remain directly under each Part 2 cue card, and adjacent Part 2 blocks are sorted by reusable umbrella-story themes when possible. This preserves exam flow while reducing memory load.
