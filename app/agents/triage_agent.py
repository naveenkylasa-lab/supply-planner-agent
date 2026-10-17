from __future__ import annotations

import json
from typing import Any, Dict

from app.llm_client import HybridLLMClient
from app.models import (
    RiskLevel,
    SKUClassificationTier,
    SupplyPlanSubmission,
    TriagePhaseOutput,
)
from app.observability import start_otel_span
from app.supply_constitution import SUPPLY_CHAIN_CONSTITUTION
from app.tools import extract_erp_inventory_positions


class DemandInventoryTriageAgent:
    """
    Phase 1 Agent: Demand & Inventory Triage Agent.

    Uses Tier-1 (`fast`) model routing and Native LLM Tool Calling with explicit JSON Schemas:
    - `extract_erp_inventory_positions`
    - `classify_sku_abc_xyz_criticality`
    """

    AGENT_NAME = "Demand & Inventory Triage Agent"

    def __init__(self, llm_client: HybridLLMClient) -> None:
        self.llm_client = llm_client

    def run(self, submission: SupplyPlanSubmission) -> TriagePhaseOutput:
        with start_otel_span(
            "agent.triage.run",
            {
                "agent.name": self.AGENT_NAME,
                "sku.id": submission.sku_id,
                "sku.name": submission.sku_name,
            },
        ) as span:
            # First compute ERP inventory position so its `immediate_stockout_risk` feeds into ABC/XYZ classification
            erp_preview = extract_erp_inventory_positions(
                sku_id=submission.sku_id,
                sku_name=submission.sku_name,
                plant_code=submission.plant_code,
                on_hand_units=submission.inventory.on_hand_units,
                allocated_units=submission.inventory.allocated_units,
                in_transit_units=submission.inventory.in_transit_units,
                open_po_units=submission.inventory.open_po_units,
                quality_hold_units=submission.inventory.quality_hold_units,
                backorder_units=submission.inventory.backorder_units,
                weekly_demand_mean=submission.demand.weekly_demand_mean,
                unstructured_erp_notes=submission.unstructured_erp_notes,
            )

            default_tool_args: Dict[str, Dict[str, Any]] = {
                "extract_erp_inventory_positions": {
                    "sku_id": submission.sku_id,
                    "sku_name": submission.sku_name,
                    "plant_code": submission.plant_code,
                    "on_hand_units": submission.inventory.on_hand_units,
                    "allocated_units": submission.inventory.allocated_units,
                    "in_transit_units": submission.inventory.in_transit_units,
                    "open_po_units": submission.inventory.open_po_units,
                    "quality_hold_units": submission.inventory.quality_hold_units,
                    "backorder_units": submission.inventory.backorder_units,
                    "weekly_demand_mean": submission.demand.weekly_demand_mean,
                    "unstructured_erp_notes": submission.unstructured_erp_notes,
                },
                "classify_sku_abc_xyz_criticality": {
                    "unit_cost_usd": submission.financials.unit_cost_usd,
                    "weekly_demand_mean": submission.demand.weekly_demand_mean,
                    "weekly_demand_std_dev": submission.demand.weekly_demand_std_dev,
                    "is_revenue_critical_bom": submission.financials.is_revenue_critical_bom,
                    "single_source_dependency": submission.supplier.single_source_dependency,
                    "active_geopolitical_or_port_disruption": submission.supplier.active_geopolitical_or_port_disruption,
                    "immediate_stockout_risk": bool(erp_preview["immediate_stockout_risk"]),
                    "customer_sla_penalty_per_day_usd": submission.financials.customer_sla_penalty_per_day_usd,
                },
            }

            system_prompt = (
                "You are the Demand & Inventory Triage Agent (Phase 1 of S&OP Supply Planning). "
                "Call `extract_erp_inventory_positions` and `classify_sku_abc_xyz_criticality` using "
                "strict JSON schemas and summarize net ATP inventory, weeks of supply, and ABC/XYZ tier.\n\n"
                f"{SUPPLY_CHAIN_CONSTITUTION}"
            )
            user_prompt = (
                f"Evaluate SKU '{submission.sku_id}' ({submission.sku_name}) at plant {submission.plant_code}:\n"
                f"{json.dumps(submission.model_dump(mode='json'), indent=2)}"
            )

            def _fallback_synthesis(tool_outputs: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
                inv_out = tool_outputs["extract_erp_inventory_positions"]
                cls_out = tool_outputs["classify_sku_abc_xyz_criticality"]
                urg = int(cls_out["stockout_urgency_score"])
                if urg >= 70:
                    r_level = RiskLevel.CRITICAL
                elif urg >= 45:
                    r_level = RiskLevel.HIGH
                elif urg >= 25:
                    r_level = RiskLevel.MODERATE
                else:
                    r_level = RiskLevel.LOW

                summary = (
                    f"SKU {submission.sku_id} classified as {cls_out['sku_tier']} (ABC/XYZ: {cls_out['abc_xyz_class']}). "
                    f"Net ATP on-hand = {inv_out['net_available_on_hand_units']:,} units "
                    f"({inv_out['weeks_of_supply_on_hand']:.2f} weeks cover); Total net position = "
                    f"{inv_out['net_inventory_position_units']:,} units ({inv_out['days_of_supply_total']:.1f} days cover)."
                )
                return {
                    "risk_score": urg,
                    "risk_level": r_level,
                    "key_findings": list(cls_out["triggers"]),
                    "recommended_controls": [
                        "Enforce Article I ABC/XYZ service level target in downstream safety stock calculation.",
                        "Scrub personal planner contact PII from ERP exception logs before S&OP archival.",
                    ],
                    "executive_summary": summary,
                }

            result_bundle = self.llm_client.execute_agent_with_tools(
                agent_name=self.AGENT_NAME,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                tool_names=[
                    "extract_erp_inventory_positions",
                    "classify_sku_abc_xyz_criticality",
                ],
                default_tool_call_args=default_tool_args,
                fallback_synthesis_fn=_fallback_synthesis,
                model_tier="fast",
            )

            inv_data = result_bundle["tool_outputs"]["extract_erp_inventory_positions"]
            cls_data = result_bundle["tool_outputs"]["classify_sku_abc_xyz_criticality"]
            synth = result_bundle["synthesis"]

            triage_output = TriagePhaseOutput(
                sku_tier=SKUClassificationTier(cls_data["sku_tier"]),
                abc_xyz_class=cls_data["abc_xyz_class"],
                stockout_urgency_score=int(cls_data["stockout_urgency_score"]),
                net_available_on_hand_units=int(inv_data["net_available_on_hand_units"]),
                net_inventory_position_units=int(inv_data["net_inventory_position_units"]),
                weeks_of_supply_on_hand=float(inv_data["weeks_of_supply_on_hand"]),
                days_of_supply_total=float(inv_data["days_of_supply_total"]),
                immediate_stockout_risk=bool(inv_data["immediate_stockout_risk"]),
                sanitized_erp_notes=str(inv_data["sanitized_erp_notes"]),
                extracted_erp_entities={
                    **inv_data.get("parsed_entities", {}),
                    "annual_spend_usd": cls_data["annual_spend_usd"],
                    "tool_invocation_mode": result_bundle["invocation_mode"],
                },
                triage_rationale=synth["executive_summary"],
            )
            span.set_attribute("triage.sku_tier", triage_output.sku_tier.value)
            span.set_attribute("triage.urgency_score", triage_output.stockout_urgency_score)
            return triage_output
