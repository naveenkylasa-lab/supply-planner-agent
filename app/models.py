"""Pydantic data models & explicit JSON Schemas for the Supply Planner & S&OP multi-agent workflow."""

from __future__ import annotations

import copy
from enum import Enum
from typing import Any, Dict, List, Optional

try:
    from pydantic import BaseModel, Field

    PYDANTIC_V2_AVAILABLE = True
except ImportError:
    PYDANTIC_V2_AVAILABLE = False

    class _FieldDefault:
        def __init__(self, default: Any = None, default_factory: Any = None, **kwargs: Any) -> None:
            self.default = default
            self.default_factory = default_factory
            self.metadata = kwargs

    def Field(default: Any = None, *, default_factory: Any = None, **kwargs: Any) -> Any:  # type: ignore
        return _FieldDefault(default=default, default_factory=default_factory, **kwargs)

    class BaseModel:  # type: ignore
        def __init__(self, **kwargs: Any) -> None:
            for cls in reversed(self.__class__.__mro__):
                if cls is object:
                    continue
                for k, v in cls.__dict__.items():
                    if k.startswith("_") or callable(v):
                        continue
                    if isinstance(v, _FieldDefault):
                        setattr(self, k, v.default_factory() if v.default_factory else copy.deepcopy(v.default))
                    else:
                        setattr(self, k, copy.deepcopy(v))
            for k, v in kwargs.items():
                setattr(self, k, v)

        def model_copy(self, *, deep: bool = False) -> Any:
            return copy.deepcopy(self) if deep else copy.copy(self)

        def model_dump(self) -> Dict[str, Any]:
            def _conv(val: Any) -> Any:
                if isinstance(val, Enum):
                    return val.value
                if hasattr(val, "model_dump"):
                    return val.model_dump()
                if isinstance(val, list):
                    return [_conv(x) for x in val]
                if isinstance(val, dict):
                    return {dk: _conv(dv) for dk, dv in val.items()}
                return val

            return {k: _conv(v) for k, v in self.__dict__.items() if not k.startswith("_")}

        @classmethod
        def model_json_schema(cls) -> Dict[str, Any]:
            props: Dict[str, Any] = {}
            req: List[str] = []
            for k, v in cls.__dict__.items():
                if k.startswith("_") or callable(v):
                    continue
                desc = v.metadata.get("description", "") if isinstance(v, _FieldDefault) else ""
                props[k] = {"type": "string", "description": desc}
                if isinstance(v, _FieldDefault) and v.default is Ellipsis:
                    req.append(k)
            return {"title": cls.__name__, "type": "object", "properties": props, "required": req}


class CriticalityClass(str, Enum):
    CLASS_A_CRITICAL = "CLASS_A_CRITICAL"
    CLASS_B_ESSENTIAL = "CLASS_B_ESSENTIAL"
    CLASS_C_STANDARD = "CLASS_C_STANDARD"
    CLASS_D_CONSUMABLE = "CLASS_D_CONSUMABLE"


class DemandVolatility(str, Enum):
    XYZ_X_STABLE = "XYZ_X_STABLE"
    XYZ_Y_SEASONAL = "XYZ_Y_SEASONAL"
    XYZ_Z_ERRATIC = "XYZ_Z_ERRATIC"


class PlanDecision(str, Enum):
    RELEASE_STANDARD_PO = "RELEASE_STANDARD_PO"
    RELEASE_WITH_EXPEDITE = "RELEASE_WITH_EXPEDITE"
    ESCALATED_S_AND_OP_REVIEW = "ESCALATED_S_AND_OP_REVIEW"
    HOLD_DISRUPTION_BLOCK = "HOLD_DISRUPTION_BLOCK"


class RiskSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class PhaseStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class InventoryStateInput(BaseModel):
    on_hand_units: int = Field(default=1200, ge=0, description="Unrestricted physical inventory on hand.")
    allocated_units: int = Field(default=300, ge=0, description="Inventory already committed to customer orders.")
    in_transit_units: int = Field(default=400, ge=0, description="Open purchase order units currently in transit.")
    quality_hold_units: int = Field(default=0, ge=0, description="Quarantined units on quality inspection hold.")
    shelf_life_risk: bool = Field(default=False, description="True if SKU has cold-chain or expiration risk.")


class DemandForecastInput(BaseModel):
    daily_demand_mean: float = Field(default=50.0, ge=0.0, description="Mean daily demand rate in units.")
    daily_demand_std_dev: float = Field(default=12.0, ge=0.0, description="Standard deviation of daily demand.")
    planning_horizon_days: int = Field(default=30, ge=1, description="MRP planning horizon in days.")
    demand_surge_pct: float = Field(default=0.0, ge=-50.0, le=500.0, description="Promo or market demand surge percentage.")
    target_service_level_pct: float = Field(default=98.0, ge=50.0, le=99.99, description="Target cycle service level percentage.")
    backorder_penalty_per_unit_usd: float = Field(default=150.0, ge=0.0, description="Contractual penalty or lost margin per stockout unit.")


class SupplierNetworkInput(BaseModel):
    primary_supplier_name: str = Field(default="Apex Precision Manufacturing", description="Primary tier-1 supplier name.")
    primary_supplier_country: str = Field(default="United States", description="Primary supplier manufacturing country.")
    quoted_lead_time_days: int = Field(default=14, ge=1, description="Contractual supplier lead time in days.")
    lead_time_std_dev_days: float = Field(default=2.0, ge=0.0, description="Historical supplier lead-time standard deviation.")
    on_time_in_full_pct: float = Field(default=96.0, ge=0.0, le=100.0, description="Historical OTIF delivery score percentage.")
    single_sourced: bool = Field(default=False, description="True if no qualified backup supplier exists.")
    backup_supplier_available: bool = Field(default=True, description="True if a pre-qualified secondary supplier is active.")
    max_weekly_capacity_units: int = Field(default=1500, ge=1, description="Supplier maximum weekly production capacity.")
    geopolitical_or_port_disruption: bool = Field(default=False, description="True if active port congestion, strike, or export ban impacts route.")
    trade_compliance_hold: bool = Field(default=False, description="True if supplier or sub-tier is under customs/UFLPA/sanctions hold.")
    disruption_alerts: List[str] = Field(default_factory=list, description="Active supply chain disruption intelligence alerts.")


class ReplenishmentCostInput(BaseModel):
    unit_cost_usd: float = Field(default=120.0, ge=0.01, description="Standard unit purchase cost in USD.")
    minimum_order_qty: int = Field(default=100, ge=1, description="Supplier Minimum Order Quantity (MOQ).")
    order_multiple: int = Field(default=50, ge=1, description="Lot-size rounding multiple.")
    standard_freight_per_unit_usd: float = Field(default=4.5, ge=0.0, description="Standard ocean/ground freight cost per unit.")
    expedite_air_freight_per_unit_usd: float = Field(default=28.0, ge=0.0, description="Expedited air-freight cost per unit.")
    working_capital_budget_usd: float = Field(default=500_000.0, ge=0.0, description="Approved PO working capital budget ceiling.")


