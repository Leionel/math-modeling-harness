#!/usr/bin/env python3
"""Freeze a validated result snapshot for the P0 evidence chain."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from _common import load_structured, rel_path, resolve_path, sha256_file, sha256_json, write_json  # noqa: E402
from runtime_state import RuntimeStateError, load_runtime_state  # noqa: E402
from validation.obligations import (  # noqa: E402
    declared_obligations,
    file_ref,
    validation_verdict,
    verify_validation_report,
)


def numeric_display(value: Any, precision: int) -> str:
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"value {value!r} is not numeric; provide display_value explicitly") from exc
    try:
        quantum = Decimal(1).scaleb(-precision)
        rounded = decimal.quantize(quantum, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError(f"value {value!r} cannot be rounded to precision={precision}") from exc
    return f"{rounded:.{precision}f}"


def normalize_result(
    row: dict[str, Any],
    source_path: Path,
    root: Path,
    index: int,
    *,
    claimable: bool,
    validation_verdict: str,
) -> dict[str, Any]:
    required = ("result_id", "question_id", "name", "value", "unit", "precision", "statistical_definition", "boundary", "validation_status")
    missing = [key for key in required if key not in row]
    if missing:
        raise ValueError(f"results[{index}] missing required fields: {', '.join(missing)}")
    allowed_statuses = {"passed", "failed", "error"}
    if row["validation_status"] not in allowed_statuses:
        raise ValueError(
            f"results[{index}] must have validation_status in {sorted(allowed_statuses)} before freezing"
        )
    expected_status = {"PASS": "passed", "FAIL": "failed", "ERROR": "error"}[validation_verdict]
    if row["validation_status"] != expected_status:
        raise ValueError(
            f"results[{index}].validation_status must be {expected_status!r} because validation verdict is {validation_verdict}"
        )
    precision = row["precision"]
    if not isinstance(precision, int) or precision < 0:
        raise ValueError(f"results[{index}].precision must be a non-negative integer")
    result = dict(row)
    if not isinstance(result["unit"], str) or not result["unit"].strip():
        raise ValueError(f"results[{index}].unit must be a non-empty string")
    display_scale = result.get("display_scale")
    has_display_unit = bool(result.get("display_unit")) or bool(result.get("display_label"))
    if display_scale is not None:
        if not isinstance(display_scale, (int, float)) or isinstance(display_scale, bool) or display_scale <= 0:
            raise ValueError(f"results[{index}].display_scale must be a positive number")
        if not has_display_unit:
            raise ValueError(
                f"results[{index}].display_scale requires display_unit or display_label so value/unit/scale stay bound"
            )
    elif has_display_unit:
        raise ValueError(
            f"results[{index}] declares display_unit/display_label without display_scale; scaled presentation is ambiguous"
        )
    scaled_value = result["value"]
    if display_scale is not None and isinstance(result["value"], (int, float)) and not isinstance(result["value"], bool):
        scaled_value = result["value"] / display_scale
    try:
        expected_display = numeric_display(scaled_value, precision)
    except ValueError:
        expected_display = None
    if "display_value" not in result:
        if expected_display is None:
            raise ValueError(f"results[{index}].display_value is required for a non-numeric value")
        result["display_value"] = expected_display
    if not isinstance(result["display_value"], str) or not result["display_value"].strip():
        raise ValueError(f"results[{index}].display_value must be a non-empty string")
    if expected_display is not None and result["display_value"] != expected_display:
        raise ValueError(
            f"results[{index}].display_value must equal canonical rounded value {expected_display!r}"
        )
    result.setdefault("source_artifact", rel_path(source_path, root))
    result.setdefault("source_key", str(result["result_id"]))
    supplied_claimable = result.get("claimable")
    if supplied_claimable is not None and supplied_claimable is not claimable:
        raise ValueError(
            f"results[{index}].claimable is derived from validation verdict and cannot be supplied as {supplied_claimable!r}"
        )
    result["claimable"] = claimable
    for key in ("result_id", "question_id", "name", "statistical_definition", "boundary", "source_artifact", "source_key"):
        if not isinstance(result[key], str) or not result[key].strip():
            raise ValueError(f"results[{index}].{key} must be a non-empty string")
    return result


def inspect_validation_reports(
    raw_paths: list[str],
    root: Path,
    model_contract: dict[str, Any],
    model_contract_path: Path,
) -> tuple[list[dict[str, str]], list[dict[str, Any]], str]:
    required = set(declared_obligations(model_contract))
    snapshots: list[dict[str, str]] = []
    verdicts: dict[str, dict[str, Any]] = {}
    for raw_path in raw_paths:
        path = resolve_path(raw_path, root).resolve()
        if not path.is_file():
            raise ValueError(f"validation artifact does not exist: {path}")
        report = load_structured(path)
        if not isinstance(report, dict):
            raise ValueError(f"validation report must be an object: {raw_path}")
        measurement_ref = report.get("measurement_snapshot")
        if not isinstance(measurement_ref, dict) or not isinstance(measurement_ref.get("path"), str):
            raise ValueError(f"validation report must contain measurement_snapshot.path: {raw_path}")
        measurements_path = resolve_path(measurement_ref["path"], root).resolve()
        if not measurements_path.is_file():
            raise ValueError(f"measurement snapshot does not exist: {measurement_ref['path']}")
        actual_measurement_ref = file_ref(measurements_path, root)
        if measurement_ref != actual_measurement_ref:
            raise ValueError(f"validation report measurement_snapshot does not match current file: {raw_path}")
        measurements = load_structured(measurements_path)
        if not isinstance(measurements, dict):
            raise ValueError(f"measurement snapshot must be an object: {measurement_ref['path']}")
        expected = verify_validation_report(
            report,
            model_contract,
            measurements,
            file_ref(model_contract_path, root),
            actual_measurement_ref,
        )
        rows = expected["obligations"]
        report_ref = {"path": rel_path(path, root), "sha256": sha256_file(path)}
        snapshots.append(report_ref)
        for index, row in enumerate(rows):
            obligation_id = row.get("obligation_id")
            if obligation_id in verdicts:
                raise ValueError(f"validation obligation appears in more than one report: {obligation_id}")
            verdicts[obligation_id] = {
                "obligation_id": obligation_id,
                "status": row["status"],
                "report": report_ref,
            }
    missing = sorted(required - set(verdicts))
    extra = sorted(set(verdicts) - required)
    if missing:
        raise ValueError(f"validation reports do not cover required obligation(s): {', '.join(missing)}")
    if extra:
        raise ValueError(f"validation reports contain undeclared obligation(s): {', '.join(extra)}")
    frozen_obligations = [verdicts[key] for key in sorted(verdicts)]
    return snapshots, frozen_obligations, validation_verdict([row["status"] for row in frozen_obligations])


def _receipt_path_from_index(index: Any, root: Path, receipt_id: str) -> Path | None:
    if not isinstance(index, dict):
        return None
    rows = index.get("receipts") if index.get("schema_version") == "2.0" else index.get("runs")
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        candidate = row.get("receipt_id") or row.get("command_id")
        if str(candidate) == receipt_id and isinstance(row.get("receipt_path"), str):
            return resolve_path(row["receipt_path"], root).resolve()
    return None


def _verify_v2_receipt(
    receipt_path: Path,
    *,
    root: Path,
    run_id: str,
    index: Any,
    selected_receipt_id: str | None,
    mode: str,
    require_io_hash: bool | None = None,
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    receipt = load_structured(receipt_path)
    if not isinstance(receipt, dict) or receipt.get("schema_version") != "2.0":
        raise ValueError("v2 freeze requires a schema_version=2.0 command receipt")
    receipt_id = str(receipt.get("receipt_id") or "")
    if not receipt_id:
        raise ValueError("command receipt has no receipt_id")
    if receipt.get("run_id") != run_id:
        raise ValueError("selected receipt run_id does not match --run-id")
    metadata = receipt.get("metadata")
    if receipt.get("exit_code") != 0 or (
        isinstance(metadata, dict) and metadata.get("outcome") == "failed"
    ):
        raise ValueError("selected receipt is not a successful run")
    if receipt.get("stage") != "full":
        raise ValueError("v2 result freeze requires a selected full receipt")
    if selected_receipt_id and selected_receipt_id != receipt_id:
        raise ValueError("supplied selected receipt ID does not match the receipt file")
    selected_rows: list[dict[str, Any]] = []
    if isinstance(index, dict):
        rows = index.get("receipts") if index.get("schema_version") == "2.0" else []
        if isinstance(rows, list):
            selected_rows = [row for row in rows if isinstance(row, dict) and row.get("selected") is True]
    if require_io_hash is None:
        require_io_hash = mode in {"research", "submission"}
    if require_io_hash:
        if not selected_rows:
            raise ValueError("research/submission result freeze requires a selected receipt in run_index")
        selected_ids = {str(row.get("receipt_id")) for row in selected_rows}
        if receipt_id not in selected_ids:
            raise ValueError("selected receipt is not the run_index selection")
        if len(selected_ids) != 1:
            raise ValueError("run_index must select exactly one receipt for result freeze")
    # The receipt is the only owner of these digests.  Recompute them from the
    # files; projected index values are intentionally ignored.
    if mode in {"research", "submission"}:
        for field in ("input_refs", "output_refs"):
            refs = receipt.get(field, [])
            if not isinstance(refs, list):
                raise ValueError(f"command receipt {field} must be an array")
            for index_value, ref in enumerate(refs):
                if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
                    raise ValueError(f"command receipt {field}[{index_value}] is not a v2 artifact ref")
                expected = ref.get("sha256")
                if not isinstance(expected, str):
                    raise ValueError(f"selected receipt {field}[{index_value}] is missing its SHA-256 binding")
                path = resolve_path(ref["path"], root).resolve()
                if not path.is_file() or sha256_file(path) != expected:
                    raise ValueError(f"selected receipt {field}[{index_value}] SHA-256 drift: {ref['path']}")
    block = {
        "path": rel_path(receipt_path, root),
        "command_id": receipt.get("command_id") or receipt_id,
        "exit_code": int(receipt["exit_code"]),
        "argv_matched": True,
    }
    return receipt, receipt_id, block


def _freeze_v2(args: argparse.Namespace, *, root: Path, receipt_path: Path, manifest_path: Path | None) -> int:
    """New v2 path: selected receipt is execution evidence, not free text."""

    # A standalone v2 receipt carries the runner-selected policy in its
    # metadata.  Use it when no manifest or explicit mode is available so a
    # sprint receipt is not silently promoted to research hashing.
    mode = args.integrity_mode
    index: Any = None
    require_io_hash: bool | None = None
    if manifest_path is not None:
        state = load_runtime_state(manifest_path, project_root=root, allow_legacy=False)
        if args.integrity_mode and args.integrity_mode != state.preset:
            raise ValueError(
                "--integrity-mode conflicts with the v2 manifest preset; "
                "freeze capabilities must come from preset+overrides"
            )
        mode = state.preset
        require_io_hash = bool(state.capabilities.require_selected_io_hash)
        index_path = state.root_path("run_index")
        if index_path is not None and index_path.is_file():
            index = load_structured(index_path)
    if args.run_index:
        index_path = resolve_path(args.run_index, root).resolve()
        if not index_path.is_file():
            raise ValueError(f"run_index does not exist: {args.run_index}")
        index = load_structured(index_path)
    if args.integrity_mode and manifest_path is None:
        mode = args.integrity_mode
    if mode is None and manifest_path is None:
        receipt_probe = load_structured(receipt_path)
        receipt_metadata = receipt_probe.get("metadata") if isinstance(receipt_probe, dict) else None
        receipt_mode = receipt_metadata.get("integrity_mode") if isinstance(receipt_metadata, dict) else None
        mode = receipt_mode if receipt_mode in {"sprint", "research", "submission"} else "research"
    mode = mode or "research"
    if mode not in {"sprint", "research", "submission"}:
        raise ValueError(f"unsupported integrity mode: {mode}")
    if not receipt_path.is_file():
        raise ValueError(f"command receipt does not exist: {receipt_path}")
    receipt, receipt_id, receipt_block = _verify_v2_receipt(
        receipt_path, root=root, run_id=args.run_id, index=index,
        selected_receipt_id=args.selected_receipt, mode=mode,
        require_io_hash=require_io_hash,
    )

    source = resolve_path(args.source, root).resolve()
    output = resolve_path(args.output, root).resolve()
    model_contract_path = resolve_path(args.model_contract, root).resolve()
    if args.freeze_receipt:
        freeze_receipt_path = resolve_path(args.freeze_receipt, root).resolve()
        freeze_receipt = load_structured(freeze_receipt_path)
        if (
            not isinstance(freeze_receipt, dict)
            or freeze_receipt.get("schema_version") != "2.0"
            or freeze_receipt.get("stage") != "freeze"
            or freeze_receipt.get("exit_code") != 0
            or freeze_receipt.get("run_id") != args.run_id
            or (
                isinstance(freeze_receipt.get("metadata"), dict)
                and freeze_receipt["metadata"].get("outcome") == "failed"
            )
        ):
            raise ValueError("freeze receipt must be a successful v2 freeze receipt for the frozen run")
        # A freeze receipt is meaningful only when it owns the canonical
        # frozen artifact's path and byte digest.  Recompute the digest from
        # the file instead of trusting a projected status/hash_verified bit.
        if not output.is_file():
            raise ValueError("freeze receipt binding requires the canonical frozen artifact to exist")
        matching = [
            ref for ref in freeze_receipt.get("output_refs", [])
            if isinstance(ref, dict)
            and isinstance(ref.get("path"), str)
            and resolve_path(ref["path"], root).resolve() == output
        ]
        if len(matching) != 1:
            raise ValueError("freeze receipt must bind exactly one canonical frozen artifact path")
        expected = matching[0].get("sha256")
        if not isinstance(expected, str):
            raise ValueError("freeze receipt canonical frozen artifact is missing its SHA-256 binding")
        actual = sha256_file(output)
        if expected != actual:
            raise ValueError("freeze receipt canonical frozen artifact SHA-256 drift")
    if not source.is_file() or source == output:
        raise ValueError("source result file must exist and differ from output")
    raw = load_structured(source)
    model_contract = load_structured(model_contract_path)
    if not isinstance(model_contract, dict) or model_contract.get("run_id") != args.run_id:
        raise ValueError("model contract run_id does not match --run-id")
    rows = raw.get("results") if isinstance(raw, dict) else raw
    if not isinstance(rows, list) or not rows:
        raise ValueError("source must contain a non-empty results array")

    def refs(raw_paths: list[str]) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        for raw_path in raw_paths:
            path = resolve_path(raw_path, root).resolve()
            if not path.is_file():
                raise ValueError(f"artifact does not exist: {path}")
            result.append({"path": rel_path(path, root), "sha256": sha256_file(path)})
        return result

    validation_snapshot, validation_obligations, overall_verdict = inspect_validation_reports(
        args.validation, root, model_contract, model_contract_path
    )
    claimable = overall_verdict == "PASS"
    results = [normalize_result(row, source, root, index, claimable=claimable, validation_verdict=overall_verdict)
               for index, row in enumerate(rows)]
    ids = [row["result_id"] for row in results]
    if len(ids) != len(set(ids)):
        raise ValueError("result_id values must be unique")
    frozen: dict[str, Any] = {
        "schema_version": "1.2", "run_id": args.run_id, "status": "frozen",
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "model_contract_snapshot": {"path": rel_path(model_contract_path, root), "sha256": sha256_file(model_contract_path)},
        "source_snapshot": {"path": rel_path(source, root), "sha256": sha256_file(source)},
        "input_snapshot": refs(args.input), "code_snapshot": refs(args.code),
        "validation_snapshot": validation_snapshot, "validation_obligations": validation_obligations,
        "validation_verdict": overall_verdict, "claimable": claimable,
        "command": f"receipt:{receipt_id}", "seed": args.seed if args.seed is not None else receipt.get("seed"),
        "results_sha256": sha256_json(results), "results": results, "command_receipt": receipt_block,
    }
    write_json(output, frozen, overwrite=args.force)
    print(json.dumps({"status": "frozen", "output": rel_path(output, root), "results": len(results),
                      "validation_verdict": overall_verdict, "claimable": claimable,
                      "selected_receipt_id": receipt_id, "warning": "v2 freeze evidence is bound to the selected receipt; free-text command is not authoritative"}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="JSON result file with a top-level results array")
    parser.add_argument("--output", required=True, help="frozen_results.json output path")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--model-contract", required=True)
    parser.add_argument("--command", help="legacy v1 free-text command; not execution evidence on the v2 path")
    parser.add_argument(
        "--command-receipt",
        help="Process-captured receipt from run_and_record.py proving --command actually executed. "
        "Verifies exit_code==0 and argv match without any hash comparison; dev mode may omit it "
        "(explicit downgrade), research mode expects it.",
    )
    parser.add_argument("--receipt", help="selected v2 command receipt path")
    parser.add_argument("--selected-receipt", help="selected v2 receipt_id (optional when --receipt is supplied)")
    parser.add_argument("--freeze-receipt", help="optional process receipt for the freeze operation itself")
    parser.add_argument("--run-index", help="v2 run_index projection when no manifest root supplies it")
    parser.add_argument("--manifest", help="v2 run_manifest; activates the normalized path")
    parser.add_argument("--integrity-mode", choices=["sprint", "research", "submission"])
    parser.add_argument("--seed", type=int)
    parser.add_argument("--input", action="append", default=[], help="input artifact; repeatable")
    parser.add_argument("--code", action="append", required=True, help="code artifact; repeatable")
    parser.add_argument("--validation", action="append", required=True, help="validation report/log; repeatable")
    parser.add_argument("--force", action="store_true", help="overwrite existing output file")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    manifest_candidate = resolve_path(args.manifest, root).resolve() if args.manifest else (root / "run_manifest.json").resolve()
    manifest_path = manifest_candidate if manifest_candidate.is_file() else None
    receipt_candidate = args.receipt or args.command_receipt
    use_v2 = bool(manifest_path and manifest_path.is_file() and load_structured(manifest_path).get("schema_version") == "2.0")
    if not use_v2 and receipt_candidate:
        candidate_path = resolve_path(receipt_candidate, root).resolve()
        try:
            candidate_value = load_structured(candidate_path)
        except (OSError, ValueError, TypeError):
            candidate_value = None
        use_v2 = isinstance(candidate_value, dict) and candidate_value.get("schema_version") == "2.0"
    if use_v2:
        try:
            if not receipt_candidate:
                raise ValueError("v2 result freeze requires --receipt (selected command receipt)")
            return _freeze_v2(
                args,
                root=root,
                receipt_path=resolve_path(receipt_candidate, root).resolve(),
                manifest_path=manifest_path,
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError, RuntimeStateError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    if not args.command:
        print("ERROR: legacy result freeze requires --command; use --receipt for v2", file=sys.stderr)
        return 2
    source = resolve_path(args.source, root).resolve()
    output = resolve_path(args.output, root).resolve()
    model_contract_path = resolve_path(args.model_contract, root).resolve()
    if not source.is_file():
        print(f"ERROR: source result file does not exist: {source}", file=sys.stderr)
        return 2
    if source == output:
        print("ERROR: --source and --output must be different files", file=sys.stderr)
        return 2
    try:
        raw = load_structured(source)
        model_contract = load_structured(model_contract_path)
        if not isinstance(model_contract, dict):
            raise ValueError("model contract must be an object")
        if model_contract.get("run_id") != args.run_id:
            raise ValueError("model contract run_id does not match --run-id")
        rows = raw.get("results") if isinstance(raw, dict) else raw
        if not isinstance(rows, list) or not rows:
            raise ValueError("source must be a non-empty list or an object with a non-empty results list")

        def refs(raw_paths: list[str]) -> list[dict[str, str]]:
            output_refs: list[dict[str, str]] = []
            for raw_path in raw_paths:
                path = resolve_path(raw_path, root).resolve()
                if not path.is_file():
                    raise ValueError(f"artifact does not exist: {path}")
                output_refs.append({"path": rel_path(path, root), "sha256": sha256_file(path)})
            return output_refs

        command_receipt_block = None
        if args.command_receipt:
            receipt_path = resolve_path(args.command_receipt, root).resolve()
            if not receipt_path.is_file():
                raise ValueError(f"command receipt does not exist: {receipt_path}")
            receipt = load_structured(receipt_path)
            if not isinstance(receipt, dict):
                raise ValueError("command receipt must be an object")
            if receipt.get("exit_code") != 0:
                raise ValueError(
                    f"command receipt shows a failed run (exit_code={receipt.get('exit_code')}); "
                    "only successful runs may be frozen"
                )
            receipt_argv = [str(part) for part in receipt.get("argv", [])]
            declared = args.command.split()
            argv_matched = receipt_argv == declared
            if not argv_matched:
                raise ValueError(
                    "command receipt argv does not match --command:\n"
                    f"  receipt: {receipt_argv}\n  declared: {declared}"
                )
            command_receipt_block = {
                "path": rel_path(receipt_path, root),
                "command_id": str(receipt.get("command_id", "")),
                "exit_code": int(receipt.get("exit_code", -1)),
                "argv_matched": argv_matched,
            }

        validation_snapshot, validation_obligations, overall_verdict = inspect_validation_reports(
            args.validation, root, model_contract, model_contract_path
        )
        claimable = overall_verdict == "PASS"
        results = [
            normalize_result(
                row,
                source,
                root,
                index,
                claimable=claimable,
                validation_verdict=overall_verdict,
            )
            for index, row in enumerate(rows)
        ]
        ids = [row["result_id"] for row in results]
        if len(ids) != len(set(ids)):
            raise ValueError("result_id values must be unique")
        frozen = {
            "schema_version": "1.2",
            "run_id": args.run_id,
            "status": "frozen",
            "frozen_at": datetime.now(timezone.utc).isoformat(),
            "model_contract_snapshot": {
                "path": rel_path(model_contract_path, root),
                "sha256": sha256_file(model_contract_path),
            },
            "source_snapshot": {"path": rel_path(source, root), "sha256": sha256_file(source)},
            "input_snapshot": refs(args.input),
            "code_snapshot": refs(args.code),
            "validation_snapshot": validation_snapshot,
            "validation_obligations": validation_obligations,
            "validation_verdict": overall_verdict,
            "claimable": claimable,
            "command": args.command,
            "seed": args.seed,
            "results_sha256": sha256_json(results),
            "results": results,
        }
        if command_receipt_block is not None:
            frozen["command_receipt"] = command_receipt_block
        write_json(output, frozen, overwrite=args.force)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": "frozen",
                "output": rel_path(output, root),
                "results": len(results),
                "validation_verdict": overall_verdict,
                "claimable": claimable,
                "warning": "legacy --command is compatibility metadata only; use --receipt for execution evidence",
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
