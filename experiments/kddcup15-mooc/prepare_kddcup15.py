#!/usr/bin/env python3
"""Convert the KDD Cup 2015 (XuetangX MOOC dropout) raw files into the
sequence-motif-discovery JSONL format: one record per enrollment, one plain
token per event, epoch-second times.

    python prepare_kddcup15.py RAW_DIR/train --truth truth_train.csv --out train.jsonl
    python prepare_kddcup15.py RAW_DIR/test  --truth truth_test.csv  --out test.jsonl

RAW_DIR/<split>/ must contain log_<split>.csv, enrollment_<split>.csv, date.csv
and the truth file. Labels: dropout (no activity in the 10 days after course
end) vs persist.

Token design (kept deliberately generic — single token per event):
  - the raw `event` column value: navigate/access/problem/video/page_close/
    discussion/wiki
  - optional `--source-tokens`: use "<event>@<source>" instead (server/browser)
  - a final synthetic `course_end` event stamped at 23:59:59 of the course's
    last day (from date.csv). Course end is known scheduling metadata, not
    outcome; it lets time-gap features express trailing inactivity ("went
    silent long before the course ended"), which plain sequences can't encode
    because they simply stop at the last event.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import datetime


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("raw_dir", help="directory with log/enrollment/date csvs")
    ap.add_argument("--truth", required=True, help="truth csv (enrollment_id,label)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--source-tokens", action="store_true",
                    help="tokens like problem@server instead of problem")
    ap.add_argument("--no-course-end", action="store_true",
                    help="do not append the synthetic course_end event")
    args = ap.parse_args()

    split = "train" if os.path.exists(
        os.path.join(args.raw_dir, "log_train.csv")) else "test"

    truth = {}
    with open(os.path.join(args.raw_dir, args.truth)) as f:
        for row in csv.reader(f):
            if len(row) == 2:
                truth[row[0]] = "dropout" if row[1].strip() == "1" else "persist"

    course_of = {}
    with open(os.path.join(args.raw_dir, f"enrollment_{split}.csv")) as f:
        for r in csv.DictReader(f):
            course_of[r["enrollment_id"]] = r["course_id"]

    course_end = {}
    with open(os.path.join(args.raw_dir, "date.csv")) as f:
        for r in csv.DictReader(f):
            end = datetime.fromisoformat(r["to"] + "T23:59:59")
            course_end[r["course_id"]] = end.timestamp()

    # log files are grouped by enrollment_id and time-sorted within a group,
    # but stream defensively: accumulate per enrollment, sort on flush
    seqs = {}
    with open(os.path.join(args.raw_dir, f"log_{split}.csv")) as f:
        for r in csv.DictReader(f):
            eid = r["enrollment_id"]
            tok = (f"{r['event']}@{r['source']}" if args.source_tokens
                   else r["event"])
            t = datetime.fromisoformat(r["time"]).timestamp()
            seqs.setdefault(eid, []).append((t, tok))

    n, skipped = 0, 0
    with open(args.out, "w") as out:
        for eid, label in truth.items():
            evs = seqs.get(eid)
            if not evs:
                skipped += 1
                continue
            evs.sort(key=lambda x: x[0])
            events = [tok for _, tok in evs]
            times = [t for t, _ in evs]
            if not args.no_course_end:
                end = course_end.get(course_of.get(eid), times[-1])
                events.append("course_end")
                times.append(max(end, times[-1]))
            out.write(json.dumps({"id": eid, "label": label, "events": events,
                                  "times": times}) + "\n")
            n += 1
    print(f"wrote {n} enrollments to {args.out} "
          f"({skipped} truth ids had no log events)")


if __name__ == "__main__":
    main()
