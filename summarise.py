#!/usr/bin/env python3
"""Aggregate a probe.py run into the numbers you can quote. Reads nothing from the network."""
import json, sys, collections

path = sys.argv[1] if len(sys.argv) > 1 else "results.jsonl"
rows = [json.loads(l) for l in open(path, encoding="utf-8")]

GH_STANDARD_RATE = 0.006   # USD/min, GitHub's published standard-runner price
PLATFORM_RATE = 0.002      # USD/min, the platform charge that also covers self-hosted runners

print(f"{'repo':<28}{'jobs':>7}{'machine min':>14}{'billable':>10}{'not-GitHub min':>16}{'%':>7}")
print("-" * 82)
tj = tm = tb = 0.0
by_owner = collections.Counter(); sec_by_owner = collections.Counter()
zero_billable = not_github_repos = 0

for r in sorted(rows, key=lambda x: -x["machine_seconds"]):
    m = r["machine_seconds"] / 60
    b = r["billable_ms"] / 60000
    ng = r["seconds_by_owner"]["not-github"] / 60
    print(f"{r['repo']:<28}{r['jobs']:>7}{m:>14,.1f}{b:>10,.1f}{ng:>16,.1f}{100*ng/max(m,.001):>6.1f}%")
    tj += r["jobs"]; tm += m; tb += b
    if b == 0: zero_billable += 1
    if r["by_owner"]["not-github"]: not_github_repos += 1
    for k, v in r["by_owner"].items(): by_owner[k] += v
    for k, v in r["seconds_by_owner"].items(): sec_by_owner[k] += v / 60

print("-" * 82)
print(f"{'TOTAL':<28}{int(tj):>7}{tm:>14,.1f}{tb:>10,.1f}"
      f"{sec_by_owner['not-github']:>16,.1f}{100*sec_by_owner['not-github']/max(tm,.001):>6.1f}%")
print()
print(f"Projects in sample:                  {len(rows)}")
print(f"Projects with billable = 0:          {zero_billable} / {len(rows)}")
print(f"Projects using non-GitHub hardware:  {not_github_repos} / {len(rows)}")
print(f"Machine time:                        {tm:,.0f} min = {tm/60:,.0f} h = {tm/1440:,.1f} days")
print()
print("By who owns the machine:")
for k in ("github-standard", "github-larger", "not-github", "unknown"):
    print(f"  {k:<18} {by_owner[k]:>7} jobs  {sec_by_owner[k]:>12,.1f} min  "
          f"{100*sec_by_owner[k]/max(tm,.001):>5.1f}%")
print()
print("Priced at GitHub's own published rates. This is a conversion, not a bill:")
print(f"  {tm:,.0f} min x {GH_STANDARD_RATE} USD/min (standard runner) = {tm*GH_STANDARD_RATE:>10,.2f} USD")
print(f"  {tm:,.0f} min x {PLATFORM_RATE} USD/min (platform charge)   = {tm*PLATFORM_RATE:>10,.2f} USD")
print(f"  Actually billed by GitHub:                        {tb:>10,.2f} min")
print()
print("Named ownership, straight from the API:")
seen = set()
for r in rows:
    for s in r["samples"]:
        key = (r["repo"], s.get("owner"), s.get("group"), str(s.get("labels")))
        if key in seen: continue
        seen.add(key)
        print(f"  {r['repo']:<24} {str(s.get('owner')):<16} group={str(s.get('group')):<32} {s.get('labels')}")
print()
truncated = [r["repo"] for r in rows
             if r["by_owner"]["not-github"] + r["by_owner"]["github-larger"] > len(r["samples"])]
if truncated:
    print("SAMPLES TRUNCATED for these repos, so their ownership split is inference, not proof:")
    for t in truncated: print(f"  {t}")
    print("  Re-run with a higher --max-samples to settle it.")
print()
print("Read before quoting any of this:")
print(" 1. The sample is the N most recent runs per project. Not a time window, not random.")
print(" 2. Machine time is summed job duration, not wall clock. Jobs run in parallel.")
print(" 3. The prices above are a conversion at published rates, not money anyone paid.")
print(" 4. 'not-GitHub' means the runner is outside GitHub's fleet, which is not the same as")
print("    'self-hosted by the project'. Only the group name can tell you which.")
