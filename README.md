# oss-ci-machine-time

Who owns the machines that build and test critical open source, and what keeps that cost
invisible to the people funding it?

This repository holds a small, reproducible probe that asks the first half of that question
against GitHub's public API, plus the raw results of one pilot run.

## What it measures

For a list of repositories, for the N most recent workflow runs of each:

| Signal | Endpoint | Why it matters |
|---|---|---|
| machine time | `/actions/runs/{id}/jobs` | summed job duration, the compute actually consumed |
| what GitHub reports as billable | `/actions/runs/{id}/timing` | the `billable` field; zero by definition in public repositories (limitation 6) |
| who owns the runner | `runner_group_name` on each job | GitHub's standard fleet, its paid larger runners, or somebody else's hardware |

Everything comes from documented, public REST endpoints. Nothing is scraped.

## Pilot run

Numbers below come from `data/pilot.jsonl` in this repository. Re-run `summarise.py` against
that file to reproduce them.

Ten critical projects, the 50 most recent workflow runs of each: 500 runs, **6,617 jobs**,
**85,221 minutes of machine time** (1,420 hours, 59 days), and a `billable` figure of
**0.0 in ten cases out of ten**, which is what GitHub's documentation says to expect in public
repositories (limitation 6).

Split by who owns the machine, resolved from `runner_group_name`:

| Owner | Jobs | Machine minutes | Share |
|---|---|---|---|
| GitHub, standard fleet | 6,134 | 80,913.8 | 94.9% |
| GitHub, larger runners (its paid tier) | 454 | 3,427.9 | 4.0% |
| **Not GitHub** | **29** | **878.9** | **1.0%** |

Three of the ten projects use hardware GitHub does not own, and the API names it:

- **Rust** runs jobs in a group it calls `gha-self-hosted`, with labels naming EC2 instance
  types (`c8a.8xlarge`, `m8a.2xlarge`, `c9g.4xlarge` on aarch64), and separately on AWS
  CodeBuild (`codebuild-ubuntu-22-36c-…`).
- **LLVM** runs macOS/ARM64 jobs in a group called `llvm-macos-apple`, whose labels literally
  read `self-hosted, macOS, ARM64, apple-runners`.
- **systemd** runs `ppc64le` and `s390x` jobs in the `default` group, which means they are not
  GitHub's fleet. **Public data does not reveal who owns them.**

`billable` is zero for all of it, GitHub's own hardware and everyone else's alike, including the
larger runners GitHub does charge for. That is a property of the field, not a finding (limitation 6).

## Limitations, stated plainly

1. The sample is the **N most recent runs per project**, not a time window and not a random
   sample. **This matters more than it sounds.** Two runs of this probe over the same ten
   projects, a day apart, gave 69,404 and 85,221 minutes; on individual projects the gap
   reached a factor of five. Do not quote a single figure as if it were stable, and do not
   extrapolate to a month by multiplying.
2. **Machine time is the sum of job durations**, not wall clock. Jobs run in parallel, so this
   number is larger than a run's elapsed time and it is the right measure of compute.
3. "Outside GitHub's fleet" is not the same as "self-hosted by the project", and neither is the
   same as "donated". Only the group name and labels can tell you which, and for systemd they
   do not.
4. GitHub's **larger runners are still GitHub's hardware**, and they are a paid tier: GitHub's
   billing documentation states that they "are always charged for, even when used by public
   repositories" ([docs](https://docs.github.com/en/billing/concepts/product-billing/github-actions),
   accessed 1 October 2026). Counting them as third-party would raise the third-party share in
   this pilot from 1.0% to 5.1% of machine time.
5. Projects that do not use GitHub Actions at all are invisible to this method. That is a
   finding in itself, not a gap in the data.
6. **`billable` cannot show who pays.** GitHub's documentation is explicit: "Billable job execution
   minutes are only shown for jobs run on private repositories that use GitHub-hosted runners
   [...]. There are no billable minutes when using GitHub Actions in public repositories or for
   jobs run on self-hosted runners." ([docs](https://docs.github.com/en/actions/how-tos/monitor-workflows/view-job-execution-time),
   accessed 1 October 2026). In this pilot the field stays at zero even for the 454 larger-runner
   jobs, which GitHub charges for, and GitHub announced on 2 February 2025 that the endpoint
   behind it is closing down ([changelog](https://github.blog/changelog/2025-02-02-actions-get-workflow-usage-and-get-workflow-run-usage-endpoints-closing-down/)).

## Running it

A token is only needed to raise the rate limit from 60 to 5,000 requests an hour. GitHub's
documentation for these endpoints states they "can be used without authentication or the
aforementioned permissions if only public resources are requested", so **a classic token with
no scopes selected is enough**.

```sh
GITHUB_TOKEN=... python3 probe.py --days 30 --max-runs 50 --repos-file repos.txt \
    --max-samples 1000 --out data/pilot.jsonl
python3 summarise.py data/pilot.jsonl
```

`--max-samples` controls how many non-standard jobs are recorded in full per repository. The
default of 40 is enough to see which groups are in play, but a repository with hundreds of such
jobs needs a higher value before its ownership split is proof rather than inference.
`summarise.py` tells you which repositories were truncated.

Budget roughly `repos * (max_runs/100 + 2*max_runs)` API calls. Ten repositories at 50 runs is
about 1,010 calls and twenty minutes. The script appends to its output file after each
repository and resumes where it stopped.

## Licence

Code: MIT. Data in `data/`: CC0, it is derived entirely from public API responses.

## A note on tooling

The measurement, the questions it asks and the reading of its results are mine. I used Claude
(Anthropic) to write and debug the scripts, to check sources, and to edit this README.

## Corrections

- **1 October 2026.** Limitation 4 said GitHub's larger runners were "a paid tier given free to
  public repositories"; GitHub's billing documentation says they are always charged for. Added
  limitation 6 on what `billable` can and cannot show. Corrected comments in `probe.py` (there is
  no 40,000 cap on `total_count`; a search filtered by `created` returns at most 1,000 results)
  and in `summarise.py` (USD 0.006 a minute is GitHub's Linux 2-core price, while Linux standard
  runners in public repositories have 4 CPUs; the self-hosted platform charge was postponed).
  The repository as it stood for the pilot run is tagged `pilot-2026-09-01`.
