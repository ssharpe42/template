# KDD Cup 2015 MOOC dropout — real-data test of the sequence-motif skill

This experiment tests the `sequence-motif-discovery` skill (deterministic contrast
mining + LLM propose→verify loop) on a public continuous-time discrete-event benchmark,
with **weaker models (Claude Haiku / Sonnet) as the in-loop LLM** and the orchestration
following the skill exactly. Results: `REPORT.md`.

## Dataset

[KDD Cup 2015](https://www.biendata.xyz/competition/kddcup2015/) (XuetangX MOOC
dropout prediction): per-enrollment logs of 7 event types
(`navigate access problem video page_close discussion wiki`) with second-resolution
timestamps over ~30-day courses. Label: `dropout` = no activity in the 10 days after
the course ends (79% of enrollments). This mirror is a consistent subset of the
original release (72,395 train / 24,013 test enrollments, 39 courses — the original
had 200,904 enrollments total) and includes the post-competition **test labels**, so
evaluation runs on the official test split.

Provenance (the official site no longer hosts the data):

```
git clone https://github.com/noonlay/MOOCdata.git   # LFS pointer only
curl -L -o KDDCUP2015data.7z \
  https://media.githubusercontent.com/media/noonlay/MOOCdata/main/KDDCUP2015data.7z
# sha256: dba6afe9562e96c3b6b5c1a243c465e4496b780e3374003d105f887573d01655
python -c "import py7zr; py7zr.SevenZipFile('KDDCUP2015data.7z').extractall('raw')"
```

## Reproduction

```bash
SK=../../.claude/skills/sequence-motif-discovery/scripts

# 1. convert to skill JSONL (generic single-token events, epoch times).
#    --no-course-end omits the synthetic course-calendar event: the user ruled
#    trailing-silence-before-course-end leakage-adjacent (the label itself is
#    "10 more days of silence"), so headline results exclude it.
python prepare_kddcup15.py raw/KDDCUP2015data/train --truth truth_train.csv \
  --out train.jsonl --no-course-end
python prepare_kddcup15.py raw/KDDCUP2015data/test --truth truth_test.csv \
  --out test.jsonl --no-course-end

# 2. profile, then mine candidates (both directions) on the train split
python $SK/profile_data.py train.jsonl --pos-label dropout
python $SK/mine_candidates.py train.jsonl --pos-label dropout --direction both \
  --min-pos-support 0.05 --max-len 3 --top 60 --gap-buckets '1h,1d,7d' \
  --split 0.3 --seed 42 --sample 8000 --out cands_len3.json
python $SK/mine_candidates.py train.jsonl --pos-label dropout --direction both \
  --min-pos-support 0.05 --max-len 4 --max-gap 3 --top 60 --gap-buckets '1h,1d,7d' \
  --split 0.3 --seed 42 --sample 8000 --out cands_len4gap3.json

# 3. LLM loop: a weaker model (Haiku/Sonnet subagent) reads the profile + candidate
#    tables + sample sequences and proposes DSL hypotheses; each round is verified with
#    $SK/verify_patterns.py (same --split/--seed/--gap-buckets) and the train-split
#    stats are fed back. 3 rounds here. Agent outputs: rulesets/*.json
python $SK/verify_patterns.py train.jsonl --patterns rulesets/haiku_r3.json \
  --pos-label dropout --split 0.3 --seed 42 --gap-buckets '1h,1d,7d'

# 4. deterministic rule-set selection (same procedure for every arm)
python $SK/select_ruleset.py train.jsonl \
  --patterns rulesets/haiku_r3.json cands_len3.json cands_len4gap3.json \
  --pos-label dropout --split 0.3 --seed 42 --gap-buckets '1h,1d,7d' \
  --max-rules 12 --out rulesets/final_haiku.json

# 5. benchmark evaluation: fit rule weights on official train, AUC on official test
python $SK/evaluate_ruleset.py test.jsonl --patterns rulesets/final_haiku.json \
  --pos-label dropout --fit-data train.jsonl --gap-buckets '1h,1d,7d'

# baseline for context (pure-python LR on classic count features)
python baseline_counts.py train.jsonl test.jsonl
```

## Arms compared

| arm | candidate source |
|---|---|
| mined-only | PrefixSpan candidates → select_ruleset (no LLM) |
| mined + Haiku loop | candidates + 3 propose→verify rounds, Haiku as in-loop LLM |
| mined + Sonnet loop | candidates + 2 propose→verify rounds, Sonnet as in-loop LLM |
| count-feature LR | classic engagement counts (no sequence structure) |

Key methodological point exercised here: on the leakage-cleaned data PrefixSpan finds
**zero dropout-direction subsequences** (dropouts do less of everything, so no
subsequence is enriched), while the LLM loop contributes `absent`-based negation rules
("never worked a problem", "never returned after a day away") that carry the entire
dropout direction — a construct sequence mining cannot express.