class SupplyPlanSubmission(BaseModel):
    sku_id: Optional[str] = Field(default=None, description="Unique SKU identifier (e.g. SKU-2001).")
    sku_name: str = Field(..., description="Descriptive part or product name.")
    category: str = Field(..., description="Product family or commodity category.")
    plant_code: str = Field(default="PLT-US-EAST-01", description="Receiving manufacturing plant or distribution center.")
    planner_contact: str = Field(default="Director of Global Supply Planning", description="Responsible supply planner contact.")
    bom_description: str = Field(..., description="Bill of Materials (BOM) role and downstream assembly impact.")
    annual_spend_usd: float = Field(default=450_000.0, ge=0.0, description="Annualized SKU procurement spend in USD.")
    demand_volatility: DemandVolatility = Field(default=DemandVolatility.XYZ_X_STABLE, description="XYZ demand variability classification.")
    revenue_at_risk_per_day_usd: float = Field(default=25_000.0, ge=0.0, description="Daily production revenue halted if SKU stocks out.")
    submitted_erp_documents: List[str] = Field(default_factory=list, description="Uploaded ERP snapshots, BOM files, and open PO reports.")
    inventory: InventoryStateInput = Field(default_factory=InventoryStateInput)
    demand: DemandForecastInput = Field(default_factory=DemandForecastInput)
    supplier: SupplierNetworkInput = Field(default_factory=SupplierNetworkInput)
    replenishment: ReplenishmentCostInput = Field(default_factory=ReplenishmentCostInput)


# ---------------------------------------------------------------------------
# Explicit Tool Input / Output Pydantic Schemas & LLM Output Constraints
# ---------------------------------------------------------------------------
class ExtractErpInventoryToolArgs(BaseModel):
    """Explicit JSON Schema input parameters for `extract_erp_inventory_and_bom_data`."""

    sku_name: str = Field(..., description="Name of the SKU whose ERP/BOM files are being inspected.")
    submitted_erp_documents: List[str] = Field(
        default_factory=list,
        description="List of ERP inventory snapshots, BOM exports, and open PO schedule filenames.",
    )


class ExtractErpInventoryToolResult(BaseModel):
    """Explicit JSON Schema output structure for `extract_erp_inventory_and_bom_data`."""

    status: str = Field(..., description="'EXTRACTION_SUCCESS' or 'GUIDED_ERROR_RECOVERY_REQUIRED'.")
    extracted_artifacts: List[str] = Field(default_factory=list, description="Verified ERP/BOM artifacts extracted.")
    guided_errors: List[str] = Field(default_factory=list, description="Actionable guided recovery instructions for corrupt/stale/encrypted files.")
    documents_scanned: int = Field(..., ge=0, description="Total number of submitted ERP/BOM documents scanned.")


class ClassifySkuCriticalityToolArgs(BaseModel):
    """Explicit JSON Schema input parameters for `classify_sku_criticality_tier`."""

    demand_volatility: DemandVolatility = Field(..., description="XYZ demand volatility class.")
    annual_spend_usd: float = Field(..., ge=0.0, description="Annual SKU procurement spend in USD.")
    revenue_at_risk_per_day_usd: float = Field(..., ge=0.0, description="Daily revenue at risk upon stockout.")
    net_available_units: int = Field(..., description="Net available inventory (on_hand - allocated + in_transit).")
    daily_demand_mean: float = Field(..., ge=0.0, description="Mean daily demand in units.")
    submitted_erp_documents: List[str] = Field(default_factory=list, description="Uploaded ERP/BOM document names.")


class ClassifySkuCriticalityToolResult(BaseModel):
    """Explicit JSON Schema output structure for `classify_sku_criticality_tier`."""

    criticality_score: float = Field(..., ge=0.0, le=100.0, description="Calculated inherent supply criticality score (0-100).")
    criticality_class: CriticalityClass = Field(..., description="Assigned ABC criticality class.")
    days_of_supply: float = Field(..., ge=0.0, description="Current Days of Supply (DoS) based on net inventory.")
    required_erp_documents: List[str] = Field(default_factory=list, description="Mandatory ERP/BOM artifacts for this class.")
    missing_erp_documents: List[str] = Field(default_factory=list, description="Missing mandatory ERP/BOM documents.")
    auto_release_eligible: bool = Field(..., description="True if SKU qualifies for automated Class D PO release.")


