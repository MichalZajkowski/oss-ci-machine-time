#!/usr/bin/env python3
"""
How much machine time do the pipelines of critical open source consume, who owns the
machines, and what does GitHub record as owed for that time?

Run it with your own token:

    GITHUB_TOKEN=... python3 probe.py --days 30 --max-runs 50 --repos-file repos.txt

The token is only there to raise the rate limit from 60 to 5,000 requests an hour. GitHub's
documentation for these endpoints states they "can be used without authentication or the
aforementioned permissions if only public resources are requested", so a classic token with
no scopes selected is enough.

Sources, all public and documented:
    GET /repos/{r}/actions/runs              inventory of runs; filtered by created=, at most 1,000 results per search
    GET /repos/{r}/actions/runs/{id}/jobs     per-job duration, labels, runner name and group
    GET /repos/{r}/actions/runs/{id}/timing   the billable field; zero in public repos by GitHub's definition (README)
"""
import argparse, json, os, sys, time, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone

try:                                    # Windows consoles are not UTF-8 by default and some
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # runner names are not ASCII
except Exception:
    pass

API = "https://api.github.com"
THROTTLE = [0.15]
MAX_SAMPLES = [40]        # per repo; raise it when a repo has more non-standard jobs than this
TOKEN = os.environ.get("GITHUB_TOKEN", "")
HEADERS = {"User-Agent": "oss-ci-machine-time/1.0",
           "Accept": "application/vnd.github+json",
           "X-GitHub-Api-Version": "2022-11-28"}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"

STANDARD_GROUP = "github actions"          # GitHub's standard hosted fleet reports this group
LARGER_HINTS = ("larger runners", "large runners")   # GitHub's own paid tier, still its hardware


class Rate:
    """Stops before GitHub refuses, rather than after."""
    remaining = None
    reset = None
    calls = 0


def get(url, tries=4):
    for attempt in range(tries):
        if Rate.remaining is not None and Rate.remaining < 20 and Rate.reset:
            wait = max(0, Rate.reset - int(time.time())) + 3
            if wait:
                print(f"    [rate limit] {Rate.remaining} left, waiting {wait}s", flush=True)
                time.sleep(wait)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=30) as f:
                Rate.calls += 1
                time.sleep(THROTTLE[0])
                rem, res = f.headers.get("x-ratelimit-remaining"), f.headers.get("x-ratelimit-reset")
                Rate.remaining = int(rem) if rem and rem.isdigit() else Rate.remaining
                Rate.reset = int(res) if res and res.isdigit() else Rate.reset
                return json.loads(f.read().decode()), True
        except urllib.error.HTTPError as e:
            rem, res = e.headers.get("x-ratelimit-remaining"), e.headers.get("x-ratelimit-reset")
            Rate.remaining = int(rem) if rem and rem.isdigit() else Rate.remaining
            Rate.reset = int(res) if res and res.isdigit() else Rate.reset
            if e.code in (403, 429):
                ra = e.headers.get("retry-after")
                wait = int(ra) if ra and ra.isdigit() else min(60 * (attempt + 1), 300)
                print(f"    [{e.code}] backing off {wait}s", flush=True)
                time.sleep(wait); continue
            if 500 <= e.code < 600:
                time.sleep(5 * (attempt + 1)); continue
            return None, False              # 404, 451 and friends: no Actions, or no access
        except Exception:
            time.sleep(3 * (attempt + 1))
    return None, False


def seconds(a, b):
    try:
        return (datetime.fromisoformat(b.replace("Z", "+00:00"))
                - datetime.fromisoformat(a.replace("Z", "+00:00"))).total_seconds()
    except Exception:
        return None


def classify(job):
    """Three categories instead of a guess. runner_group_name decides, not the label.

    A runner registered by a repository or an organisation lands in the group 'default'
    unless someone names it otherwise, so anything that is neither GitHub's standard fleet
    nor its larger-runner tier is hardware GitHub does not own.
    """
    group = (job.get("runner_group_name") or "").strip()
    name = (job.get("runner_name") or "").strip()
    if not group and not name:
        return "unknown", "no runner_name and no runner_group_name"
    if group.lower() == STANDARD_GROUP or name.startswith("GitHub Actions"):
        return "github-standard", f"group={group!r}"
    if any(h in group.lower() for h in LARGER_HINTS):
        return "github-larger", f"group={group!r}, GitHub's own paid tier"
    return "not-github", f"group={group!r} runner={name[:28]!r}"


