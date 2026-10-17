from __future__ import annotations

import json
from typing import Any, Dict, List

from app.llm_client import HybridLLMClient
from app.models import (
    PhaseAssessment,
    RiskLevel,
    SupplyPlanSubmission,
    TriagePhaseOutput,
)
from app.observability import start_otel_span
from app.supply_constitution import SUPPLY_CHAIN_CONSTITUTION


class ReplenishmentOptimizerAgent:
    """
    Phase 4 Agent: Replenishment & PO Optimizer Agent.

    Uses Tier-2 (`deep`) model routing and Native LLM Tool Calling with explicit JSON Schemas:
    - `optimize_mrp_replenishment_orders`
    """

    AGENT_NAME = "Replenishment & PO Optimizer Agent"

    def __init__(self, llm_client: HybridLLMClient) -> None:
        self.llm_client = llm_client

    def run(
        self,
        submission: SupplyPlanSubmission,
        triage_output: TriagePhaseOutput,
        forecast_assessment: PhaseAssessment,
        supplier_assessment: PhaseAssessment,
    ) -> PhaseAssessment:
        with start_otel_span(
            "agent.replenishment.run",
            {
                "agent.name": self.AGENT_NAME,
                "sku.id": submission.sku_id,
                "mrp.budget_usd": submission.financials.working_capital_budget_usd,
            },
        ) as span:
            effective_weekly_demand = float(
                forecast_assessment.quantitative_metrics.get(
                    "effective_weekly_demand_units",
                    submission.demand.weekly_demand_mean,
                )
            )
            safety_stock_units = int(
                forecast_assessment.quantitative_metrics.get("statistical_safety_stock_units", 0)
            )
            reorder_point_units = int(
                forecast_assessment.quantitative_metrics.get("reorder_point_units", 0)
            )
            recommended_backup_pct = float(
                supplier_assessment.quantitative_metrics.get("recommended_backup_allocation_pct", 0.0)
            )

            default_tool_args: Dict[str, Dict[str, Any]] = {
                "optimize_mrp_replenishment_orders": {
                    "net_inventory_position_units": triage_output.net_inventory_position_units,
                    "net_available_on_hand_units": triage_output.net_available_on_hand_units,
                    "effective_weekly_demand_units": effective_weekly_demand,
                    "planning_horizon_weeks": submission.planning_horizon_weeks,
                    "statistical_safety_stock_units": safety_stock_units,
                    "reorder_point_units": reorder_point_units,
                    "minimum_order_qty": submission.supplier.minimum_order_qty,
                    "lot_size_multiple": submission.supplier.lot_size_multiple,
                    "unit_cost_usd": submission.financials.unit_cost_usd,
                    "standard_freight_per_unit_usd": submission.financials.standard_freight_per_unit_usd,
                    "expedite_air_freight_per_unit_usd": submission.financials.expedite_air_freight_per_unit_usd,
                    "stockout_penalty_per_unit_usd": submission.financials.stockout_penalty_per_unit_usd,
                    "customer_sla_penalty_per_day_usd": submission.financials.customer_sla_penalty_per_day_usd,
                    "working_capital_budget_usd": submission.financials.working_capital_budget_usd,
                    "backup_supplier_available": submission.supplier.backup_supplier_available,
                    "recommended_backup_allocation_pct": recommended_backup_pct,
                    "backup_unit_cost_premium_pct": submission.supplier.backup_unit_cost_premium_pct,
                }
            }

            system_prompt = (
                "You are the Replenishment & PO Optimizer Agent (Phase 4 of S&OP Supply Planning). "
                "Call `optimize_mrp_replenishment_orders` using the strict JSON schema to solve "
                "net MRP requirements, MOQ/lot-sizing, dual-source PO splits, and expedite freight allocation.\n\n"
                f"{SUPPLY_CHAIN_CONSTITUTION}"
            )
            user_prompt = (
                f"Optimize replenishment purchase orders for SKU '{submission.sku_id}':\n"
                f"{json.dumps(default_tool_args['optimize_mrp_replenishment_orders'], indent=2)}"
            )

            def _fallback_synthesis(tool_outputs: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
                mrp_out = tool_outputs["optimize_mrp_replenishment_orders"]
                controls: List[str] = [
                    f"Issue primary supplier PO for {mrp_out['primary_supplier_order_units']:,} units (MOQ {submission.supplier.minimum_order_qty:,}, lot multiple {submission.supplier.lot_size_multiple:,})."
                ]
                if mrp_out["backup_supplier_order_units"] > 0:
                    controls.append(
                        f"Issue secondary split PO for {mrp_out['backup_supplier_order_units']:,} units to qualified backup supplier."
                    )
                if mrp_out["expedite_units"] > 0:
                    controls.append(
                        f"Book priority air freight for {mrp_out['expedite_units']:,} units (${mrp_out['expedite_freight_cost_usd']:,.2f}) to prevent immediate line-down/SLA breach."
                    )
                if mrp_out["exceeds_working_capital_budget"]:
                    controls.append(
                        "Escalate PO packet to Executive S&OP / CFO Governance Committee for working-capital & expedite capex sign-off (Article IV & V)."
                    )

                summary = (
                    f"Recommended total PO release = {mrp_out['recommended_total_order_units']:,} units "
                    f"(Primary: {mrp_out['primary_supplier_order_units']:,}, Backup: {mrp_out['backup_supplier_order_units']:,}, "
                    f"Expedite Air: {mrp_out['expedite_units']:,}). Total PO commitment = ${mrp_out['total_po_spend_usd']:,.2f} "
                    f"({mrp_out['budget_utilization_pct']:.1f}% of working capital budget)."
                )
                return {
                    "risk_score": int(mrp_out["financial_risk_score"]),
                    "risk_level": RiskLevel(mrp_out["risk_level"]),
                    "key_findings": list(mrp_out["findings"]),
                    "recommended_controls": controls,
                    "executive_summary": summary,
                }

            result_bundle = self.llm_client.execute_agent_with_tools(
                agent_name=self.AGENT_NAME,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                tool_names=["optimize_mrp_replenishment_orders"],
                default_tool_call_args=default_tool_args,
                fallback_synthesis_fn=_fallback_synthesis,
                model_tier="deep",
            )

            mrp_data = result_bundle["tool_outputs"]["optimize_mrp_replenishment_orders"]
            synth = result_bundle["synthesis"]

            assessment = PhaseAssessment(
                phase_name="Phase 4 — MRP Replenishment & Working Capital Optimization",
                agent_name=self.AGENT_NAME,
                model_used=self.llm_client.get_model_for_tier("deep"),
                risk_score=int(synth["risk_score"]),
                risk_level=RiskLevel(synth["risk_level"]),
                key_findings=list(synth["key_findings"]),
                recommended_actions=list(synth["recommended_controls"]),
                quantitative_metrics={
                    **mrp_data,
                    "tool_invocation_mode": result_bundle["invocation_mode"],
                },
                llm_narrative=synth["executive_summary"],
            )
            span.set_attribute("replenishment.total_order_units", mrp_data["recommended_total_order_units"])
            span.set_attribute("replenishment.total_po_spend_usd", mrp_data["total_po_spend_usd"])
            return assessment
