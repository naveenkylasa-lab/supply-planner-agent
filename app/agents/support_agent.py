from __future__ import annotations

from typing import Dict, List

from app.llm_client import HybridLLMClient
from app.models import IntentClassificationStructuredSchema, IntentType
from app.observability import get_logger, redact_pii_text, start_otel_span
from app.supply_constitution import SUPPLY_CHAIN_CONSTITUTION


logger = get_logger("supply_planner.support_agent")


class ConversationalSOPSupportAgent:
    """
    Coordinator & Conversational S&OP Support Agent.

    Implements the Intent Router:
    - `PLANNER_QUESTION` -> Conversational Pattern (answers Supply Chain Constitution & S&OP queries
      using fast Flash/Mini tier and conversation memory).
    - `SUPPLY_PACKET_SUBMISSION` -> Sequential Multi-Agent Pipeline Pattern.
    """

    def __init__(self, llm_client: HybridLLMClient) -> None:
        self.llm_client = llm_client

    def classify_intent(self, message: str, has_supply_packet: bool = False) -> IntentClassificationStructuredSchema:
        with start_otel_span(
            "agent.support.classify_intent",
            {"agent.name": "ConversationalSOPSupportAgent", "has_supply_packet": has_supply_packet},
        ):
            if has_supply_packet:
                return IntentClassificationStructuredSchema(
                    intent=IntentType.SUPPLY_PACKET_SUBMISSION,
                    confidence=0.99,
                    reasoning="Structured ERP SupplyPlanSubmission packet was provided in the request payload.",
                )

            lower = message.lower()
            submission_keywords = [
                "run mrp",
                "submit sku",
                "execute supply plan",
                "release po for sku",
                "plan_submission",
            ]
            if any(k in lower for k in submission_keywords):
                return IntentClassificationStructuredSchema(
                    intent=IntentType.SUPPLY_PACKET_SUBMISSION,
                    confidence=0.92,
                    reasoning="Planner prompt explicitly requested full MRP/S&OP sequential supply plan execution.",
                )

            return IntentClassificationStructuredSchema(
                intent=IntentType.PLANNER_QUESTION,
                confidence=0.95,
                reasoning="Planner asked a policy, safety-stock formula, or S&OP governance question.",
            )

    def answer_question(
        self,
        question: str,
        conversation_history: List[Dict[str, str]],
    ) -> str:
        sanitized_question = redact_pii_text(question)
        history_block = "\n".join(
            f"{turn.get('role', 'user').upper()}: {turn.get('message', '')}"
            for turn in conversation_history[-6:]
        )

        system_prompt = (
            "You are the Enterprise S&OP Supply Planning Support Agent. Answer the supply planner's "
            "question concisely and accurately using the Enterprise Supply Chain Constitution below.\n\n"
            f"{SUPPLY_CHAIN_CONSTITUTION}"
        )
        user_prompt = (
            f"Conversation History:\n{history_block or '(New Session)'}\n\n"
            f"Supply Planner Question: {sanitized_question}"
        )

        def _fallback() -> str:
            q_lower = sanitized_question.lower()
            if "safety stock" in q_lower or "rop" in q_lower or "reorder" in q_lower or "z-score" in q_lower:
                return (
                    "**Article II — Statistical Safety Stock & Reorder Point (ROP) Formula:**\n"
                    "- We compute coupled demand and lead-time uncertainty via:\n"
                    "  `Safety Stock = Z * sqrt(L_weeks * sigma_D^2 + D_weekly^2 * sigma_L_weeks^2)`\n"
                    "  `Reorder Point (ROP) = (Effective_Weekly_Demand * L_weeks) + Safety_Stock`\n"
                    "- Service-level Z-factors: **99% -> Z=2.33** (`CLASS_A_CRITICAL`), **97% -> Z=1.88** (`CLASS_B_CORE`), "
                    "**95% -> Z=1.65** (`CLASS_C_STANDARD`), **92% -> Z=1.41** (`CLASS_D_CONSUMABLE`)."
                )
            if "hitl" in q_lower or "human" in q_lower or "override" in q_lower or "expedite" in q_lower or "budget" in q_lower:
                return (
                    "**Article IV & V — Working Capital, Expedite Capex & Mandatory HITL Code Stop:**\n"
                    "- Autonomous PO release is **strictly blocked (`HOLD_FOR_EXECUTIVE_SOP_APPROVAL`)** whenever:\n"
                    "  1. Total PO commitment exceeds the SKU's `working_capital_budget_usd`.\n"
                    "  2. Expedited air-freight cost exceeds **$25,000 USD**.\n"
                    "  3. Composite risk score is **>= 75** (`CRITICAL`) or a `CLASS_A_CRITICAL` SKU faces a single-source geopolitical disruption.\n"
                    "- An S&OP Executive can resolve the hold via the **Human Override** control panel (`POST /api/plans/{plan_id}/human-override`)."
                )
            if "tier" in q_lower or "abc" in q_lower or "xyz" in q_lower or "class" in q_lower:
                return (
                    "**Article I — ABC/XYZ SKU Stratification Tiers:**\n"
                    "- **CLASS_A_CRITICAL**: High annual spend (>$3M/yr), revenue-critical BOM blocker, or single-source wafer/fab dependency.\n"
                    "- **CLASS_B_CORE**: Core production components ($1M–$3M/yr) with moderate demand/lead-time variance.\n"
                    "- **CLASS_C_STANDARD**: Standard catalog assemblies ($500k–$1M/yr) with reliable multi-source capacity.\n"
                    "- **CLASS_D_CONSUMABLE**: Low-cost indirect packaging/consumables (<$500k/yr) eligible for automated Kanban/VMI release."
                )
            return (
                "**Enterprise S&OP Control Tower Guidance:**\n"
                "- Our 5-Agent Sequential Pipeline evaluates SKUs across:\n"
                "  1. **Demand & Inventory Triage Agent** (ATP reconciliation, ABC/XYZ tiering, PII scrubbing)\n"
                "  2. **Forecast & Safety Stock Agent** (Z-score safety stock & ROP calculation)\n"
                "  3. **Supplier Capacity & Lead-Time Risk Agent** (utilization, OTIF >= 88%, dual-source split)\n"
                "  4. **Replenishment & PO Optimizer Agent** (MRP net requirements, MOQ/lot sizing, expedite air vs SLA penalty)\n"
                "  5. **Master Supply Planner & S&OP Governance Agent** (Constitutional compliance & HITL Code Stop)."
            )

        return self.llm_client.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            fallback_fn=_fallback,
            model_tier="fast",
        )
