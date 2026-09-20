# Blinded synthetic transfer experiment

## Objective and separation

The user asked for parallel implementation and real tests that assess transfer,
not another round of tuning to the existing fifty development cases. The old50
remain a regression corpus, not a held-out estimate of general intelligence.

Three parallel tasks own designer context, reviewer evidence, and independently
authored evaluation inputs. Runtime implementers do not inspect the new case
details or outcomes before freezing their code. The evaluation author does not
read old50 findings or production prompts while constructing the bank. Families
are explicit in the bank, but no claim is made that the underlying visualization
skills are absent from the old corpus or model pretraining.

The bank contains 24 newly authored synthetic tasks across six families, with
intent contrasts and meaning-preserving transformations. It is a challenge set,
not a representative production sample or human-labelled gold. The original bank
was frozen at 2026-09-17T03:32:26Z with SHA256
`2548d627feb492d200ca11bd33113121ee1d9467c15a1d474f09a850759b84a5`.
No hidden case-specific runtime changes or prompt optimization are permitted
after opening outcomes. A future change requires a new version and a fresh
evaluation claim, not overwriting this experiment.

## Baseline and candidate

Before implementation, the existing dirty working runtime was archived at
`/private/tmp/vis-generalization-baseline.3SEChZ/runtime.tar`; its archive SHA256 is
`d10588641c1f695be78b1a00d08235601fa7e84f69d733d6d9cc042f0bef2bf2`.
It contains the user's current files, not a historical git commit. Existing
unrelated edits are preserved. Only node_modules and Python bytecode are excluded;
the extracted renderer uses the same installed node_modules as the candidate.

Both arms use GLM5.3 for all text roles and Gemma4 31B Nitro for image review,
with the same reasoning settings and shared18 model-request/16 tool-call limits.
The turn watchdog is120 seconds and the latency target60 seconds. Environment
overrides are process-local; production model defaults and .env are not changed.
The two arms use the same frozen case order and one case at a time per arm. If
run concurrently, total case concurrency is two and reported as such, not compared
causally to the earlier serial50 timing distribution.

The evaluator selects and hashes the actual imported runtime and renderer, not
just the repository checkout. Bank, scoring, runtime and model metadata are saved.
Every attempt, timeout, artifact, first/repair image and tool trace is retained.
No retry is silently substituted for a failure. Framework request counts may
exclude calls cancelled before usage accounting; they are not provider billing
counts. The programmatic lead/tool entry point is used with caller_kind=agent;
there is no browser/UI automation.

## Measures and interpretation

- Source-value and unit fidelity, required information coverage, supported
  chart choice and actual artifact delivery are scored separately.
- Online inspector verdicts are recorded but do not constitute the quality oracle.
- Pairwise tests check semantic stability under meaning-preserving transforms,
  and goal-responsive representations under intent changes. Identical images or
  a single prescribed chart family are not universal requirements.
- Model requests, repair attempts, median/p95 latency and all failures retain
  their denominators. Automated success is not independently established visual
  correctness; retained images require a separate audit with uncertainty.
- One paired trial of a small synthetic bank is evidence of behavior on that
  bank, not a guarantee of generalization or a statistically isolated attribution
  to one change. Several related candidate changes are being tested together.

## Permissions and adoption

On2026-09-17 an attempted full89 legacy reviewer evaluation was rejected by
auto-review because it would export existing local chart images/reference rows
to OpenRouter without sufficiently specific fresh consent. No such export was
started. The user has been asked explicitly; do not work around this block.
New synthetic inputs do not copy those files or user CSV contents. The required
full89 reviewer validation remains an adoption gate unless permission is granted
and the actual run is completed. Synthetic probes are not a replacement for it.

Local tests establish code contracts and compatibility, not model intelligence.
The final report must distinguish completed checks, external-call failures,
permission-blocked checks, observed improvements and regressions. No automatic
deployment, commit, model substitution, or unrelated cleanup is part of this run.

The methodology follows [OpenAI evaluation guidance](https://developers.openai.com/api/docs/guides/evaluation-best-practices#how-to-read-evals):
task-specific tests, real-use relevance, independent calibration, and retained
failure evidence. These experiment-specific choices are ours, not vendor guarantees.
