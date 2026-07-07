# LEDGER — append-only history

> Sole writer: historian. New entries go at the END of this file. Never edit or
> delete a past entry — corrections are new entries referencing the old one.
> Every `change` entry carries its verification evidence; an entry without evidence
> is a rumor.

Entry format:

```
## <YYYY-MM-DD> — <title>
- Type: change | decision | run | postmortem | handoff | note
- Branch/commit: <where the work lives>
- What: <what happened, 1–3 lines>
- Why: <intent / trigger>
- Evidence: <tiers run + results, reviewer verdicts, probe outputs — for changes;
  "n/a" only for notes>
- Pointers: <decisions/NNNN, runs/NNNN, catalog IDs, PRs — whatever deepens the trail>
```

---

## 1970-01-01 — Ledger initialized
- Type: note
- Branch/commit: (install)
- What: Loom installed; memory seeded (STATE, MAP placeholder, failure catalog).
- Why: Framework installation.
- Evidence: n/a
- Pointers: loom README in the framework source repo.
