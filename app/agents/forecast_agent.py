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


class ForecastSafetyStockAgent:
    """
    Phase 2 Agent: Forecast & Safety Stock Agent.

    Uses Tier-2 (`deep`) model routing and Native LLM Tool Calling with explicit JSON Schemas:
    - `calculate_statistical_safety_stock`
    """

    AGENT_NAME = "Forecast & Safety Stock Agent"

    def __init__(self, llm_client: HybridLLMClient) -> None:
        self.llm_client = llm_client

    def run(
        self,
        submission: SupplyPlanSubmission,
        triage_output: TriagePhaseOutput,
    ) -> PhaseAssessment:
        with start_otel_span(
            "agent.forecast.run",
            {
                "agent.name": self.AGENT_NAME,
                "sku.id": submission.sku_id,
                "sku.tier": triage_output.sku_tier.value,
            },
        ) as span:
            default_tool_args: Dict[str, Dict[str, Any]] = {
                "calculate_statistical_safety_stock": {
                    "weekly_demand_mean": submission.demand.weekly_demand_mean,
                    "weekly_demand_std_dev": submission.demand.weekly_demand_std_dev,
                    "firm_customer_orders_4w": submission.demand.firm_customer_orders_4w,
                    "promotional_uplift_pct": submission.demand.promotional_uplift_pct,
                    "forecast_mape_pct": submission.demand.forecast_mape_pct,
                    "seasonality_index": submission.demand.seasonality_index,
                    "lead_time_days_mean": submission.supplier.lead_time_days_mean,
                    "lead_time_days_std_dev": submission.supplier.lead_time_days_std_dev,
                    "target_service_level": submission.target_service_level,
                }
            }

            system_prompt = (
                "You are the Forecast & Safety Stock Agent (Phase 2 of S&OP Supply Planning). "
                "Call `calculate_statistical_safety_stock` using the strict JSON schema to compute "
                "statistical safety stock and Reorder Point (ROP) under coupled demand and lead-time variance.\n\n"
                f"{SUPPLY_CHAIN_CONSTITUTION}"
            )
            user_prompt = (
                f"Compute statistical safety stock and ROP for SKU '{submission.sku_id}' "
                f"(Tier: {triage_output.sku_tier.value}, Target Service Level: {submission.target_service_level * 100:.1f}%):\n"
                f"{json.dumps(default_tool_args['calculate_statistical_safety_stock'], indent=2)}"
            )

            def _fallback_synthesis(tool_outputs: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
                ss_out = tool_outputs["calculate_statistical_safety_stock"]
                controls: List[str] = [
                    f"Maintain statistical safety stock buffer of {ss_out['statistical_safety_stock_units']:,} units (Z={ss_out['z_score']:.2f}).",
                    f"Trigger automated MRP replenishment whenever net inventory position drops below ROP of {ss_out['reorder_point_units']:,} units.",
                ]
                if submission.demand.forecast_mape_pct >= 18.0:
                    controls.append(
                        "Implement weekly collaborative demand-sensing cadence with top hyperscale/OEM customers to reduce MAPE below 15%."
                    )

                summary = (
                    f"Effective weekly demand is {ss_out['effective_weekly_demand_units']:,.1f} units/wk. "
                    f"At {submission.target_service_level * 100:.1f}% cycle service level (Z={ss_out['z_score']:.2f}), "
                    f"required safety stock is {ss_out['statistical_safety_stock_units']:,} units and Reorder Point (ROP) "
                    f"is {ss_out['reorder_point_units']:,} units."
                )
                return {
                    "risk_score": int(ss_out["demand_volatility_score"]),
                    "risk_level": RiskLevel(ss_out["risk_level"]),
                    "key_findings": list(ss_out["findings"]),
                    "recommended_controls": controls,
                    "executive_summary": summary,
                }

            result_bundle = self.llm_client.execute_agent_with_tools(
                agent_name=self.AGENT_NAME,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                tool_names=["calculate_statistical_safety_stock"],
                default_tool_call_args=default_tool_args,
                fallback_synthesis_fn=_fallback_synthesis,
                model_tier="deep",
            )

            ss_data = result_bundle["tool_outputs"]["calculate_statistical_safety_stock"]
            synth = result_bundle["synthesis"]

            assessment = PhaseAssessment(
                phase_name="Phase 2 — Demand Sensing & Statistical Safety Stock",
                agent_name=self.AGENT_NAME,
                model_used=self.llm_client.get_model_for_tier("deep"),
                risk_score=int(synth["risk_score"]),
                risk_level=RiskLevel(synth["risk_level"]),
                key_findings=list(synth["key_findings"]),
                recommended_actions=list(synth["recommended_controls"]),
                quantitative_metrics={
                    **ss_data,
                    "tool_invocation_mode": result_bundle["invocation_mode"],
                },
                llm_narrative=synth["executive_summary"],
            )
            span.set_attribute("forecast.safety_stock_units", ss_data["statistical_safety_stock_units"])
            span.set_attribute("forecast.reorder_point_units", ss_data["reorder_point_units"])
            return assessment
