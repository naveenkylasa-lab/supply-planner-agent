from __future__ import annotations

from typing import List

from app.llm_client import HybridLLMClient
from app.models import (
    FinalSupplyPlanDecision,
    PhaseAssessment,
    ReplenishmentDecisionStatus,
    RiskLevel,
    SKUClassificationTier,
    SupplyPlanSubmission,
    TriagePhaseOutput,
)
from app.observability import start_otel_span
from app.supply_constitution import SUPPLY_CHAIN_CONSTITUTION


class MasterSupplyPlannerAgent:
    """
    Phase 5 Agent: Master Supply Planner & S&OP Governance Agent.

    Synthesizes Phases 1–4 into a weighted composite supply risk score, enforces
    Supply Chain Constitution Article V (Human-in-the-Loop Code Stop when working capital,
    expedite capex > $25k, or critical single-source stockout thresholds trigger),
    and produces the final executive S&OP memo.
    """

    AGENT_NAME = "Master Supply Planner & S&OP Governance Agent"

    def __init__(self, llm_client: HybridLLMClient) -> None:
        self.llm_client = llm_client

    def run(
        self,
        submission: SupplyPlanSubmission,
        triage_output: TriagePhaseOutput,
        forecast_assessment: PhaseAssessment,
        supplier_assessment: PhaseAssessment,
        replenishment_assessment: PhaseAssessment,
    ) -> FinalSupplyPlanDecision:
        with start_otel_span(
            "agent.master_planner.run",
            {
                "agent.name": self.AGENT_NAME,
                "sku.id": submission.sku_id,
                "sku.tier": triage_output.sku_tier.value,
            },
        ) as span:
            # Weighted composite score: 30% Demand/Forecast + 40% Supplier/Lead-Time + 30% Financial/MRP
            composite_score = round(
                (0.30 * forecast_assessment.risk_score)
                + (0.40 * supplier_assessment.risk_score)
                + (0.30 * replenishment_assessment.risk_score),
                1,
            )

            if composite_score >= 70.0:
                overall_level = RiskLevel.CRITICAL
            elif composite_score >= 45.0:
                overall_level = RiskLevel.HIGH
            elif composite_score >= 25.0:
                overall_level = RiskLevel.MODERATE
            else:
                overall_level = RiskLevel.LOW

            f_metrics = forecast_assessment.quantitative_metrics
            r_metrics = replenishment_assessment.quantitative_metrics

            safety_stock_units = int(f_metrics.get("statistical_safety_stock_units", 0))
            reorder_point_units = int(f_metrics.get("reorder_point_units", 0))
            total_order_units = int(r_metrics.get("recommended_total_order_units", 0))
            primary_order_units = int(r_metrics.get("primary_supplier_order_units", 0))
            backup_order_units = int(r_metrics.get("backup_supplier_order_units", 0))
            expedite_units = int(r_metrics.get("expedite_units", 0))
            total_po_spend_usd = float(r_metrics.get("total_po_spend_usd", 0.0))
            expedite_freight_cost_usd = float(r_metrics.get("expedite_freight_cost_usd", 0.0))
            exceeds_budget = bool(r_metrics.get("exceeds_working_capital_budget", False))

            # Constitutional Article V HITL Governance Check
            hitl_reasons: List[str] = []
            if total_po_spend_usd > submission.financials.working_capital_budget_usd:
                hitl_reasons.append(
                    f"Total PO spend (${total_po_spend_usd:,.2f}) exceeds working capital budget (${submission.financials.working_capital_budget_usd:,.2f}) [Article IV]."
                )
            if expedite_freight_cost_usd > 25000.0:
                hitl_reasons.append(
                    f"Expedited air freight cost (${expedite_freight_cost_usd:,.2f}) exceeds $25,000 autonomous capex ceiling [Article IV]."
                )
            if composite_score >= 75.0:
                hitl_reasons.append(
                    f"Composite supply risk score ({composite_score}/100) exceeds autonomous release ceiling (75.0) [Article V]."
                )
            if (
                triage_output.sku_tier == SKUClassificationTier.CLASS_A_CRITICAL
                and submission.supplier.single_source_dependency
                and submission.supplier.active_geopolitical_or_port_disruption
            ):
                hitl_reasons.append(
                    "CLASS_A_CRITICAL single-source SKU faces active port/geopolitical disruption and immediate stockout exposure [Article V]."
                )

            requires_hitl = len(hitl_reasons) > 0

            if requires_hitl:
                decision_status = ReplenishmentDecisionStatus.HOLD_FOR_EXECUTIVE_SOP_APPROVAL
            elif backup_order_units > 0 or expedite_units > 0 or composite_score >= 35.0:
                decision_status = ReplenishmentDecisionStatus.RELEASE_WITH_DUAL_SOURCE_AND_EXPEDITE
            else:
                decision_status = ReplenishmentDecisionStatus.AUTO_RELEASE_PO

            conditions: List[str] = []
            for phase in (forecast_assessment, supplier_assessment, replenishment_assessment):
                for action in phase.recommended_actions:
                    if action not in conditions:
                        conditions.append(action)

            system_prompt = (
                "You are the Master Supply Planner & S&OP Governance Agent (Phase 5). "
                "Write a concise, authoritative executive S&OP memo summarizing the replenishment plan, "
                "safety stock parameters, supplier split, financial commitment, and constitutional governance status.\n\n"
                f"{SUPPLY_CHAIN_CONSTITUTION}"
            )
            user_prompt = (
                f"SKU: {submission.sku_id} ({submission.sku_name})\n"
                f"Tier: {triage_output.sku_tier.value} ({triage_output.abc_xyz_class})\n"
                f"Composite Risk Score: {composite_score}/100 ({overall_level.value})\n"
                f"Decision: {decision_status.value}\n"
                f"Safety Stock: {safety_stock_units:,} units | ROP: {reorder_point_units:,} units\n"
                f"Total Order: {total_order_units:,} units (Primary: {primary_order_units:,}, Backup: {backup_order_units:,}, Expedite: {expedite_units:,})\n"
                f"Total PO Spend: ${total_po_spend_usd:,.2f} (Expedite Freight: ${expedite_freight_cost_usd:,.2f})\n"
                f"HITL Reasons: {hitl_reasons}"
            )

            def _fallback_memo() -> str:
                if requires_hitl:
                    gov_line = (
                        f"MANDATORY EXECUTIVE S&OP HOLD TRIGGERED (Article V): {'; '.join(hitl_reasons)} "
                        "Autonomous ERP purchase order release has been paused pending VP of Supply Chain / CFO override."
                    )
                else:
                    gov_line = (
                        f"CONSTITUTIONAL COMPLIANCE VERIFIED: Purchase order packet ({total_order_units:,} units, "
                        f"${total_po_spend_usd:,.2f}) is cleared for ERP release under status {decision_status.value}."
                    )
                return (
                    f"EXECUTIVE S&OP REPLENISHMENT MEMO — {submission.sku_id} ({submission.sku_name}): "
                    f"Classified as {triage_output.sku_tier.value} (ABC/XYZ {triage_output.abc_xyz_class}) with "
                    f"composite supply risk score {composite_score}/100 ({overall_level.value}). "
                    f"Statistical safety stock is set at {safety_stock_units:,} units (ROP {reorder_point_units:,} units). "
                    f"MRP optimization recommends releasing {total_order_units:,} total units "
                    f"({primary_order_units:,} primary, {backup_order_units:,} dual-source backup, "
                    f"{expedite_units:,} expedited air freight) for a total commitment of ${total_po_spend_usd:,.2f}. "
                    f"{gov_line}"
                )

            executive_memo = self.llm_client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                fallback_fn=_fallback_memo,
                model_tier="deep",
            )

            decision = FinalSupplyPlanDecision(
                sku_id=submission.sku_id,
                sku_name=submission.sku_name,
                sku_tier=triage_output.sku_tier,
                composite_risk_score=composite_score,
                overall_risk_level=overall_level,
                decision_status=decision_status,
                requires_human_review=requires_hitl,
                human_review_reason=" | ".join(hitl_reasons) if hitl_reasons else None,
                recommended_safety_stock_units=safety_stock_units,
                recommended_reorder_point_units=reorder_point_units,
                recommended_order_qty_units=total_order_units,
                primary_supplier_order_units=primary_order_units,
                backup_supplier_order_units=backup_order_units,
                expedite_air_units=expedite_units,
                total_po_spend_usd=total_po_spend_usd,
                expedite_freight_cost_usd=expedite_freight_cost_usd,
                mandatory_mitigation_actions=conditions,
                executive_sop_memo=executive_memo,
            )
            span.set_attribute("decision.status", decision_status.value)
            span.set_attribute("decision.requires_human_review", requires_hitl)
            span.set_attribute("decision.composite_risk_score", composite_score)
            return decision
