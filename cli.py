from __future__ import annotations

import argparse
import json
import sys

from app.orchestrator import SupplyPlanningOrchestrator
from app.sample_skus import PRESET_SKUS


def print_plan_summary(result_dict: dict) -> None:
    sub = result_dict["submission"]
    triage = result_dict["triage_output"]
    dec = result_dict["final_decision"]

    print("=" * 88)
    print(f"SUPPLY PLAN ID   : {result_dict['plan_id']}  |  W3C TRACE ID: {result_dict['trace_id']}")
    print(f"SKU              : {sub['sku_id']} — {sub['sku_name']} ({sub['plant_code']})")
    print(f"ABC/XYZ TIER     : {triage['sku_tier']} ({triage['abc_xyz_class']}) | Urgency: {triage['stockout_urgency_score']}/100")
    print(f"NET ATP ON-HAND  : {triage['net_available_on_hand_units']:,} units ({triage['weeks_of_supply_on_hand']} wks cover)")
    print(f"SAFETY STOCK/ROP : Safety Stock = {dec['recommended_safety_stock_units']:,} units | ROP = {dec['recommended_reorder_point_units']:,} units")
    print(
        f"RECOMMENDED PO   : {dec['recommended_order_qty_units']:,} units "
        f"(Primary: {dec['primary_supplier_order_units']:,} | Backup: {dec['backup_supplier_order_units']:,} | Expedite Air: {dec['expedite_air_units']:,})"
    )
    print(
        f"TOTAL PO SPEND   : ${dec['total_po_spend_usd']:,.2f} "
        f"(Expedite Freight: ${dec['expedite_freight_cost_usd']:,.2f})"
    )
    print(f"COMPOSITE RISK   : {dec['composite_risk_score']}/100 ({dec['overall_risk_level']})")
    print(f"S&OP DECISION    : {dec['decision_status']} (Requires HITL: {dec['requires_human_review']})")
    if dec.get("human_review_reason"):
        print(f"HITL CODE STOP   : {dec['human_review_reason']}")
    print(f"PII-SCRUBBED ERP : {triage['sanitized_erp_notes']}")
    print("-" * 88)
    print(f"EXECUTIVE MEMO   :\n{dec['executive_sop_memo']}")
    print("=" * 88)
    print()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Supply Planner Agent CLI — Multi-Agent S&OP & MRP Control Tower"
    )
    parser.add_argument(
        "--preset",
        choices=list(PRESET_SKUS.keys()),
        default="sku_a_critical_asic",
        help="Preset SKU profile to evaluate",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all 4 preset SKU profiles sequentially",
    )
    parser.add_argument(
        "--ask",
        type=str,
        default=None,
        help="Ask a conversational S&OP policy or formula question",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output full JSON payload",
    )
    args = parser.parse_args()

    orchestrator = SupplyPlanningOrchestrator()

    if args.ask:
        reply = orchestrator.support_agent.answer_question(args.ask, [])
        print(reply)
        return 0

    keys = list(PRESET_SKUS.keys()) if args.all else [args.preset]
    for key in keys:
        submission = PRESET_SKUS[key]
        result = orchestrator.run_supply_plan(submission, persist_in_background=False)
        data = result.model_dump(mode="json")
        if args.json:
            print(json.dumps(data, indent=2))
        else:
            print_plan_summary(data)

    orchestrator.memory_store.flush_background_tasks()
    return 0


if __name__ == "__main__":
    sys.exit(main())
