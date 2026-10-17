from __future__ import annotations

import asyncio
import inspect
import pytest
from pydantic import ValidationError

from app.config import AppSettings
from app.memory_store import PersistentSupplyMemoryStore
from app.models import (
    HumanOverrideRequest,
    ReplenishmentDecisionStatus,
    SKUClassificationTier,
)
from app.observability import (
    clear_recorded_otel_spans,
    get_recent_otel_spans,
    redact_pii_text,
    start_otel_span,
)
from app.orchestrator import SupplyPlanningOrchestrator
from app.sample_skus import PRESET_SKUS
from app.tools import (
    TOOL_FUNCTIONS,
    TOOL_JSON_SCHEMAS,
    execute_registered_tool,
    get_gemini_tool_declarations,
    get_openai_tool_schemas,
    validate_tool_arguments_against_schema,
)


# ==============================================================================
# 1. Explicit Tool Docstrings, JSON Schemas & Native LLM Tool Calling Tests
# ==============================================================================
def test_all_tools_have_explicit_parameter_and_return_docstrings() -> None:
    for tool_name, fn in TOOL_FUNCTIONS.items():
        doc = inspect.getdoc(fn) or ""
        assert "Args:" in doc, f"Tool {tool_name} is missing explicit 'Args:' section"
        assert "Returns:" in doc, f"Tool {tool_name} is missing explicit 'Returns:' section"
        assert "Raises:" in doc, f"Tool {tool_name} is missing explicit 'Raises:' section"
        sig = inspect.signature(fn)
        for param_name in sig.parameters:
            assert param_name in doc, f"Parameter '{param_name}' missing from {tool_name} docstring"


def test_tool_json_schemas_and_openai_gemini_declarations() -> None:
    assert len(TOOL_JSON_SCHEMAS) == 5
    openai_tools = get_openai_tool_schemas()
    gemini_decls = get_gemini_tool_declarations()
    assert len(openai_tools) == 5
    assert len(gemini_decls) == 5

    for tool_def in openai_tools:
        assert tool_def["type"] == "function"
        assert tool_def["function"]["strict"] is True
        assert tool_def["function"]["parameters"]["additionalProperties"] is False

    # Verify strict schema rejection of invalid parameters
    with pytest.raises(ValidationError):
        validate_tool_arguments_against_schema(
            "calculate_statistical_safety_stock",
            {"weekly_demand_mean": -50.0},
        )


def test_execute_registered_tool_roundtrip() -> None:
    out = execute_registered_tool(
        "calculate_statistical_safety_stock",
        {
            "weekly_demand_mean": 500.0,
            "weekly_demand_std_dev": 80.0,
            "firm_customer_orders_4w": 2100,
            "promotional_uplift_pct": 5.0,
            "forecast_mape_pct": 12.0,
            "seasonality_index": 1.05,
            "lead_time_days_mean": 21.0,
            "lead_time_days_std_dev": 3.5,
            "target_service_level": 0.98,
        },
    )
    assert out["tool_name"] == "calculate_statistical_safety_stock"
    assert out["statistical_safety_stock_units"] > 0
    assert out["reorder_point_units"] > out["statistical_safety_stock_units"]


# ==============================================================================
# 2. Non-Blocking Async & Background Task Memory Persistence Tests
# ==============================================================================
def test_async_and_background_memory_operations(tmp_path) -> None:
    db_file = str(tmp_path / "test_async_supply_memory.db")
    orchestrator = SupplyPlanningOrchestrator(db_path=db_file)

    submission = PRESET_SKUS["sku_c_power_supply"]
    result = orchestrator.run_supply_plan(submission, plan_id="PLAN-BG-001", persist_in_background=True)

    # Flush background worker pool
    completed = orchestrator.memory_store.flush_background_tasks()
    assert completed >= 1

    async def _verify_async_memory() -> None:
        fetched = await orchestrator.memory_store.aget_session("PLAN-BG-001")
        assert fetched is not None
        assert fetched.submission.sku_id == "SKU-PSU-3000W-TITAN"

        await orchestrator.memory_store.aappend_conversation_turn(
            "sess-101", "user", "How is safety stock calculated?"
        )
        await orchestrator.memory_store.aappend_conversation_turn(
            "sess-101", "assistant", "Using Z-score and coupled variance."
        )
        history = await orchestrator.memory_store.aget_conversation_history("sess-101")
        assert len(history) == 2

    asyncio.run(_verify_async_memory())
    telemetry = orchestrator.memory_store.get_memory_telemetry()
    assert telemetry["background_writes_completed"] >= 1
    assert telemetry["async_reads"] >= 1