class ForecastDemandSafetyStockToolArgs(BaseModel):
    """Explicit JSON Schema input parameters for `forecast_demand_and_safety_stock`."""

    sku_name: str = Field(..., description="Name of the SKU being forecasted.")
    criticality_class: CriticalityClass = Field(..., description="Assigned ABC criticality class.")
    daily_demand_mean: float = Field(..., ge=0.0, description="Mean daily demand in units.")
    daily_demand_std_dev: float = Field(..., ge=0.0, description="Daily demand standard deviation.")
    planning_horizon_days: int = Field(..., ge=1, description="MRP planning horizon in days.")
    demand_surge_pct: float = Field(..., description="Demand surge percentage adjustment.")
    target_service_level_pct: float = Field(..., ge=50.0, le=99.99, description="Target cycle service level percentage.")
    quoted_lead_time_days: int = Field(..., ge=1, description="Supplier lead time in days.")
    lead_time_std_dev_days: float = Field(..., ge=0.0, description="Supplier lead time standard deviation in days.")
    net_available_units: int = Field(..., description="Net available inventory units before new orders.")


class EvaluateSupplierCapacityToolArgs(BaseModel):
    """Explicit JSON Schema input parameters for `evaluate_supplier_capacity_and_lead_times`."""

    sku_name: str = Field(..., description="Name of the SKU being evaluated.")
    criticality_class: CriticalityClass = Field(..., description="Assigned ABC criticality class.")
    primary_supplier_name: str = Field(..., description="Primary supplier legal name.")
    primary_supplier_country: str = Field(..., description="Primary supplier country of origin.")
    quoted_lead_time_days: int = Field(..., ge=1, description="Quoted supplier lead time in days.")
    on_time_in_full_pct: float = Field(..., ge=0.0, le=100.0, description="Supplier OTIF performance percentage.")
    single_sourced: bool = Field(..., description="Whether the SKU is single-sourced.")
    backup_supplier_available: bool = Field(..., description="Whether an active secondary supplier is qualified.")
    geopolitical_or_port_disruption: bool = Field(..., description="Whether port congestion or geopolitical disruption is active.")
    trade_compliance_hold: bool = Field(..., description="Whether a customs/UFLPA/sanctions trade hold is active.")


class OptimizeReplenishmentOrdersToolArgs(BaseModel):
    """Explicit JSON Schema input parameters for `optimize_replenishment_and_purchase_orders`."""

    sku_name: str = Field(..., description="Name of the SKU being replenished.")
    criticality_class: CriticalityClass = Field(..., description="Assigned ABC criticality class.")
    net_requirement_units: int = Field(..., ge=0, description="Net requirement units needed over the planning horizon.")
    days_of_supply: float = Field(..., ge=0.0, description="Current Days of Supply (DoS).")
    quoted_lead_time_days: int = Field(..., ge=1, description="Supplier lead time in days.")
    unit_cost_usd: float = Field(..., ge=0.01, description="Unit purchase price in USD.")
    minimum_order_qty: int = Field(..., ge=1, description="Minimum Order Quantity (MOQ) in units.")
    order_multiple: int = Field(..., ge=1, description="Order lot-sizing multiple in units.")
    standard_freight_per_unit_usd: float = Field(..., ge=0.0, description="Standard freight cost per unit in USD.")
    expedite_air_freight_per_unit_usd: float = Field(..., ge=0.0, description="Expedited air-freight cost per unit in USD.")
    working_capital_budget_usd: float = Field(..., ge=0.0, description="Approved working capital ceiling in USD.")


class AgentStructuredSynthesisSchema(BaseModel):
    """Explicit JSON Schema used to constrain LLM structured outputs (`response_schema`)."""

    summary: str = Field(..., description="Concise 2-4 sentence executive synthesis of the supply planning phase.")
    constitutional_compliance_status: str = Field(
        default="COMPLIANT",
        description="Supply Chain Constitution compliance status: 'COMPLIANT', 'CONDITIONAL_VIOLATION', or 'CRITICAL_VIOLATION'.",
    )
    key_risk_indicators: List[str] = Field(default_factory=list, description="Key supply risk or stockout indicators identified.")
    recommended_next_step: str = Field(default="Proceed to next planning phase.", description="Recommended S&OP governance action.")


