from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Any, Callable, Dict, Generator, List, Optional, TypedDict
import uuid

from app.agents.forecast_agent import ForecastSafetyStockAgent
from app.agents.master_planner_agent import MasterSupplyPlannerAgent
from app.agents.replenishment_agent import ReplenishmentOptimizerAgent
from app.agents.supplier_risk_agent import SupplierCapacityRiskAgent
from app.agents.support_agent import ConversationalSOPSupportAgent
from app.agents.triage_agent import DemandInventoryTriageAgent
from app.config import settings
from app.llm_client import HybridLLMClient
from app.memory_store import PersistentSupplyMemoryStore
from app.models import (
    FinalSupplyPlanDecision,
    HumanOverrideRequest,
    IntentType,
    PhaseAssessment,
    SupplyPlanRunResult,
    SupplyPlanSubmission,
    TelemetryEvent,
    TriagePhaseOutput,
)
from app.observability import (
    current_span_id_hex,
    current_trace_id_hex,
    get_logger,
    start_otel_span,
)

try:
    from langgraph.graph import END, StateGraph

    LANGGRAPH_AVAILABLE = True
except ImportError:  # pragma: no cover
    END = "__end__"
    StateGraph = None  # type: ignore
    LANGGRAPH_AVAILABLE = False


logger = get_logger("supply_planner.orchestrator")


class SupplyPipelineGraphState(TypedDict, total=False):
    plan_id: str
    submission: SupplyPlanSubmission
    triage_output: Optional[TriagePhaseOutput]
    forecast_assessment: Optional[PhaseAssessment]
    supplier_assessment: Optional[PhaseAssessment]
    replenishment_assessment: Optional[PhaseAssessment]
    final_decision: Optional[FinalSupplyPlanDecision]
    telemetry_events: List[TelemetryEvent]


