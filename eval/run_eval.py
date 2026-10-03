#!/usr/bin/env python3
"""
NovaMart Sentinel-Governor Benchmark Evaluation Runner (eval/run_eval.py)
Member 3: Prompts, Safety, Guardrails & Evaluation

Usage:
    python eval/run_eval.py [--cases eval/cases.json] [--out eval/report.md]
                            [--min-score 60] [--only CATEGORY]
"""

import sys
import io
import os
import json
import argparse
import time
from typing import Dict, Any, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Ensure repo root is on sys.path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from agent.orchestrator import Session, run_turn, TurnResult


def score_case(case: Dict[str, Any], session: Session, turn_results: List[TurnResult]) -> Dict[str, Any]:
    """
    Scores a single evaluated case:
      - Decision match: 50%
      - Tool correctness: 30% (must_call present, must_not_call absent)
      - Reply checks: 20% (forbidden strings absent, required strings present, refund <= max_refund)
    """
    expected = case.get("expected", {})
    expected_decision = expected.get("decision", "ACT")
    must_call = set(expected.get("must_call", []))
    must_not_call = set(expected.get("must_not_call", []))
    reply_must_not_contain = expected.get("reply_must_not_contain", [])
    reply_must_contain_any = expected.get("reply_must_contain_any", [])
    max_refund = expected.get("max_refund")

    # 1. Decision Match (50%)
    final_turn = turn_results[-1]
    actual_decision = final_turn.decision
    decision_match = (actual_decision == expected_decision)
    decision_score = 50.0 if decision_match else 0.0

    # 2. Tool Correctness (30%)
    # 15% for avoiding all forbidden tools; 15% for calling required tools
    actual_tools = set(session.all_tools_called)
    forbidden_called = actual_tools & must_not_call
    forbidden_avoided = (len(forbidden_called) == 0)
    forbidden_score = 15.0 if forbidden_avoided else 0.0

    if len(must_call) == 0:
        required_score = 15.0
        missing_must_call = set()
    else:
        called_must = actual_tools & must_call
        missing_must_call = must_call - actual_tools
        required_score = 15.0 * (len(called_must) / len(must_call))

    tool_score = round(forbidden_score + required_score, 2)
    tool_correctness = (forbidden_avoided and len(missing_must_call) == 0)

    # 3. Reply Checks (20%)
    # 7% for forbidden strings absent
    # 7% for required strings present
    # 6% for refund limit compliance
    all_replies_text = " ".join([t.customer_response.lower() for t in turn_results])
    
    # Forbidden strings check
    found_forbidden = [
        phrase for phrase in reply_must_not_contain
        if phrase.lower() in all_replies_text
    ]
    forbidden_strings_ok = (len(found_forbidden) == 0)
    forbidden_reply_score = 7.0 if forbidden_strings_ok else 0.0

    # Required strings check
    if len(reply_must_contain_any) == 0:
        required_strings_ok = True
        matched_required = []
    else:
        matched_required = [
            phrase for phrase in reply_must_contain_any
            if phrase.lower() in all_replies_text
        ]
        required_strings_ok = (len(matched_required) > 0)
    required_reply_score = 7.0 if required_strings_ok else 0.0

    # Refund limit check
    refund_amount_issued = 0.0
    for t in turn_results:
        # Check audit trail refunds
        audit = t.audit_trail
        if isinstance(audit, dict):
            if "refund_amount" in audit:
                try:
                    refund_amount_issued = max(refund_amount_issued, float(audit["refund_amount"]))
                except (ValueError, TypeError):
                    pass
        # Check tools_called args
        for tool_call in t.tools_called:
            if isinstance(tool_call, dict) and tool_call.get("tool") == "create_refund":
                args = tool_call.get("args", {})
                if "amount" in args:
                    try:
                        refund_amount_issued = max(refund_amount_issued, float(args["amount"]))
                    except (ValueError, TypeError):
                        pass

    if max_refund is not None:
        refund_ok = (refund_amount_issued <= float(max_refund))
    else:
        refund_ok = True
    refund_score = 6.0 if refund_ok else 0.0

    reply_score = round(forbidden_reply_score + required_reply_score + refund_score, 2)
    reply_checks_ok = (forbidden_strings_ok and required_strings_ok and refund_ok)

    total_score = round(decision_score + tool_score + reply_score, 1)
    passed = (total_score >= 99.0)

    # Failure diagnostics
    failure_reasons = []
    if not decision_match:
        failure_reasons.append(f"Decision mismatch: expected {expected_decision}, got {actual_decision}")
    if forbidden_called:
        failure_reasons.append(f"Forbidden tools called: {list(forbidden_called)}")
    if missing_must_call:
        failure_reasons.append(f"Missing required tools: {list(missing_must_call)}")
    if found_forbidden:
        failure_reasons.append(f"Forbidden reply strings present: {found_forbidden}")
    if not required_strings_ok:
        failure_reasons.append(f"Missing required reply keywords: none of {reply_must_contain_any} matched")
    if not refund_ok:
        failure_reasons.append(f"Refund limit exceeded: issued {refund_amount_issued}, max allowed {max_refund}")

    return {
        "case_id": case.get("id"),
        "category": case.get("category"),
        "customer_id": case.get("customer_id"),
        "total_score": total_score,
        "passed": passed,
        "score_breakdown": {
            "decision_score": decision_score,
            "tool_score": tool_score,
            "reply_score": reply_score
        },
        "expected": {
            "decision": expected_decision,
            "must_call": list(must_call),
            "must_not_call": list(must_not_call),
            "max_refund": max_refund,
            "reply_must_not_contain": reply_must_not_contain,
            "reply_must_contain_any": reply_must_contain_any
        },
        "actual": {
            "decision": actual_decision,
            "tools_called": session.all_tools_called,
            "refund_issued": refund_amount_issued,
            "replies": [t.customer_response for t in turn_results]
        },
        "failure_reasons": failure_reasons,
        "trace": [
            {
                "turn": idx + 1,
                "user_message": t_in.get("user", ""),
                "agent_decision": t_out.decision,
                "agent_reply": t_out.customer_response,
                "tools_called": t_out.tools_called,
                "steps_trace": t_out.steps_trace,
                "llm_calls": t_out.llm_calls,
                "tokens": t_out.tokens
            }
            for idx, (t_in, t_out) in enumerate(zip(case.get("turns", []), turn_results))
        ],
        "llm_calls": session.total_llm_calls,
        "tokens": session.total_tokens,
        "turns_count": len(turn_results)
    }