def probe(repo, days, max_runs):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    out = {"repo": repo, "window_days": days, "since": since,
           "runs_fetched": 0, "runs_total_reported": None, "jobs": 0,
           "machine_seconds": 0.0, "billable_ms": 0, "billable_per_os": {},
           "run_duration_ms": 0,
           "by_owner": {"github-standard": 0, "github-larger": 0, "not-github": 0, "unknown": 0},
           "seconds_by_owner": {"github-standard": 0.0, "github-larger": 0.0,
                                "not-github": 0.0, "unknown": 0.0},
           "runner_name_present": 0, "runner_group_present": 0,
           "samples": [], "labels": {}, "errors": 0}
    page = seen = 0
    page = 1
    while seen < max_runs:
        per = min(100, max_runs - seen)
        data, ok = get(f"{API}/repos/{repo}/actions/runs?per_page={per}&page={page}&created=%3E%3D{since}")
        if not ok or not data:
            out["errors"] += 1; break
        if out["runs_total_reported"] is None:
            out["runs_total_reported"] = data.get("total_count")     # as reported; not capped (LLVM: 272,786)
        runs = data.get("workflow_runs", [])
        if not runs:
            break
        for run in runs:
            seen += 1; out["runs_fetched"] += 1
            jp = 1
            while True:
                jd, ok = get(f"{API}/repos/{repo}/actions/runs/{run['id']}/jobs?per_page=100&page={jp}")
                if not ok or not jd:
                    out["errors"] += 1; break
                jobs = jd.get("jobs", [])
                if not jobs:
                    break
                for job in jobs:
                    s = seconds(job.get("started_at") or "", job.get("completed_at") or "")
                    if not s or s <= 0:
                        continue
                    out["jobs"] += 1; out["machine_seconds"] += s
                    if job.get("runner_name"): out["runner_name_present"] += 1
                    if job.get("runner_group_name"): out["runner_group_present"] += 1
                    owner, why = classify(job)
                    out["by_owner"][owner] += 1; out["seconds_by_owner"][owner] += s
                    lab = str(job.get("labels"))
                    out["labels"][lab] = out["labels"].get(lab, 0) + 1
                    if owner != "github-standard" and len(out["samples"]) < MAX_SAMPLES[0]:
                        out["samples"].append({"run": run["id"], "job": job.get("name", "")[:60],
                                               "runner": job.get("runner_name"),
                                               "group": job.get("runner_group_name"),
                                               "labels": job.get("labels"),
                                               "seconds": round(s, 1), "owner": owner, "why": why})
                if len(jobs) < 100:
                    break
                jp += 1
            timing, ok = get(f"{API}/repos/{repo}/actions/runs/{run['id']}/timing")
            if ok and timing:
                out["run_duration_ms"] += timing.get("run_duration_ms") or 0
                for os_name, v in (timing.get("billable") or {}).items():
                    ms = v.get("total_ms", 0)
                    out["billable_ms"] += ms
                    out["billable_per_os"][os_name] = out["billable_per_os"].get(os_name, 0) + ms
        if len(runs) < per:
            break
        page += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repos", nargs="*")
    ap.add_argument("--repos-file")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--max-runs", type=int, default=50)
    ap.add_argument("--out", default="results.jsonl")
    ap.add_argument("--sleep", type=float, default=0.15,
                    help="pause between requests; keeps you under GitHub's secondary limit")
    ap.add_argument("--max-samples", type=int, default=40,
                    help="per repo, how many non-standard jobs to record in full")
    a = ap.parse_args()
    THROTTLE[0] = a.sleep
    MAX_SAMPLES[0] = a.max_samples

    repos = list(a.repos)
    if a.repos_file:
        with open(a.repos_file, encoding="utf-8") as f:
            repos += [l.strip() for l in f if l.strip() and not l.startswith("#")]
    if not repos:
        repos = ["systemd/systemd"]
    if not TOKEN:
        print("No GITHUB_TOKEN: the limit is 60 requests an hour, enough for about one repo.\n", flush=True)

    est = len(repos) * (max(1, a.max_runs // 100) + 2 * a.max_runs)
    print(f"Plan: {len(repos)} repos, up to {a.max_runs} runs each, {a.days} day window.")
    print(f"Estimated API calls: ~{est:,}. Limit with a token: 5,000/hour.")
    print(f"  -> {'this will wait for a limit reset, roughly %.1f h total' % (est/5000) if est > 5000 else 'fits in one hour, roughly %d min' % (est*(a.sleep+0.35)/60)}\n", flush=True)

    done = set()
    if os.path.exists(a.out):                       # resume after an interruption
        for line in open(a.out, encoding="utf-8"):
            try: done.add(json.loads(line)["repo"])
            except Exception: pass
        if done: print(f"Resuming: {len(done)} repos already done, skipping them.\n", flush=True)

    fh = open(a.out, "a", encoding="utf-8")
    for i, repo in enumerate(repos, 1):
        if repo in done: continue
        t0 = time.time()
        r = probe(repo, a.days, a.max_runs)
        fh.write(json.dumps(r, ensure_ascii=False) + "\n"); fh.flush()
        n = max(r["jobs"], 1)
        print(f"[{i}/{len(repos)}] {repo}")
        print(f"    runs={r['runs_fetched']} (GitHub reports {r['runs_total_reported']})"
              f"  jobs={r['jobs']}  errors={r['errors']}  {time.time()-t0:.0f}s")
        print(f"    machine time={r['machine_seconds']/60:,.1f} min | elapsed={r['run_duration_ms']/60000:,.1f} min"
              f" | BILLABLE={r['billable_ms']/60000:,.1f} min {r['billable_per_os'] or ''}")
        o, so = r["by_owner"], r["seconds_by_owner"]
        print(f"    github-standard={o['github-standard']} ({so['github-standard']/60:,.0f} min)"
              f"  github-larger={o['github-larger']} ({so['github-larger']/60:,.0f} min)"
              f"  NOT-GITHUB={o['not-github']} ({so['not-github']/60:,.0f} min"
              f" = {100*so['not-github']/max(r['machine_seconds'],1):.1f}%)  unknown={o['unknown']}")
        print(f"    runner_name present={100*r['runner_name_present']/n:.1f}%"
              f"  runner_group_name present={100*r['runner_group_present']/n:.1f}%"
              f"   [API calls left: {Rate.remaining}]")
        for s in r["samples"][:4]:
            print(f"      ! {s['owner']:<16} {s['labels']} group={s['group']} {s['seconds']/60:.1f} min")
        print(flush=True)
    fh.close()
    print(f"Written to {a.out}. API calls made: {Rate.calls}.")
    print("Remember: machine time is the sum of job durations, not wall clock. Jobs run in")
    print("parallel, so it is larger than a run's elapsed time and it is the right measure.")


if __name__ == "__main__":
    main()
