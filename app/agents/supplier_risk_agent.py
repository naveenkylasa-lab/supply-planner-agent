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


class SupplierCapacityRiskAgent:
    """
    Phase 3 Agent: Supplier Capacity & Lead-Time Risk Agent.

    Uses Tier-2 (`deep`) model routing and Native LLM Tool Calling with explicit JSON Schemas:
    - `evaluate_supplier_capacity_and_leadtime_risk`
    """

    AGENT_NAME = "Supplier Capacity & Lead-Time Risk Agent"

    def __init__(self, llm_client: HybridLLMClient) -> None:
        self.llm_client = llm_client

    def run(
        self,
        submission: SupplyPlanSubmission,
        triage_output: TriagePhaseOutput,
        forecast_assessment: PhaseAssessment,
    ) -> PhaseAssessment:
        with start_otel_span(
            "agent.supplier_risk.run",
            {
                "agent.name": self.AGENT_NAME,
                "sku.id": submission.sku_id,
                "supplier.name": submission.supplier.primary_supplier_name,
            },
        ) as span:
            effective_weekly_demand = float(
                forecast_assessment.quantitative_metrics.get(
                    "effective_weekly_demand_units",
                    submission.demand.weekly_demand_mean,
                )
            )

            default_tool_args: Dict[str, Dict[str, Any]] = {
                "evaluate_supplier_capacity_and_leadtime_risk": {
                    "primary_supplier_name": submission.supplier.primary_supplier_name,
                    "primary_country": submission.supplier.primary_country,
                    "backup_supplier_available": submission.supplier.backup_supplier_available,
                    "lead_time_days_mean": submission.supplier.lead_time_days_mean,
                    "lead_time_days_std_dev": submission.supplier.lead_time_days_std_dev,
                    "on_time_in_full_pct": submission.supplier.on_time_in_full_pct,
                    "defect_rate_ppm": submission.supplier.defect_rate_ppm,
                    "max_weekly_capacity_units": submission.supplier.max_weekly_capacity_units,
                    "effective_weekly_demand_units": effective_weekly_demand,
                    "active_geopolitical_or_port_disruption": submission.supplier.active_geopolitical_or_port_disruption,
                    "single_source_dependency": submission.supplier.single_source_dependency,
                }
            }

            system_prompt = (
                "You are the Supplier Capacity & Lead-Time Risk Agent (Phase 3 of S&OP Supply Planning). "
                "Call `evaluate_supplier_capacity_and_leadtime_risk` using the strict JSON schema to audit "
                "supplier utilization, OTIF reliability, geopolitical/port disruptions, and dual-sourcing.\n\n"
                f"{SUPPLY_CHAIN_CONSTITUTION}"
            )
            user_prompt = (
                f"Evaluate supplier network risk for SKU '{submission.sku_id}' "
                f"(Primary Supplier: {submission.supplier.primary_supplier_name}, Country: {submission.supplier.primary_country}):\n"
                f"{json.dumps(default_tool_args['evaluate_supplier_capacity_and_leadtime_risk'], indent=2)}"
            )

            def _fallback_synthesis(tool_outputs: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
                sup_out = tool_outputs["evaluate_supplier_capacity_and_leadtime_risk"]
                controls: List[str] = []
                if sup_out["recommended_backup_allocation_pct"] > 0 and submission.supplier.backup_supplier_name:
                    controls.append(
                        f"Execute dual-source split: allocate {sup_out['recommended_backup_allocation_pct']:.0f}% of PO volume to backup supplier '{submission.supplier.backup_supplier_name}'."
                    )
                if submission.supplier.single_source_dependency:
                    controls.append(
                        "Initiate emergency engineering qualification of secondary foundry/OSAT partner and secure 6-week wafer/die buffer commitment."
                    )
                if submission.supplier.active_geopolitical_or_port_disruption:
                    controls.append(
                        "Reroute critical shipments via priority air corridor to bypass port congestion on primary ocean lane."
                    )
                if not controls:
                    controls.append(
                        "Maintain standard supplier scorecard monitoring and quarterly capacity reservation review."
                    )

                summary = (
                    f"Primary supplier '{submission.supplier.primary_supplier_name}' ({submission.supplier.primary_country}) "
                    f"utilization is {sup_out['capacity_utilization_pct']:.1f}% with {submission.supplier.on_time_in_full_pct:.1f}% OTIF. "
                    f"Supplier risk score = {sup_out['supplier_risk_score']}/100 ({sup_out['risk_level']}). "
                    f"Recommended backup allocation = {sup_out['recommended_backup_allocation_pct']:.0f}%."
                )
                return {
                    "risk_score": int(sup_out["supplier_risk_score"]),
                    "risk_level": RiskLevel(sup_out["risk_level"]),
                    "key_findings": list(sup_out["findings"]),
                    "recommended_controls": controls,
                    "executive_summary": summary,
                }

            result_bundle = self.llm_client.execute_agent_with_tools(
                agent_name=self.AGENT_NAME,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                tool_names=["evaluate_supplier_capacity_and_leadtime_risk"],
                default_tool_call_args=default_tool_args,
                fallback_synthesis_fn=_fallback_synthesis,
                model_tier="deep",
            )

            sup_data = result_bundle["tool_outputs"]["evaluate_supplier_capacity_and_leadtime_risk"]
            synth = result_bundle["synthesis"]

            assessment = PhaseAssessment(
                phase_name="Phase 3 — Supplier Capacity & Lead-Time Resilience",
                agent_name=self.AGENT_NAME,
                model_used=self.llm_client.get_model_for_tier("deep"),
                risk_score=int(synth["risk_score"]),
                risk_level=RiskLevel(synth["risk_level"]),
                key_findings=list(synth["key_findings"]),
                recommended_actions=list(synth["recommended_controls"]),
                quantitative_metrics={
                    **sup_data,
                    "tool_invocation_mode": result_bundle["invocation_mode"],
                },
                llm_narrative=synth["executive_summary"],
            )
            span.set_attribute("supplier.risk_score", assessment.risk_score)
            span.set_attribute("supplier.utilization_pct", sup_data["capacity_utilization_pct"])
            return assessment
