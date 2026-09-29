# Bounded execution receipts

For a v2 command, `harness execute` / `scripts/run_and_record.py` accepts
`--timeout <seconds>`. A timed-out child still produces an immutable receipt,
stdout/stderr sidecars, and a run-index entry. The receipt records
`exit_code: null` because the child did not return an exit code; its metadata
records `outcome: failed`, `failure_reason: timeout`, and `timeout_seconds`.
The CLI returns 124 to the caller. This is a Harness status code, not a child
exit code. A timed-out run cannot support a frozen result.

The local backend does not capture the complete process environment. A receipt
therefore does not by itself prove cross-machine reproducibility.