class IntentClassificationStructuredSchema(BaseModel):
    """Explicit JSON Schema constraining the Coordinator Agent's intent routing output."""

    intent: str = Field(..., description="Classified planner intent: 'PLANNER_QUESTION' or 'SUPPLY_PACKET_SUBMISSION'.")
    pattern: str = Field(..., description="Selected multi-agent execution pattern: 'CONVERSATIONAL' or 'SEQUENTIAL'.")
    rationale: str = Field(..., description="Justification for selecting the conversational or sequential pattern.")


class SupplyRiskFinding(BaseModel):
    finding_id: str
    phase: str
    agent_name: str
    title: str
    description: str
    severity: RiskSeverity
    category: str
    recommendation: str


class PurchaseOrderActionItem(BaseModel):
    action_id: str
    owner: str
    priority: RiskSeverity
    requirement: str
    execution_window: str
    requires_s_and_op_signoff: bool = False


class ToolCallTrace(BaseModel):
    tool_name: str
    inputs: Dict[str, Any] = Field(default_factory=dict)
    output_summary: str
    timestamp: str
    json_schema_validated: bool = True
    invocation_mechanism: str = "native_llm_tool_calling"
    otel_span_id: Optional[str] = None


class PhaseAssessment(BaseModel):
    phase_id: str
    phase_name: str
    agent_name: str
    agent_role: str
    status: PhaseStatus = PhaseStatus.COMPLETED
    risk_score: float = Field(ge=0.0, le=100.0, description="0 = lowest supply risk, 100 = severe stockout/disruption risk")
    confidence: float = Field(default=0.94, ge=0.0, le=1.0)
    summary: str
    findings: List[SupplyRiskFinding] = Field(default_factory=list)
    tool_calls: List[ToolCallTrace] = Field(default_factory=list)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    llm_mode_used: str = "simulation"
    duration_ms: int = 0


class TriagePhaseOutput(PhaseAssessment):
    criticality_class: CriticalityClass = CriticalityClass.CLASS_A_CRITICAL
    inherent_criticality_score: float = 50.0
    days_of_supply: float = 15.0
    net_available_units: int = 1000
    required_erp_documents: List[str] = Field(default_factory=list)
    missing_erp_documents: List[str] = Field(default_factory=list)
    auto_release_eligible: bool = False
    required_phases: List[str] = Field(default_factory=list)


class FinalSupplyPlanDecision(BaseModel):
    decision: PlanDecision
    composite_supply_risk_score: float = Field(ge=0.0, le=100.0)
    residual_risk_level: RiskSeverity
    criticality_class: CriticalityClass
    recommended_order_qty: int = 0
    expedited_order_qty: int = 0
    estimated_total_po_spend_usd: float = 0.0
    safety_stock_target_units: int = 0
    reorder_point_units: int = 0
    executive_sop_memo: str
    key_strengths: List[str] = Field(default_factory=list)
    critical_blockers: List[str] = Field(default_factory=list)
    action_plan: List[PurchaseOrderActionItem] = Field(default_factory=list)
    next_review_days: int = 7
    human_override: Optional[Dict[str, Any]] = None


class SupplyPlanRunResult(BaseModel):
    plan_id: str
    created_at: str
    completed_at: Optional[str] = None
    orchestrator_engine: str
    llm_provider_status: str
    submission: SupplyPlanSubmission
    triage_assessment: Optional[TriagePhaseOutput] = None
    phase_assessments: Dict[str, PhaseAssessment] = Field(default_factory=dict)
    all_findings: List[SupplyRiskFinding] = Field(default_factory=list)
    final_decision: Optional[FinalSupplyPlanDecision] = None
    audit_trail: List[Dict[str, Any]] = Field(default_factory=list)


class HumanReviewDecisionRequest(BaseModel):
    decision: PlanDecision
    reviewer_name: str = "VP of Supply Chain & S&OP"
    notes: str