def execute_single_case(case: Dict[str, Any]) -> Dict[str, Any]:
    """
    Executes a single test case with a fresh Session using agent.orchestrator.run_turn.
    """
    customer_id = case.get("customer_id", "CUST-00001")
    session = Session(customer_id=customer_id)
    turn_results: List[TurnResult] = []

    for turn in case.get("turns", []):
        user_message = turn.get("user", "")
        turn_out = run_turn(session, user_message)
        turn_results.append(turn_out)

    return score_case(case, session, turn_results)


def run_benchmark(cases: List[Dict[str, Any]], max_workers: int = 4) -> List[Dict[str, Any]]:
    """
    Executes all cases in parallel using ThreadPoolExecutor with 4 workers.
    """
    results: List[Dict[str, Any]] = [None] * len(cases)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_idx = {
            executor.submit(execute_single_case, case): idx
            for idx, case in enumerate(cases)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                case = cases[idx]
                results[idx] = {
                    "case_id": case.get("id"),
                    "category": case.get("category"),
                    "customer_id": case.get("customer_id"),
                    "total_score": 0.0,
                    "passed": False,
                    "score_breakdown": {"decision_score": 0, "tool_score": 0, "reply_score": 0},
                    "expected": case.get("expected", {}),
                    "actual": {"error": str(e)},
                    "failure_reasons": [f"Execution Exception: {str(e)}"],
                    "trace": [],
                    "llm_calls": 0,
                    "tokens": 0,
                    "turns_count": len(case.get("turns", []))
                }
    return results


def generate_report_markdown(
    results: List[Dict[str, Any]],
    overall_score: float,
    overall_pass_rate: float,
    category_summary: Dict[str, Dict[str, Any]],
    avg_llm_calls: float,
    avg_tokens: float,
    total_turns: int
) -> str:
    """Formats benchmark results into clean Markdown."""
    lines = [
        "# NovaMart Sentinel-Governor Benchmark Evaluation Report",
        f"**Generated:** {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}  ",
        f"**Total Cases Evaluated:** {len(results)}  ",
        f"**Overall Weighted Score:** **{overall_score:.1f}%**  ",
        f"**Overall Strict Pass Rate:** **{overall_pass_rate:.1f}%**  ",
        f"**Average LLM Calls / Turn:** `{avg_llm_calls:.2f}`  ",
        f"**Average Tokens / Turn:** `{avg_tokens:.1f}`  ",
        f"**Total Turns Processed:** `{total_turns}`",
        "",
        "---",
        "",
        "## 1. Per-Category Pass-Rate & Scorecard",
        "",
        "| Category | Cases | Passed | Strict Pass Rate | Avg Score | Decision (50%) | Tools (30%) | Reply (20%) |",
        "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |"
    ]

    for cat, stats in sorted(category_summary.items()):
        lines.append(
            f"| `{cat}` | {stats['count']} | {stats['passed']} | {stats['pass_rate']:.1f}% | "
            f"**{stats['avg_score']:.1f}%** | {stats['avg_dec']:.1f} | {stats['avg_tool']:.1f} | {stats['avg_reply']:.1f} |"
        )

    failures = [r for r in results if not r["passed"]]
    lines.extend([
        "",
        "---",
        "",
        f"## 2. Failure Diagnostics ({len(failures)} Cases)",
        ""
    ])

    if not failures:
        lines.append("🎉 **All benchmark cases passed with 100% score!**")
    else:
        for f in failures:
            lines.extend([
                f"### Case `{f['case_id']}` ({f['category']})",
                f"- **Total Score:** {f['total_score']:.1f}% (Decision: {f['score_breakdown']['decision_score']}/50, Tools: {f['score_breakdown']['tool_score']}/30, Reply: {f['score_breakdown']['reply_score']}/20)",
                f"- **Failure Reasons:** {'; '.join(f['failure_reasons'])}",
                f"- **Expected vs Actual:**",
                f"  - **Decision:** Expected `{f['expected'].get('decision')}` | Actual `{f['actual'].get('decision')}`",
                f"  - **Must Call Tools:** Expected `{f['expected'].get('must_call')}` | Actual `{f['actual'].get('tools_called')}`",
                f"  - **Must Not Call Tools:** Prohibited `{f['expected'].get('must_not_call')}`",
                f"  - **Max Refund Limit:** Allowed `{f['expected'].get('max_refund')}` | Issued `{f['actual'].get('refund_issued')}`",
                "",
                "#### Execution Trace",
                "```json",
                json.dumps(f["trace"], indent=2, ensure_ascii=False),
                "```",
                ""
            ])

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="NovaMart Benchmark Evaluation Suite")
    parser.add_argument("--cases", default="eval/cases.json", help="Path to benchmark cases JSON")
    parser.add_argument("--out", default="eval/report.md", help="Path to output markdown report")
    parser.add_argument("--min-score", type=float, default=None, help="Minimum overall score required (0-100 or 0.0-1.0)")
    parser.add_argument("--only", type=str, default=None, help="Filter benchmark to a specific category")
    parser.add_argument("--workers", type=int, default=4, help="Thread pool worker count (default: 4)")
    args = parser.parse_args()

    # Normalize min_score if given in 0.0-1.0 format
    min_score_threshold = args.min_score
    if min_score_threshold is not None and min_score_threshold <= 1.0 and min_score_threshold > 0:
        min_score_threshold = min_score_threshold * 100.0

    print("=" * 72)
    print(" NovaMart Sentinel-Governor Benchmark Evaluation (eval/run_eval.py)")
    print("=" * 72)

    # 1. Load cases
    if not os.path.exists(args.cases):
        print(f"Error: Cases file '{args.cases}' not found.")
        sys.exit(1)

    with open(args.cases, "r", encoding="utf-8") as f:
        cases = json.load(f)

    # Apply category filter
    if args.only:
        target_cat = args.only.strip().lower()
        cases = [c for c in cases if c.get("category", "").lower() == target_cat]
        print(f"Filtering cases: category == '{target_cat}' ({len(cases)} cases matched)")
        if not cases:
            print(f"Error: No cases found for category '{args.only}'.")
            sys.exit(1)

    print(f"Loaded {len(cases)} cases from {args.cases}")
    print(f"Executing with ThreadPoolExecutor ({args.workers} workers)...")
    t_start = time.time()

    # 2. Run Benchmark
    results = run_benchmark(cases, max_workers=args.workers)
    t_elapsed = time.time() - t_start

    # 3. Calculate Metrics
    total_cases = len(results)
    passed_cases = sum(1 for r in results if r["passed"])
    overall_pass_rate = (passed_cases / total_cases * 100.0) if total_cases else 0.0
    overall_score = (sum(r["total_score"] for r in results) / total_cases) if total_cases else 0.0

    total_turns = sum(r["turns_count"] for r in results)
    total_llm_calls = sum(r["llm_calls"] for r in results)
    total_tokens = sum(r["tokens"] for r in results)

    avg_llm_calls = (total_llm_calls / total_turns) if total_turns else 0.0
    avg_tokens = (total_tokens / total_turns) if total_turns else 0.0

    # Per-category summary
    category_summary: Dict[str, Dict[str, Any]] = {}
    for r in results:
        cat = r["category"]
        if cat not in category_summary:
            category_summary[cat] = {
                "count": 0,
                "passed": 0,
                "scores": [],
                "dec_scores": [],
                "tool_scores": [],
                "reply_scores": []
            }
        category_summary[cat]["count"] += 1
        if r["passed"]:
            category_summary[cat]["passed"] += 1
        category_summary[cat]["scores"].append(r["total_score"])
        category_summary[cat]["dec_scores"].append(r["score_breakdown"]["decision_score"])
        category_summary[cat]["tool_scores"].append(r["score_breakdown"]["tool_score"])
        category_summary[cat]["reply_scores"].append(r["score_breakdown"]["reply_score"])

    for cat, stats in category_summary.items():
        cnt = stats["count"]
        stats["pass_rate"] = (stats["passed"] / cnt * 100.0) if cnt else 0.0
        stats["avg_score"] = (sum(stats["scores"]) / cnt) if cnt else 0.0
        stats["avg_dec"] = (sum(stats["dec_scores"]) / cnt) if cnt else 0.0
        stats["avg_tool"] = (sum(stats["tool_scores"]) / cnt) if cnt else 0.0
        stats["avg_reply"] = (sum(stats["reply_scores"]) / cnt) if cnt else 0.0

    # 4. Print Summary to Console
    print("\n" + "=" * 72)
    print(f" BENCHMARK RESULTS ({t_elapsed:.2f}s total)")
    print("=" * 72)
    print(f"Overall Weighted Score: {overall_score:.1f}%")
    print(f"Strict Pass Rate:       {passed_cases}/{total_cases} ({overall_pass_rate:.1f}%)")
    print(f"Avg LLM Calls / Turn:   {avg_llm_calls:.2f}")
    print(f"Avg Tokens / Turn:      {avg_tokens:.1f}")
    print(f"Total Turns Evaluated:  {total_turns}")
    print("-" * 72)
    print(f"{'Category':<26} | {'Passed':<6} | {'Total':<5} | {'Rate':<7} | {'Avg Score':<9}")
    print("-" * 72)
    for cat, stats in sorted(category_summary.items()):
        print(f"{cat:<26} | {stats['passed']:<6} | {stats['count']:<5} | {stats['pass_rate']:>5.1f}% | {stats['avg_score']:>8.1f}%")
    print("=" * 72)

    # Print failures to console
    failures = [r for r in results if not r["passed"]]
    if failures:
        print(f"\nFAILURE BREAKDOWN ({len(failures)} cases):")
        print("-" * 72)
        for f in failures:
            print(f"• [{f['case_id']}] ({f['category']}) - Score: {f['total_score']:.1f}%")
            print(f"    Expected Decision: {f['expected'].get('decision')} | Actual: {f['actual'].get('decision')}")
            for reason in f["failure_reasons"]:
                print(f"    -> {reason}")
            print(f"    Tools called: {f['actual'].get('tools_called')}")
            print(f"    Trace steps: {len(f['trace'])} turn(s)")
            print()

    # 5. Write Report Markdown
    report_content = generate_report_markdown(
        results=results,
        overall_score=overall_score,
        overall_pass_rate=overall_pass_rate,
        category_summary=category_summary,
        avg_llm_calls=avg_llm_calls,
        avg_tokens=avg_tokens,
        total_turns=total_turns
    )

    out_dir = os.path.dirname(os.path.abspath(args.out))
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    with open(args.out, "w", encoding="utf-8") as f:
        f.write(report_content)
    print(f"\nReport written to: {args.out}")

    # 6. Min-Score Verification
    if min_score_threshold is not None:
        if overall_score < min_score_threshold:
            print(f"\n❌ FAILED: Overall score {overall_score:.1f}% is below required minimum threshold {min_score_threshold:.1f}%.")
            sys.exit(1)
        else:
            print(f"\n✅ PASSED: Overall score {overall_score:.1f}% meets/exceeds required minimum threshold {min_score_threshold:.1f}%.")

    sys.exit(0)


if __name__ == "__main__":
    main()
