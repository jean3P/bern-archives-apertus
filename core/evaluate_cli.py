"""Explicit evaluation acquisition or offline scoring. No action on import."""

import argparse
import json
from pathlib import Path

from core.evaluation import run_evaluation, score_evaluation


def main():
    parser = argparse.ArgumentParser(description="Bounded archival evaluation and reviewer-bound scoring")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Actually call the existing answer backend; never a dry run")
    run.add_argument("--references", type=Path, required=True)
    run.add_argument("--split", choices=("development", "evaluation"), required=True)
    run.add_argument("--data-dir", type=Path, required=True)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--pipeline", choices=("apertus", "apertus-qualified", "qwen-only", "apertus-facets", "qwen-apertus"), default="apertus",
                     help="Baseline/parts use at most three POSTs; hybrid at most four; each has one retry")
    run.add_argument("--retrieval-mode", choices=("standard", "entity", "coverage"), default="standard")
    review = run.add_mutually_exclusive_group()
    review.add_argument("--allow-draft-references", action="store_true", help="Diagnostic only, not human-approved gold")
    review.add_argument("--reviewed-by", help="Use only after this person reviewed this exact reference snapshot; records an attestation")
    score = sub.add_parser("score", help="Read saved replies/reviews only; no model calls")
    score.add_argument("--run", type=Path, required=True)
    score.add_argument("--reviews", type=Path)
    score.add_argument("--document-reviews", type=Path)
    score.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "run":
            metrics = run_evaluation(args.references, args.split, args.data_dir, args.out,
                allow_draft=args.allow_draft_references, reviewed_by=args.reviewed_by,
                pipeline=args.pipeline, retrieval_mode=args.retrieval_mode)
        else:
            metrics = score_evaluation(args.run, args.out, reviews=args.reviews,
                                       document_reviews=args.document_reviews)
    except (ValueError, LookupError, OSError, TypeError, KeyError) as error:
        parser.exit(1, "Evaluation command failed (" + type(error).__name__ + "). Preserve any output and inspect its failure record.\n")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    if args.command == "run" and (metrics["attempted"] != metrics["scheduled_questions"] or
                                   metrics["technical_completions"] != metrics["scheduled_questions"]):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
