# Model racing comparison

`python scripts/model_racing.py --spec ... --base-project ... --output-dir ...`
forks candidate branches from one checkpoint and inspects the facts present in
each branch. The CLI does not execute a candidate model. Its
`race_summary.json` records `execution_mode: fork_and_inspect_only`.

An embedded caller may pass `execute_runners` to `run_model_race`; that mode is
recorded as `custom_runner_invoked`. The comparison reports `claimable` only
when the frozen result declares it, its validation verdict is `PASS`, and M1,
P1, and P2 all pass on the candidate branch. A copied frozen flag alone does
not promote a candidate.