# ==============================================================================
# 3. Structured Logging (`structlog`) & OpenTelemetry Distributed Tracing Tests
# ==============================================================================
def test_opentelemetry_spans_and_pii_redaction(tmp_path) -> None:
    clear_recorded_otel_spans()
    raw_text = "Contact planner Maya Lin at maya.lin@corp.example.com or +1-408-555-0192; SSN 123-45-6789."
    redacted = redact_pii_text(raw_text)
    assert "[REDACTED_EMAIL]" in redacted
    assert "[REDACTED_PHONE]" in redacted
    assert "[REDACTED_SSN]" in redacted
    assert "maya.lin@corp.example.com" not in redacted

    with start_otel_span("test.custom_span", {"planner.contact": raw_text}):
        pass

    spans = get_recent_otel_spans(limit=10)
    matching = [s for s in spans if s["name"] == "test.custom_span"]
    assert len(matching) == 1
    assert "[REDACTED_EMAIL]" in matching[0]["attributes"]["planner.contact"]
    assert len(matching[0]["trace_id"]) == 32
    assert len(matching[0]["span_id"]) == 16


# ==============================================================================
# 4. End-to-End Parametrized 5-Agent Pipeline & HITL Governance Tests
# ==============================================================================
@pytest.mark.parametrize(
    "preset_key,expected_tier,expected_status,expected_hitl",
    [
        (
            "sku_a_critical_asic",
            SKUClassificationTier.CLASS_A_CRITICAL,
            ReplenishmentDecisionStatus.HOLD_FOR_EXECUTIVE_SOP_APPROVAL,
            True,
        ),
        (
            "sku_b_industrial_sensor",
            SKUClassificationTier.CLASS_B_CORE,
            ReplenishmentDecisionStatus.RELEASE_WITH_DUAL_SOURCE_AND_EXPEDITE,
            False,
        ),
        (
            "sku_c_power_supply",
            SKUClassificationTier.CLASS_C_STANDARD,
            ReplenishmentDecisionStatus.AUTO_RELEASE_PO,
            False,
        ),
        (
            "sku_d_packaging_tray",
            SKUClassificationTier.CLASS_D_CONSUMABLE,
            ReplenishmentDecisionStatus.AUTO_RELEASE_PO,
            False,
        ),
    ],
)
def test_preset_sku_pipeline_decisions(
    tmp_path,
    preset_key: str,
    expected_tier: SKUClassificationTier,
    expected_status: ReplenishmentDecisionStatus,
    expected_hitl: bool,
) -> None:
    db_file = str(tmp_path / f"supply_{preset_key}.db")
    orchestrator = SupplyPlanningOrchestrator(db_path=db_file)
    submission = PRESET_SKUS[preset_key]

    result = orchestrator.run_supply_plan(submission, persist_in_background=False)
    assert result.triage_output is not None
    assert result.final_decision is not None
    assert result.triage_output.sku_tier == expected_tier
    assert result.final_decision.decision_status == expected_status
    assert result.final_decision.requires_human_review is expected_hitl
    assert len(result.phase_assessments) == 3


def test_hitl_executive_override_unblocks_po_release(tmp_path) -> None:
    db_file = str(tmp_path / "hitl_override.db")
    orchestrator = SupplyPlanningOrchestrator(db_path=db_file)
    asic_result = orchestrator.run_supply_plan(
        PRESET_SKUS["sku_a_critical_asic"],
        plan_id="PLAN-HITL-ASIC",
        persist_in_background=False,
    )
    assert asic_result.final_decision is not None
    assert asic_result.final_decision.requires_human_review is True

    override_req = HumanOverrideRequest(
        reviewer_name="SVP Global Operations",
        override_decision=ReplenishmentDecisionStatus.RELEASE_WITH_DUAL_SOURCE_AND_EXPEDITE,
        override_justification="Authorized emergency air freight & capex expansion for CloudTitan SLA.",
    )
    updated = asyncio.run(orchestrator.aapply_human_override("PLAN-HITL-ASIC", override_req))
    assert updated is not None
    assert updated.final_decision is not None
    assert updated.final_decision.requires_human_review is False
    assert updated.final_decision.human_override_applied is True
    assert (
        updated.final_decision.decision_status
        == ReplenishmentDecisionStatus.RELEASE_WITH_DUAL_SOURCE_AND_EXPEDITE
    )


def test_secret_str_api_key_masking() -> None:
    cfg = AppSettings(gemini_api_key="AIzaSySuperSecretSupplyKey999")  # type: ignore[arg-type]
    repr_str = repr(cfg)
    assert "AIzaSySuperSecretSupplyKey999" not in repr_str
    assert cfg.get_gemini_api_key() == "AIzaSySuperSecretSupplyKey999"