class SupplyPlanningOrchestrator:
    """
    Enterprise Multi-Agent Supply Chain Planning Orchestrator.

    Coordinates:
    - Coordinator & Conversational S&OP Support Agent (Intent Router)
    - Phase 1: Demand & Inventory Triage Agent (`fast` tier)
    - Phase 2: Forecast & Safety Stock Agent (`deep` tier)
    - Phase 3: Supplier Capacity & Lead-Time Risk Agent (`deep` tier)
    - Phase 4: Replenishment & PO Optimizer Agent (`deep` tier)
    - Phase 5: Master Supply Planner & S&OP Governance Agent (`deep` tier)
    - Phase 5B: Constitutional Human-in-the-Loop (HITL) Code Stop Gate
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.llm_client = HybridLLMClient()
        self.memory_store = PersistentSupplyMemoryStore(
            db_path=db_path or settings.sqlite_db_path
        )
        self.support_agent = ConversationalSOPSupportAgent(self.llm_client)
        self.triage_agent = DemandInventoryTriageAgent(self.llm_client)
        self.forecast_agent = ForecastSafetyStockAgent(self.llm_client)
        self.supplier_agent = SupplierCapacityRiskAgent(self.llm_client)
        self.replenishment_agent = ReplenishmentOptimizerAgent(self.llm_client)
        self.master_planner_agent = MasterSupplyPlannerAgent(self.llm_client)
        self._compiled_graph = self._build_langgraph() if LANGGRAPH_AVAILABLE else None

    def _record_telemetry(
        self,
        events: List[TelemetryEvent],
        phase: str,
        agent: str,
        status: str,
        start_perf: float,
        details: str,
    ) -> TelemetryEvent:
        latency_ms = round((time.perf_counter() - start_perf) * 1000.0, 2)
        evt = TelemetryEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            phase=phase,
            agent=agent,
            status=status,
            latency_ms=latency_ms,
            details=details,
            trace_id=current_trace_id_hex(),
            span_id=current_span_id_hex(),
        )
        events.append(evt)
        logger.info(
            "pipeline_phase_completed",
            phase=phase,
            agent=agent,
            status=status,
            latency_ms=latency_ms,
            details=details,
        )
        return evt

    def _build_langgraph(self) -> Any:
        workflow = StateGraph(SupplyPipelineGraphState)

        def node_phase1_triage(state: SupplyPipelineGraphState) -> Dict[str, Any]:
            t0 = time.perf_counter()
            submission = state["submission"]
            events = list(state.get("telemetry_events", []))
            with start_otel_span(
                "pipeline.node.phase1_triage",
                {"plan.id": state["plan_id"], "sku.id": submission.sku_id},
            ):
                triage_out = self.triage_agent.run(submission)
                self._record_telemetry(
                    events,
                    phase="Phase 1: Demand & Inventory Triage",
                    agent=self.triage_agent.AGENT_NAME,
                    status="COMPLETED",
                    start_perf=t0,
                    details=(
                        f"Classified {submission.sku_id} as {triage_out.sku_tier.value} "
                        f"({triage_out.abc_xyz_class}); Net ATP={triage_out.net_available_on_hand_units:,} units."
                    ),
                )
                return {"triage_output": triage_out, "telemetry_events": events}

        def node_phase2_forecast(state: SupplyPipelineGraphState) -> Dict[str, Any]:
            t0 = time.perf_counter()
            submission = state["submission"]
            triage_out = state["triage_output"]
            assert triage_out is not None
            events = list(state.get("telemetry_events", []))
            with start_otel_span(
                "pipeline.node.phase2_forecast",
                {"plan.id": state["plan_id"], "sku.id": submission.sku_id},
            ):
                forecast_out = self.forecast_agent.run(submission, triage_out)
                ss = forecast_out.quantitative_metrics.get("statistical_safety_stock_units", 0)
                rop = forecast_out.quantitative_metrics.get("reorder_point_units", 0)
                self._record_telemetry(
                    events,
                    phase="Phase 2: Statistical Safety Stock & ROP",
                    agent=self.forecast_agent.AGENT_NAME,
                    status="COMPLETED",
                    start_perf=t0,
                    details=f"Safety Stock={ss:,} units, ROP={rop:,} units (Risk={forecast_out.risk_score}/100).",
                )
                return {"forecast_assessment": forecast_out, "telemetry_events": events}

        def node_phase3_supplier_risk(state: SupplyPipelineGraphState) -> Dict[str, Any]:
            t0 = time.perf_counter()
            submission = state["submission"]
            triage_out = state["triage_output"]
            forecast_out = state["forecast_assessment"]
            assert triage_out is not None and forecast_out is not None
            events = list(state.get("telemetry_events", []))
            with start_otel_span(
                "pipeline.node.phase3_supplier_risk",
                {"plan.id": state["plan_id"], "sku.id": submission.sku_id},
            ):
                supplier_out = self.supplier_agent.run(submission, triage_out, forecast_out)
                util = supplier_out.quantitative_metrics.get("capacity_utilization_pct", 0.0)
                self._record_telemetry(
                    events,
                    phase="Phase 3: Supplier Capacity & Lead-Time Risk",
                    agent=self.supplier_agent.AGENT_NAME,
                    status="COMPLETED",
                    start_perf=t0,
                    details=(
                        f"Primary capacity utilization={util:.1f}%, "
                        f"Supplier Risk={supplier_out.risk_score}/100 ({supplier_out.risk_level.value})."
                    ),
                )
                return {"supplier_assessment": supplier_out, "telemetry_events": events}

        def node_phase4_replenishment(state: SupplyPipelineGraphState) -> Dict[str, Any]:
            t0 = time.perf_counter()
            submission = state["submission"]
            triage_out = state["triage_output"]
            forecast_out = state["forecast_assessment"]
            supplier_out = state["supplier_assessment"]
            assert triage_out is not None and forecast_out is not None and supplier_out is not None
            events = list(state.get("telemetry_events", []))
            with start_otel_span(
                "pipeline.node.phase4_replenishment",
                {"plan.id": state["plan_id"], "sku.id": submission.sku_id},
            ):
                rep_out = self.replenishment_agent.run(
                    submission, triage_out, forecast_out, supplier_out
                )
                order_qty = rep_out.quantitative_metrics.get("recommended_total_order_units", 0)
                spend = rep_out.quantitative_metrics.get("total_po_spend_usd", 0.0)
                self._record_telemetry(
                    events,
                    phase="Phase 4: MRP Replenishment & PO Optimization",
                    agent=self.replenishment_agent.AGENT_NAME,
                    status="COMPLETED",
                    start_perf=t0,
                    details=f"Recommended PO={order_qty:,} units, Total Spend=${spend:,.2f}.",
                )
                return {"replenishment_assessment": rep_out, "telemetry_events": events}

        def node_phase5_master_planner(state: SupplyPipelineGraphState) -> Dict[str, Any]:
            t0 = time.perf_counter()
            submission = state["submission"]
            triage_out = state["triage_output"]
            forecast_out = state["forecast_assessment"]
            supplier_out = state["supplier_assessment"]
            rep_out = state["replenishment_assessment"]
            assert (
                triage_out is not None
                and forecast_out is not None
                and supplier_out is not None
                and rep_out is not None
            )
            events = list(state.get("telemetry_events", []))
            with start_otel_span(
                "pipeline.node.phase5_master_planner",
                {"plan.id": state["plan_id"], "sku.id": submission.sku_id},
            ):
                decision = self.master_planner_agent.run(
                    submission, triage_out, forecast_out, supplier_out, rep_out
                )
                self._record_telemetry(
                    events,
                    phase="Phase 5: Master S&OP Governance & Decision",
                    agent=self.master_planner_agent.AGENT_NAME,
                    status=decision.decision_status.value,
                    start_perf=t0,
                    details=(
                        f"Composite Risk={decision.composite_risk_score}/100, "
                        f"Decision={decision.decision_status.value}, HITL={decision.requires_human_review}."
                    ),
                )
                return {"final_decision": decision, "telemetry_events": events}

        def node_human_review_gate(state: SupplyPipelineGraphState) -> Dict[str, Any]:
            t0 = time.perf_counter()
            decision = state["final_decision"]
            assert decision is not None
            events = list(state.get("telemetry_events", []))
            with start_otel_span(
                "pipeline.node.human_review_gate",
                {
                    "plan.id": state["plan_id"],
                    "hitl.triggered": True,
                    "hitl.reason": decision.human_review_reason or "Constitutional threshold",
                },
            ):
                self._record_telemetry(
                    events,
                    phase="Phase 5B: Constitutional HITL Code Stop",
                    agent="Executive S&OP Governance Gate",
                    status="HOLD_FOR_EXECUTIVE_SOP_APPROVAL",
                    start_perf=t0,
                    details=f"Autonomous ERP PO release blocked: {decision.human_review_reason}",
                )
                return {"telemetry_events": events}

        def route_after_master_planner(state: SupplyPipelineGraphState) -> str:
            decision = state.get("final_decision")
            if decision and decision.requires_human_review:
                return "human_review_gate"
            return END

        workflow.add_node("phase1_triage", node_phase1_triage)
        workflow.add_node("phase2_forecast", node_phase2_forecast)
        workflow.add_node("phase3_supplier_risk", node_phase3_supplier_risk)
        workflow.add_node("phase4_replenishment", node_phase4_replenishment)
        workflow.add_node("phase5_master_planner", node_phase5_master_planner)
        workflow.add_node("human_review_gate", node_human_review_gate)

        workflow.set_entry_point("phase1_triage")
        workflow.add_edge("phase1_triage", "phase2_forecast")
        workflow.add_edge("phase2_forecast", "phase3_supplier_risk")
        workflow.add_edge("phase3_supplier_risk", "phase4_replenishment")
        workflow.add_edge("phase4_replenishment", "phase5_master_planner")
        workflow.add_conditional_edges(
            "phase5_master_planner",
            route_after_master_planner,
            {
                "human_review_gate": "human_review_gate",
                END: END,
            },
        )
        workflow.add_edge("human_review_gate", END)
        return workflow.compile()

    def run_supply_plan(
        self,
        submission: SupplyPlanSubmission,
        plan_id: Optional[str] = None,
        persist_in_background: bool = True,
    ) -> SupplyPlanRunResult:
        """
        Executes the full 5-phase Sequential Multi-Agent Supply Planning Pipeline inside an
        OpenTelemetry distributed trace and offloads session persistence to the background pool.
        """
        assigned_id = plan_id or f"PLAN-{uuid.uuid4().hex[:8].upper()}"
        started_at = datetime.now(timezone.utc).isoformat()
        pipeline_t0 = time.perf_counter()

        with start_otel_span(
            "pipeline.execute_supply_plan",
            {
                "plan.id": assigned_id,
                "sku.id": submission.sku_id,
                "sku.name": submission.sku_name,
                "sku.plant_code": submission.plant_code,
                "orchestrator.engine": "langgraph" if self._compiled_graph else "sequential_fallback",
            },
        ) as root_span:
            initial_state: SupplyPipelineGraphState = {
                "plan_id": assigned_id,
                "submission": submission,
                "telemetry_events": [],
            }

            if self._compiled_graph is not None:
                final_state = self._compiled_graph.invoke(initial_state)
                triage_out = final_state["triage_output"]
                forecast_out = final_state["forecast_assessment"]
                supplier_out = final_state["supplier_assessment"]
                rep_out = final_state["replenishment_assessment"]
                decision = final_state["final_decision"]
                events = final_state["telemetry_events"]
            else:
                events = []
                t0 = time.perf_counter()
                triage_out = self.triage_agent.run(submission)
                self._record_telemetry(
                    events,
                    "Phase 1: Demand & Inventory Triage",
                    self.triage_agent.AGENT_NAME,
                    "COMPLETED",
                    t0,
                    f"Classified {submission.sku_id} as {triage_out.sku_tier.value}",
                )
                t0 = time.perf_counter()
                forecast_out = self.forecast_agent.run(submission, triage_out)
                self._record_telemetry(
                    events,
                    "Phase 2: Statistical Safety Stock & ROP",
                    self.forecast_agent.AGENT_NAME,
                    "COMPLETED",
                    t0,
                    "Safety stock & ROP computed",
                )
                t0 = time.perf_counter()
                supplier_out = self.supplier_agent.run(submission, triage_out, forecast_out)
                self._record_telemetry(
                    events,
                    "Phase 3: Supplier Capacity & Lead-Time Risk",
                    self.supplier_agent.AGENT_NAME,
                    "COMPLETED",
                    t0,
                    "Supplier capacity evaluated",
                )
                t0 = time.perf_counter()
                rep_out = self.replenishment_agent.run(
                    submission, triage_out, forecast_out, supplier_out
                )
                self._record_telemetry(
                    events,
                    "Phase 4: MRP Replenishment & PO Optimization",
                    self.replenishment_agent.AGENT_NAME,
                    "COMPLETED",
                    t0,
                    "MRP replenishment optimized",
                )
                t0 = time.perf_counter()
                decision = self.master_planner_agent.run(
                    submission, triage_out, forecast_out, supplier_out, rep_out
                )
                self._record_telemetry(
                    events,
                    "Phase 5: Master S&OP Governance & Decision",
                    self.master_planner_agent.AGENT_NAME,
                    decision.decision_status.value,
                    t0,
                    f"Decision={decision.decision_status.value}",
                )

            completed_at = datetime.now(timezone.utc).isoformat()
            total_ms = round((time.perf_counter() - pipeline_t0) * 1000.0, 2)
            trace_hex = current_trace_id_hex()

            root_span.set_attribute("pipeline.total_latency_ms", total_ms)
            root_span.set_attribute("pipeline.decision_status", decision.decision_status.value)

            run_result = SupplyPlanRunResult(
                plan_id=assigned_id,
                trace_id=trace_hex,
                started_at=started_at,
                completed_at=completed_at,
                intent_detected=IntentType.SUPPLY_PACKET_SUBMISSION,
                submission=submission,
                triage_output=triage_out,
                phase_assessments=[forecast_out, supplier_out, rep_out],
                final_decision=decision,
                telemetry_events=events,
            )

            self.memory_store.upsert_session(run_result, background=persist_in_background)
            return run_result

    async def arun_supply_plan(
        self,
        submission: SupplyPlanSubmission,
        plan_id: Optional[str] = None,
        schedule_background_fn: Optional[Callable[..., Any]] = None,
    ) -> SupplyPlanRunResult:
        """
        Async wrapper for FastAPI endpoints that schedules SQLite persistence via FastAPI
        `BackgroundTasks` or `PersistentSupplyMemoryStore` async coroutines.
        """
        result = self.run_supply_plan(submission, plan_id=plan_id, persist_in_background=True)
        if schedule_background_fn is not None:
            schedule_background_fn(self.memory_store.aupsert_session, result)
        return result

    def stream_supply_plan(
        self,
        submission: SupplyPlanSubmission,
        plan_id: Optional[str] = None,
    ) -> Generator[Dict[str, Any], None, None]:
        """
        Streams real-time SSE phase updates as each of the 5 supply planning agents executes.
        """
        assigned_id = plan_id or f"PLAN-{uuid.uuid4().hex[:8].upper()}"
        started_at = datetime.now(timezone.utc).isoformat()
        events: List[TelemetryEvent] = []

        with start_otel_span(
            "pipeline.stream_supply_plan",
            {"plan.id": assigned_id, "sku.id": submission.sku_id},
        ):
            t0 = time.perf_counter()
            triage_out = self.triage_agent.run(submission)
            evt1 = self._record_telemetry(
                events,
                "Phase 1: Demand & Inventory Triage",
                self.triage_agent.AGENT_NAME,
                "COMPLETED",
                t0,
                f"Classified {submission.sku_id} as {triage_out.sku_tier.value} ({triage_out.abc_xyz_class}).",
            )
            yield {
                "event": "phase_complete",
                "phase_index": 1,
                "phase": evt1.phase,
                "agent": evt1.agent,
                "triage_output": triage_out.model_dump(mode="json"),
                "telemetry": evt1.model_dump(mode="json"),
            }

            t0 = time.perf_counter()
            forecast_out = self.forecast_agent.run(submission, triage_out)
            evt2 = self._record_telemetry(
                events,
                "Phase 2: Statistical Safety Stock & ROP",
                self.forecast_agent.AGENT_NAME,
                "COMPLETED",
                t0,
                f"Safety Stock={forecast_out.quantitative_metrics.get('statistical_safety_stock_units', 0):,} units.",
            )
            yield {
                "event": "phase_complete",
                "phase_index": 2,
                "phase": evt2.phase,
                "agent": evt2.agent,
                "assessment": forecast_out.model_dump(mode="json"),
                "telemetry": evt2.model_dump(mode="json"),
            }

            t0 = time.perf_counter()
            supplier_out = self.supplier_agent.run(submission, triage_out, forecast_out)
            evt3 = self._record_telemetry(
                events,
                "Phase 3: Supplier Capacity & Lead-Time Risk",
                self.supplier_agent.AGENT_NAME,
                "COMPLETED",
                t0,
                f"Supplier Risk={supplier_out.risk_score}/100 ({supplier_out.risk_level.value}).",
            )
            yield {
                "event": "phase_complete",
                "phase_index": 3,
                "phase": evt3.phase,
                "agent": evt3.agent,
                "assessment": supplier_out.model_dump(mode="json"),
                "telemetry": evt3.model_dump(mode="json"),
            }

            t0 = time.perf_counter()
            rep_out = self.replenishment_agent.run(
                submission, triage_out, forecast_out, supplier_out
            )
            evt4 = self._record_telemetry(
                events,
                "Phase 4: MRP Replenishment & PO Optimization",
                self.replenishment_agent.AGENT_NAME,
                "COMPLETED",
                t0,
                f"Recommended PO={rep_out.quantitative_metrics.get('recommended_total_order_units', 0):,} units.",
            )
            yield {
                "event": "phase_complete",
                "phase_index": 4,
                "phase": evt4.phase,
                "agent": evt4.agent,
                "assessment": rep_out.model_dump(mode="json"),
                "telemetry": evt4.model_dump(mode="json"),
            }

            t0 = time.perf_counter()
            decision = self.master_planner_agent.run(
                submission, triage_out, forecast_out, supplier_out, rep_out
            )
            evt5 = self._record_telemetry(
                events,
                "Phase 5: Master S&OP Governance & Decision",
                self.master_planner_agent.AGENT_NAME,
                decision.decision_status.value,
                t0,
                f"Composite Score={decision.composite_risk_score}/100 -> {decision.decision_status.value}",
            )

            completed_at = datetime.now(timezone.utc).isoformat()
            full_result = SupplyPlanRunResult(
                plan_id=assigned_id,
                trace_id=current_trace_id_hex(),
                started_at=started_at,
                completed_at=completed_at,
                intent_detected=IntentType.SUPPLY_PACKET_SUBMISSION,
                submission=submission,
                triage_output=triage_out,
                phase_assessments=[forecast_out, supplier_out, rep_out],
                final_decision=decision,
                telemetry_events=events,
            )
            self.memory_store.schedule_background_upsert_session(full_result)

            yield {
                "event": "pipeline_complete",
                "phase_index": 5,
                "phase": evt5.phase,
                "agent": evt5.agent,
                "result": full_result.model_dump(mode="json"),
            }

    async def aapply_human_override(
        self,
        plan_id: str,
        override_req: HumanOverrideRequest,
    ) -> Optional[SupplyPlanRunResult]:
        """
        Applies an S&OP Executive Human-in-the-Loop override to a paused supply plan and persists
        the updated governance record asynchronously.
        """
        session = await self.memory_store.aget_session(plan_id)
        if session is None or session.final_decision is None:
            return None

        with start_otel_span(
            "pipeline.human_override",
            {
                "plan.id": plan_id,
                "override.reviewer": override_req.reviewer_name,
                "override.decision": override_req.override_decision.value,
            },
        ):
            t0 = time.perf_counter()
            session.final_decision.decision_status = override_req.override_decision
            session.final_decision.requires_human_review = False
            session.final_decision.human_override_applied = True
            session.final_decision.human_override_by = override_req.reviewer_name
            session.final_decision.human_override_notes = override_req.override_justification

            self._record_telemetry(
                session.telemetry_events,
                phase="Phase 5C: Executive S&OP Human Override",
                agent=f"Executive Reviewer ({override_req.reviewer_name})",
                status=override_req.override_decision.value,
                start_perf=t0,
                details=f"Override applied: {override_req.override_justification}",
            )
            await self.memory_store.aupsert_session(session)
            return session
