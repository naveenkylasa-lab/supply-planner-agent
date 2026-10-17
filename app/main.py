from __future__ import annotations

import json
import os
from typing import Any, Dict

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.models import (
    ConversationalSupportRequest,
    ConversationalSupportResponse,
    HumanOverrideRequest,
    IntentType,
    SupplyPlanSubmission,
)
from app.observability import (
    get_logger,
    get_recent_otel_spans,
    start_otel_span,
)
from app.orchestrator import SupplyPlanningOrchestrator
from app.sample_skus import PRESET_SKUS
from app.tools import (
    TOOL_JSON_SCHEMAS,
    get_gemini_tool_declarations,
    get_openai_tool_schemas,
)


logger = get_logger("supply_planner.api")

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Enterprise Multi-Agent Supply Chain Control Tower & MRP Replenishment Engine "
        "with Schema-Constrained Native Tool Calling, Async/Background SQLite Memory, "
        "and OpenTelemetry + structlog Distributed Observability."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

orchestrator = SupplyPlanningOrchestrator()

static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def serve_dashboard() -> FileResponse:
    index_path = os.path.join(static_dir, "index.html")
    return FileResponse(index_path)


@app.get("/api/health")
async def health_check() -> Dict[str, Any]:
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "llm_provider": orchestrator.llm_client.active_provider,
        "security_posture": settings.security_posture_summary(),
        "memory_telemetry": orchestrator.memory_store.get_memory_telemetry(),
    }


@app.get("/api/presets")
async def list_preset_skus() -> Dict[str, Any]:
    return {
        key: sku.model_dump(mode="json")
        for key, sku in PRESET_SKUS.items()
    }


@app.get("/api/tools/schemas")
async def get_tool_schemas() -> Dict[str, Any]:
    """
    Exposes the explicit JSON Schemas and OpenAI/Gemini native function-calling declarations
    for all 5 supply chain planning tools.
    """
    return {
        "tool_count": len(TOOL_JSON_SCHEMAS),
        "tools": TOOL_JSON_SCHEMAS,
        "openai_function_calling_schemas": get_openai_tool_schemas(),
        "gemini_function_declarations": get_gemini_tool_declarations(),
    }


@app.get("/api/telemetry/spans")
async def get_telemetry_spans(limit: int = 50) -> Dict[str, Any]:
    spans = get_recent_otel_spans(limit=limit)
    return {
        "span_count": len(spans),
        "spans": spans,
        "memory_telemetry": orchestrator.memory_store.get_memory_telemetry(),
    }


@app.get("/api/plans")
async def list_saved_plans() -> Dict[str, Any]:
    sessions = await orchestrator.memory_store.alist_all_sessions()
    return {
        "count": len(sessions),
        "plans": [s.model_dump(mode="json") for s in sessions],
    }


@app.get("/api/plans/{plan_id}")
async def get_saved_plan(plan_id: str) -> Dict[str, Any]:
    session = await orchestrator.memory_store.aget_session(plan_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Supply plan '{plan_id}' not found.")
    return session.model_dump(mode="json")


@app.post("/api/planning/run")
async def run_supply_plan_endpoint(
    submission: SupplyPlanSubmission,
    background_tasks: BackgroundTasks,
) -> Dict[str, Any]:
    with start_otel_span(
        "http.post.api_planning_run",
        {"sku.id": submission.sku_id, "sku.name": submission.sku_name},
    ):
        result = await orchestrator.arun_supply_plan(
            submission=submission,
            schedule_background_fn=background_tasks.add_task,
        )
        return result.model_dump(mode="json")


@app.post("/api/planning/stream")
async def stream_supply_plan_endpoint(submission: SupplyPlanSubmission) -> StreamingResponse:
    def event_stream():
        for payload in orchestrator.stream_supply_plan(submission):
            yield f"data: {json.dumps(payload)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/plans/{plan_id}/human-override")
async def human_override_endpoint(
    plan_id: str,
    override_request: HumanOverrideRequest,
) -> Dict[str, Any]:
    updated = await orchestrator.aapply_human_override(plan_id, override_request)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Supply plan '{plan_id}' not found.")
    return updated.model_dump(mode="json")


@app.post("/api/chat")
async def conversational_sop_endpoint(
    request: ConversationalSupportRequest,
    background_tasks: BackgroundTasks,
) -> Dict[str, Any]:
    with start_otel_span(
        "http.post.api_chat",
        {"session.id": request.session_id, "has_supply_packet": request.supply_packet is not None},
    ):
        intent_schema = orchestrator.support_agent.classify_intent(
            request.message,
            has_supply_packet=request.supply_packet is not None,
        )

        if (
            intent_schema.intent == IntentType.SUPPLY_PACKET_SUBMISSION
            and request.supply_packet is not None
        ):
            plan_result = await orchestrator.arun_supply_plan(
                submission=request.supply_packet,
                schedule_background_fn=background_tasks.add_task,
            )
            resp = ConversationalSupportResponse(
                session_id=request.session_id,
                intent_detected=IntentType.SUPPLY_PACKET_SUBMISSION,
                agent_name="Master Supply Planner & S&OP Governance Agent",
                model_used=orchestrator.llm_client.get_model_for_tier("deep"),
                reply=(
                    f"Executed 5-agent S&OP pipeline for {request.supply_packet.sku_id}: "
                    f"Decision={plan_result.final_decision.decision_status.value if plan_result.final_decision else 'DONE'}."
                ),
                routed_to_pipeline=True,
                pipeline_result=plan_result,
            )
            return resp.model_dump(mode="json")

        history = await orchestrator.memory_store.aget_conversation_history(request.session_id)
        answer = orchestrator.support_agent.answer_question(request.message, history)

        # Schedule non-blocking background persistence of conversation turns
        background_tasks.add_task(
            orchestrator.memory_store.aappend_conversation_turn,
            request.session_id,
            "user",
            request.message,
        )
        background_tasks.add_task(
            orchestrator.memory_store.aappend_conversation_turn,
            request.session_id,
            "assistant",
            answer,
        )

        resp = ConversationalSupportResponse(
            session_id=request.session_id,
            intent_detected=IntentType.PLANNER_QUESTION,
            agent_name="Conversational S&OP Support Agent",
            model_used=orchestrator.llm_client.get_model_for_tier("fast"),
            reply=answer,
            routed_to_pipeline=False,
        )
        return resp.model_dump(mode="json")
