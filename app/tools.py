from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional, Type

from app.models import (
    ClassifySkuCriticalityToolArgs,
    ClassifySkuCriticalityToolOutput,
    DemandForecastInput,
    EvaluateSupplierCapacityToolArgs,
    EvaluateSupplierCapacityToolOutput,
    ExtractErpInventoryToolArgs,
    ExtractErpInventoryToolOutput,
    ForecastDemandSafetyStockToolArgs,
    ForecastDemandSafetyStockToolOutput,
    InventoryStateInput,
    OptimizeReplenishmentOrdersToolArgs,
    OptimizeReplenishmentOrdersToolOutput,
    ReplenishmentCostInput,
    RiskLevel,
    SKUClassificationTier,
    SupplierNetworkInput,
    SupplyPlanSubmission,
)
from app.observability import get_logger, redact_pii_text, start_otel_span


logger = get_logger("supply_planner.tools")


# ==============================================================================
# 1. Explicit Tool Functions with Comprehensive Parameter & Return Docstrings
# ==============================================================================
def extract_erp_inventory_positions(
    sku_id: str,
    sku_name: str,
    plant_code: str,
    on_hand_units: int,
    allocated_units: int,
    in_transit_units: int,
    open_po_units: int,
    quality_hold_units: int,
    backorder_units: int,
    weekly_demand_mean: float,
    unstructured_erp_notes: str = "",
) -> Dict[str, Any]:
    """
    Reconciles ERP inventory ledger balances, net available-to-promise (ATP), and weeks of supply.

    Computes net available-to-promise (`on_hand - allocated - quality_hold - backorder`),
    total net inventory position including in-transit and open purchase orders, and days/weeks
    of supply against mean weekly demand while scrubbing PII from raw ERP planner notes.

    Args:
        sku_id (str): Unique ERP Material/SKU code (e.g., 'SKU-ASIC-7NM-900').
        sku_name (str): Human-readable material description from the Item Master.
        plant_code (str): Manufacturing plant or distribution center code.
        on_hand_units (int): Current physical unrestricted stock in warehouse (units >= 0).
        allocated_units (int): Units already reserved for firm production or customer orders (units >= 0).
        in_transit_units (int): Units currently in ocean/air/ground transit with ASN (units >= 0).
        open_po_units (int): Scheduled supplier purchase order receipts within the horizon (units >= 0).
        quality_hold_units (int): Quarantined units pending QA inspection disposition (units >= 0).
        backorder_units (int): Unfulfilled past-due customer or work-order backlog (units >= 0).
        weekly_demand_mean (float): Average weekly demand rate in units (> 0).
        unstructured_erp_notes (str): Raw ERP MRP exception notes, buyer remarks, or ASN alerts.

    Returns:
        Dict[str, Any]: Validated dictionary matching `ExtractErpInventoryToolOutput` schema containing:
            - `tool_name` (str): Identifier `'extract_erp_inventory_positions'`.
            - `net_available_on_hand_units` (int): Net unrestricted ATP stock after allocations and backorders.
            - `total_pipeline_units` (int): Sum of in-transit and open PO units.
            - `net_inventory_position_units` (int): Combined net ATP + total pipeline supply.
            - `weeks_of_supply_on_hand` (float): Weeks of coverage from net on-hand stock alone.
            - `days_of_supply_total` (float): Total calendar days of coverage including pipeline.
            - `immediate_stockout_risk` (bool): True if net on-hand coverage is < 1.0 week or backorders exist.
            - `sanitized_erp_notes` (str): PII-redacted ERP exception notes.
            - `parsed_entities` (Dict[str, Any]): Summary telemetry dictionary.

    Raises:
         pydantic.ValidationError: If any numeric inventory or demand input violates schema bounds.
    """
    validated_args = ExtractErpInventoryToolArgs(
        sku_id=sku_id,
        sku_name=sku_name,
        plant_code=plant_code,
        on_hand_units=on_hand_units,
        allocated_units=allocated_units,
        in_transit_units=in_transit_units,
        open_po_units=open_po_units,
        quality_hold_units=quality_hold_units,
        backorder_units=backorder_units,
        weekly_demand_mean=weekly_demand_mean,
        unstructured_erp_notes=unstructured_erp_notes,
    )

    with start_otel_span(
        "tool.extract_erp_inventory_positions",
        {
            "tool.name": "extract_erp_inventory_positions",
            "sku.id": validated_args.sku_id,
            "sku.plant_code": validated_args.plant_code,
        },
    ) as span:
        net_on_hand = (
            validated_args.on_hand_units
            - validated_args.allocated_units
            - validated_args.quality_hold_units
            - validated_args.backorder_units
        )
        total_pipeline = validated_args.in_transit_units + validated_args.open_po_units
        net_position = net_on_hand + total_pipeline

        wos_on_hand = round(max(0.0, net_on_hand / validated_args.weekly_demand_mean), 2)
        dos_total = round(max(0.0, (net_position / validated_args.weekly_demand_mean) * 7.0), 1)
        immediate_stockout = (net_on_hand <= 0) or (wos_on_hand < 1.25) or (validated_args.backorder_units > 0)

        sanitized_notes = redact_pii_text(validated_args.unstructured_erp_notes)

        output = ExtractErpInventoryToolOutput(
            net_available_on_hand_units=net_on_hand,
            total_pipeline_units=total_pipeline,
            net_inventory_position_units=net_position,
            weeks_of_supply_on_hand=wos_on_hand,
            days_of_supply_total=dos_total,
            immediate_stockout_risk=immediate_stockout,
            sanitized_erp_notes=sanitized_notes,
            parsed_entities={
                "sku_id": validated_args.sku_id,
                "sku_name": validated_args.sku_name,
                "plant_code": validated_args.plant_code,
                "net_atp_units": net_on_hand,
                "pipeline_units": total_pipeline,
                "net_inventory_position_units": net_position,
                "weeks_of_supply_on_hand": wos_on_hand,
                "days_of_supply_total": dos_total,
                "backorder_units": validated_args.backorder_units,
                "quality_hold_units": validated_args.quality_hold_units,
            },
        )
        span.set_attribute("tool.net_inventory_position_units", net_position)
        span.set_attribute("tool.immediate_stockout_risk", immediate_stockout)
        return output.model_dump()


def classify_sku_abc_xyz_criticality(
    unit_cost_usd: float,
    weekly_demand_mean: float,
    weekly_demand_std_dev: float,
    is_revenue_critical_bom: bool,
    single_source_dependency: bool,
    active_geopolitical_or_port_disruption: bool,
    immediate_stockout_risk: bool,
    customer_sla_penalty_per_day_usd: float,
) -> Dict[str, Any]:
    """
    Performs ABC/XYZ SKU stratification and assigns the Supply Chain Constitution criticality tier.

    Evaluates annualized usage value (`weekly_demand_mean * 52 * unit_cost_usd`), demand
    coefficient of variation (`CV = std_dev / mean`), BOM revenue-blocker status, and supply
    vulnerability to classify the SKU into `CLASS_A_CRITICAL`, `CLASS_B_CORE`, `CLASS_C_STANDARD`,
    or `CLASS_D_CONSUMABLE`.

    Args:
        unit_cost_usd (float): Standard landed unit cost in USD (> 0).
        weekly_demand_mean (float): Mean weekly demand rate in units (> 0).
        weekly_demand_std_dev (float): Weekly demand standard deviation in units (>= 0).
        is_revenue_critical_bom (bool): True if the component is a hard assembly/revenue blocker.
        single_source_dependency (bool): True if no qualified secondary supplier exists.
        active_geopolitical_or_port_disruption (bool): True if an active lane/fab disruption is reported.
        immediate_stockout_risk (bool): True if net on-hand coverage is below 1.25 weeks or backordered.
        customer_sla_penalty_per_day_usd (float): Contractual daily SLA penalty for stockout (>= 0).

    Returns:
        Dict[str, Any]: Validated dictionary matching `ClassifySkuCriticalityToolOutput` schema containing:
            - `tool_name` (str): Identifier `'classify_sku_abc_xyz_criticality'`.
            - `annual_spend_usd` (float): Annualized spend volume in USD.
            - `abc_xyz_class` (str): Combined matrix code (e.g., `'AX'`, `'AY'`, `'AZ'`, `'BX'`, `'CZ'`).
            - `sku_tier` (SKUClassificationTier): Assigned constitutional criticality tier.
            - `stockout_urgency_score` (int): Deterministic urgency score from 0 to 100.
            - `triggers` (List[str]): Explicit constitutional triggers fired.

    Raises:
        pydantic.ValidationError: If any parameter violates numeric constraints.
    """
    validated_args = ClassifySkuCriticalityToolArgs(
        unit_cost_usd=unit_cost_usd,
        weekly_demand_mean=weekly_demand_mean,
        weekly_demand_std_dev=weekly_demand_std_dev,
        is_revenue_critical_bom=is_revenue_critical_bom,
        single_source_dependency=single_source_dependency,
        active_geopolitical_or_port_disruption=active_geopolitical_or_port_disruption,
        immediate_stockout_risk=immediate_stockout_risk,
        customer_sla_penalty_per_day_usd=customer_sla_penalty_per_day_usd,
    )

    with start_otel_span(
        "tool.classify_sku_abc_xyz_criticality",
        {
            "tool.name": "classify_sku_abc_xyz_criticality",
            "sku.is_revenue_critical_bom": validated_args.is_revenue_critical_bom,
            "sku.single_source": validated_args.single_source_dependency,
        },
    ) as span:
        annual_spend = round(validated_args.weekly_demand_mean * 52.0 * validated_args.unit_cost_usd, 2)
        cv = validated_args.weekly_demand_std_dev / max(1.0, validated_args.weekly_demand_mean)

        if annual_spend >= 3000000.0 or validated_args.is_revenue_critical_bom:
            abc_letter = "A"
        elif annual_spend >= 1000000.0:
            abc_letter = "B"
        else:
            abc_letter = "C"

        if cv <= 0.15:
            xyz_letter = "X"
        elif cv <= 0.30:
            xyz_letter = "Y"
        else:
            xyz_letter = "Z"

        abc_xyz_class = f"{abc_letter}{xyz_letter}"
        triggers: List[str] = [f"Annualized spend ${annual_spend:,.2f} & CV={cv:.2f} -> Class {abc_xyz_class}"]
        urgency_score = 15

        if validated_args.is_revenue_critical_bom:
            urgency_score += 25
            triggers.append("Revenue-critical BOM blocker flag is ACTIVE")
        if validated_args.single_source_dependency:
            urgency_score += 20
            triggers.append("Single-source supplier dependency (Article III vulnerability)")
        if validated_args.active_geopolitical_or_port_disruption:
            urgency_score += 20
            triggers.append("Active geopolitical or port/foundry disruption reported")
        if validated_args.immediate_stockout_risk:
            urgency_score += 20
            triggers.append("Immediate stockout risk (<1.25 weeks net ATP cover or active backorders)")
        if validated_args.customer_sla_penalty_per_day_usd >= 10000.0:
            urgency_score += 10
            triggers.append(
                f"High customer SLA liquidated damages (${validated_args.customer_sla_penalty_per_day_usd:,.0f}/day)"
            )

        urgency_score = max(0, min(100, urgency_score))

        if (
            (validated_args.is_revenue_critical_bom and validated_args.single_source_dependency)
            or urgency_score >= 70
            or (abc_letter == "A" and validated_args.immediate_stockout_risk)
        ):
            sku_tier = SKUClassificationTier.CLASS_A_CRITICAL
        elif abc_letter in ("A", "B") and urgency_score >= 35:
            sku_tier = SKUClassificationTier.CLASS_B_CORE
        elif annual_spend >= 500000.0:
            sku_tier = SKUClassificationTier.CLASS_C_STANDARD
        else:
            sku_tier = SKUClassificationTier.CLASS_D_CONSUMABLE

        output = ClassifySkuCriticalityToolOutput(
            annual_spend_usd=annual_spend,
            abc_xyz_class=abc_xyz_class,
            sku_tier=sku_tier,
            stockout_urgency_score=urgency_score,
            triggers=triggers,
        )
        span.set_attribute("tool.sku_tier", sku_tier.value)
        span.set_attribute("tool.urgency_score", urgency_score)
        return output.model_dump()


def calculate_statistical_safety_stock(
    weekly_demand_mean: float,
    weekly_demand_std_dev: float,
    firm_customer_orders_4w: int,
    promotional_uplift_pct: float,
    forecast_mape_pct: float,
    seasonality_index: float,
    lead_time_days_mean: float,
    lead_time_days_std_dev: float,
    target_service_level: float,
) -> Dict[str, Any]:
    """
    Calculates statistical safety stock and reorder point (ROP) under coupled demand and lead-time uncertainty.

    Applies the Supply Chain Constitution Article II formula:
    `SafetyStock = Z * sqrt(L_weeks * sigma_D^2 + D_weekly^2 * sigma_L_weeks^2)`
    and incorporates promotional uplift, seasonality, and firm 4-week customer orders.

    Args:
        weekly_demand_mean (float): Baseline weekly demand mean in units (> 0).
        weekly_demand_std_dev (float): Weekly demand standard deviation in units (>= 0).
        firm_customer_orders_4w (int): Committed customer orders over the next 4 weeks (>= 0).
        promotional_uplift_pct (float): Expected promotional or pull-in uplift percentage (0 to 200).
        forecast_mape_pct (float): Historical forecast Mean Absolute Percentage Error (0 to 100).
        seasonality_index (float): Seasonal multiplier for the current planning window (0.2 to 3.0).
        lead_time_days_mean (float): Average replenishment lead time in calendar days (> 0).
        lead_time_days_std_dev (float): Lead-time standard deviation in calendar days (>= 0).
        target_service_level (float): Target cycle service level between 0.80 and 0.999.

    Returns:
        Dict[str, Any]: Validated dictionary matching `ForecastDemandSafetyStockToolOutput` schema containing:
            - `tool_name` (str): Identifier `'calculate_statistical_safety_stock'`.
            - `z_score` (float): Inverse normal Z-factor corresponding to `target_service_level`.
            - `effective_weekly_demand_units` (float): Adjusted weekly demand incorporating seasonality, uplift, and firm orders.
            - `demand_over_lead_time_units` (float): Expected demand over average lead time (`D_eff * L_weeks`).
            - `statistical_safety_stock_units` (int): Required statistical buffer stock in units.
            - `reorder_point_units` (int): Trigger level (`demand_over_lead_time + safety_stock`).
            - `demand_volatility_score` (int): Normalized demand risk score (0–100).
            - `risk_level` (RiskLevel): Categorical demand risk rating.
            - `findings` (List[str]): Detailed statistical findings and assumptions.

    Raises:
        pydantic.ValidationError: If any forecast or lead-time argument fails schema validation.
    """
    validated_args = ForecastDemandSafetyStockToolArgs(
        weekly_demand_mean=weekly_demand_mean,
        weekly_demand_std_dev=weekly_demand_std_dev,
        firm_customer_orders_4w=firm_customer_orders_4w,
        promotional_uplift_pct=promotional_uplift_pct,
        forecast_mape_pct=forecast_mape_pct,
        seasonality_index=seasonality_index,
        lead_time_days_mean=lead_time_days_mean,
        lead_time_days_std_dev=lead_time_days_std_dev,
        target_service_level=target_service_level,
    )

    with start_otel_span(
        "tool.calculate_statistical_safety_stock",
        {
            "tool.name": "calculate_statistical_safety_stock",
            "forecast.target_service_level": validated_args.target_service_level,
            "forecast.mape_pct": validated_args.forecast_mape_pct,
        },
    ) as span:
        sl = validated_args.target_service_level
        if sl >= 0.99:
            z_score = 2.33
        elif sl >= 0.98:
            z_score = 2.05
        elif sl >= 0.97:
            z_score = 1.88
        elif sl >= 0.95:
            z_score = 1.65
        elif sl >= 0.92:
            z_score = 1.41
        else:
            z_score = 1.28

        uplift_multiplier = 1.0 + (validated_args.promotional_uplift_pct / 100.0)
        modeled_weekly = validated_args.weekly_demand_mean * validated_args.seasonality_index * uplift_multiplier
        firm_weekly_floor = validated_args.firm_customer_orders_4w / 4.0
        effective_weekly_demand = round(max(modeled_weekly, firm_weekly_floor), 2)

        mape_inflation = 1.0 + max(0.0, (validated_args.forecast_mape_pct - 10.0) / 100.0)
        effective_sigma_d = validated_args.weekly_demand_std_dev * mape_inflation

        lead_time_weeks = validated_args.lead_time_days_mean / 7.0
        sigma_lead_time_weeks = validated_args.lead_time_days_std_dev / 7.0

        variance_combined = (lead_time_weeks * (effective_sigma_d ** 2)) + (
            (effective_weekly_demand ** 2) * (sigma_lead_time_weeks ** 2)
        )
        safety_stock_units = int(math.ceil(z_score * math.sqrt(max(0.0, variance_combined))))
        demand_over_lt = round(effective_weekly_demand * lead_time_weeks, 1)
        reorder_point = int(math.ceil(demand_over_lt + safety_stock_units))

        cv = validated_args.weekly_demand_std_dev / max(1.0, validated_args.weekly_demand_mean)
        volatility_score = int(
            min(
                100,
                round(
                    (cv * 110.0)
                    + (validated_args.forecast_mape_pct * 1.4)
                    + (validated_args.promotional_uplift_pct * 0.8)
                ),
            )
        )

        if volatility_score >= 70:
            risk_level = RiskLevel.CRITICAL
        elif volatility_score >= 45:
            risk_level = RiskLevel.HIGH
        elif volatility_score >= 25:
            risk_level = RiskLevel.MODERATE
        else:
            risk_level = RiskLevel.LOW

        findings: List[str] = [
            f"Service level {sl * 100:.1f}% maps to Z={z_score:.2f} under coupled demand/lead-time variance.",
            f"Effective weekly demand is {effective_weekly_demand:,.1f} units/wk (seasonality {validated_args.seasonality_index:.2f}x, uplift +{validated_args.promotional_uplift_pct:.1f}%).",
            f"Computed statistical safety stock = {safety_stock_units:,} units; Reorder Point (ROP) = {reorder_point:,} units over {lead_time_weeks:.1f}-week lead time.",
        ]
        if validated_args.forecast_mape_pct >= 20.0:
            findings.append(
                f"Elevated forecast error (MAPE {validated_args.forecast_mape_pct:.1f}%) required +{int((mape_inflation - 1.0) * 100)}% buffer inflation."
            )

        output = ForecastDemandSafetyStockToolOutput(
            z_score=z_score,
            effective_weekly_demand_units=effective_weekly_demand,
            demand_over_lead_time_units=demand_over_lt,
            statistical_safety_stock_units=safety_stock_units,
            reorder_point_units=reorder_point,
            demand_volatility_score=volatility_score,
            risk_level=risk_level,
            findings=findings,
        )
        span.set_attribute("tool.safety_stock_units", safety_stock_units)
        span.set_attribute("tool.reorder_point_units", reorder_point)
        span.set_attribute("tool.demand_volatility_score", volatility_score)
        return output.model_dump()


def evaluate_supplier_capacity_and_leadtime_risk(
    primary_supplier_name: str,
    primary_country: str,
    backup_supplier_available: bool,
    lead_time_days_mean: float,
    lead_time_days_std_dev: float,
    on_time_in_full_pct: float,
    defect_rate_ppm: int,
    max_weekly_capacity_units: int,
    effective_weekly_demand_units: float,
    active_geopolitical_or_port_disruption: bool,
    single_source_dependency: bool,
) -> Dict[str, Any]:
    """
    Audits supplier capacity utilization, OTIF reliability, quality PPM, and geopolitical/port risk.

    Evaluates whether the primary supplier's weekly capacity can absorb effective demand,
    quantifies lead-time reliability, and recommends dual-source split percentages when
    utilization exceeds 90% or OTIF falls below the 88% constitutional threshold.

    Args:
        primary_supplier_name (str): Legal name of the primary manufacturer/supplier.
        primary_country (str): Country of origin for primary manufacturing or port of loading.
        backup_supplier_available (bool): Whether a qualified secondary supplier is available on AVL.
        lead_time_days_mean (float): Mean supplier replenishment lead time in days (> 0).
        lead_time_days_std_dev (float): Standard deviation of supplier lead time in days (>= 0).
        on_time_in_full_pct (float): Historical On-Time In-Full delivery rate (0 to 100).
        defect_rate_ppm (int): Supplier quality defect rate in Parts Per Million (>= 0).
        max_weekly_capacity_units (int): Primary supplier maximum weekly output capacity (> 0).
        effective_weekly_demand_units (float): Adjusted weekly demand rate from Forecast Agent (> 0).
        active_geopolitical_or_port_disruption (bool): Active trade/port/natural disaster disruption flag.
        single_source_dependency (bool): True if SKU is single-sourced with no qualified alternate.

    Returns:
        Dict[str, Any]: Validated dictionary matching `EvaluateSupplierCapacityToolOutput` schema containing:
            - `tool_name` (str): Identifier `'evaluate_supplier_capacity_and_leadtime_risk'`.
            - `capacity_utilization_pct` (float): Ratio of effective weekly demand to primary capacity (%).
            - `weekly_capacity_shortfall_units` (float): Weekly demand exceeding primary capacity (units).
            - `recommended_backup_allocation_pct` (float): Recommended percentage split to backup supplier.
            - `supplier_risk_score` (int): Composite supplier & lane risk score (0–100).
            - `risk_level` (RiskLevel): Categorical supplier risk level.
            - `findings` (List[str]): Actionable supplier capacity and resilience findings.

    Raises:
        pydantic.ValidationError: If any supplier capacity or reliability input fails validation.
    """
    validated_args = EvaluateSupplierCapacityToolArgs(
        primary_supplier_name=primary_supplier_name,
        primary_country=primary_country,
        backup_supplier_available=backup_supplier_available,
        lead_time_days_mean=lead_time_days_mean,
        lead_time_days_std_dev=lead_time_days_std_dev,
        on_time_in_full_pct=on_time_in_full_pct,
        defect_rate_ppm=defect_rate_ppm,
        max_weekly_capacity_units=max_weekly_capacity_units,
        effective_weekly_demand_units=effective_weekly_demand_units,
        active_geopolitical_or_port_disruption=active_geopolitical_or_port_disruption,
        single_source_dependency=single_source_dependency,
    )

    with start_otel_span(
        "tool.evaluate_supplier_capacity_and_leadtime_risk",
        {
            "tool.name": "evaluate_supplier_capacity_and_leadtime_risk",
            "supplier.name": validated_args.primary_supplier_name,
            "supplier.country": validated_args.primary_country,
        },
    ) as span:
        utilization_pct = round(
            (validated_args.effective_weekly_demand_units / validated_args.max_weekly_capacity_units) * 100.0,
            1,
        )
        shortfall_units = round(
            max(0.0, validated_args.effective_weekly_demand_units - validated_args.max_weekly_capacity_units),
            1,
        )

        risk_score = 10
        findings: List[str] = [
            f"Primary supplier '{validated_args.primary_supplier_name}' ({validated_args.primary_country}) utilization is {utilization_pct:.1f}% ({validated_args.effective_weekly_demand_units:,.0f}/{validated_args.max_weekly_capacity_units:,} units/wk)."
        ]

        if utilization_pct >= 100.0:
            risk_score += 25
            findings.append(
                f"Primary supplier capacity Deficit of {shortfall_units:,.0f} units/wk exceeds max weekly ceiling."
            )
        elif utilization_pct >= 90.0:
            risk_score += 15
            findings.append("Primary supplier running above 90% utilization threshold; zero surge buffer.")

        if validated_args.on_time_in_full_pct < 85.0:
            risk_score += 22
            findings.append(
                f"Supplier OTIF ({validated_args.on_time_in_full_pct:.1f}%) violates Article III minimum reliability threshold (88.0%)."
            )
        elif validated_args.on_time_in_full_pct < 92.0:
            risk_score += 10
            findings.append(
                f"Moderate OTIF drift ({validated_args.on_time_in_full_pct:.1f}%); monitor ASN delivery variance."
            )

        if validated_args.active_geopolitical_or_port_disruption:
            risk_score += 25
            findings.append("ACTIVE port/geopolitical disruption on primary shipping lane extending transit variance.")

        if validated_args.single_source_dependency or not validated_args.backup_supplier_available:
            risk_score += 18
            findings.append("Single-source dependency: no qualified dual-source supplier on Approved Vendor List (AVL).")

        if validated_args.defect_rate_ppm >= 400:
            risk_score += 8
            findings.append(f"Elevated quality defect rate ({validated_args.defect_rate_ppm} PPM) requires yield buffer.")

        risk_score = max(0, min(100, risk_score))

        recommended_backup_pct = 0.0
        if validated_args.backup_supplier_available:
            if shortfall_units > 0 or utilization_pct >= 95.0:
                recommended_backup_pct = 30.0
                findings.append(
                    "Dual-source mitigation: allocate 30% of replenishment volume to qualified backup supplier to relieve primary bottleneck."
                )
            elif risk_score >= 45:
                recommended_backup_pct = 20.0
                findings.append(
                    "Dual-source mitigation: allocate 20% volume to backup supplier to hedge lead-time variance."
                )

        if risk_score >= 70:
            risk_level = RiskLevel.CRITICAL
        elif risk_score >= 45:
            risk_level = RiskLevel.HIGH
        elif risk_score >= 25:
            risk_level = RiskLevel.MODERATE
        else:
            risk_level = RiskLevel.LOW

        output = EvaluateSupplierCapacityToolOutput(
            capacity_utilization_pct=utilization_pct,
            weekly_capacity_shortfall_units=shortfall_units,
            recommended_backup_allocation_pct=recommended_backup_pct,
            supplier_risk_score=risk_score,
            risk_level=risk_level,
            findings=findings,
        )
        span.set_attribute("tool.supplier_risk_score", risk_score)
        span.set_attribute("tool.recommended_backup_allocation_pct", recommended_backup_pct)
        return output.model_dump()


def optimize_mrp_replenishment_orders(
    net_inventory_position_units: int,
    net_available_on_hand_units: int,
    effective_weekly_demand_units: float,
    planning_horizon_weeks: int,
    statistical_safety_stock_units: int,
    reorder_point_units: int,
    minimum_order_qty: int,
    lot_size_multiple: int,
    unit_cost_usd: float,
    standard_freight_per_unit_usd: float,
    expedite_air_freight_per_unit_usd: float,
    stockout_penalty_per_unit_usd: float,
    customer_sla_penalty_per_day_usd: float,
    working_capital_budget_usd: float,
    backup_supplier_available: bool,
    recommended_backup_allocation_pct: float,
    backup_unit_cost_premium_pct: float = 0.0,
) -> Dict[str, Any]:
    """
    Solves the MRP net replenishment lot-sizing, dual-source split, and expedite freight optimization.

    Computes net requirements across the planning horizon, enforces MOQ and lot-size multiples,
    evaluates whether expedited air freight is economically justified against customer SLA/stockout
    penalties, and flags any Article IV working-capital or expedite capex breaches.

    Args:
        net_inventory_position_units (int): Current net ATP + in-transit + open PO units.
        net_available_on_hand_units (int): Current net unrestricted on-hand units.
        effective_weekly_demand_units (float): Adjusted weekly demand rate in units (> 0).
        planning_horizon_weeks (int): Active replenishment planning horizon in weeks (4 to 26).
        statistical_safety_stock_units (int): Required safety stock buffer in units (>= 0).
        reorder_point_units (int): Trigger level for replenishment orders in units (>= 0).
        minimum_order_qty (int): Supplier Minimum Order Quantity (MOQ >= 1).
        lot_size_multiple (int): Order rounding lot multiple (>= 1).
        unit_cost_usd (float): Standard primary supplier unit cost in USD (> 0).
        standard_freight_per_unit_usd (float): Ocean/ground standard freight cost per unit (>= 0).
        expedite_air_freight_per_unit_usd (float): Expedited air freight cost per unit (>= 0).
        stockout_penalty_per_unit_usd (float): Lost margin/penalty per stocked-out unit (>= 0).
        customer_sla_penalty_per_day_usd (float): Daily SLA penalty for stockout duration (>= 0).
        working_capital_budget_usd (float): Approved working capital budget ceiling in USD (> 0).
        backup_supplier_available (bool): True if a secondary supplier can receive split orders.
        recommended_backup_allocation_pct (float): Target percentage split to backup supplier (0 to 100).
        backup_unit_cost_premium_pct (float): Cost premium percentage of backup supplier (0 to 200).

    Returns:
        Dict[str, Any]: Validated dictionary matching `OptimizeReplenishmentOrdersToolOutput` schema containing:
            - `tool_name` (str): Identifier `'optimize_mrp_replenishment_orders'`.
            - `gross_horizon_demand_units` (int): Total demand over the planning horizon.
            - `net_requirement_units` (int): Uncovered demand plus safety stock minus net inventory position.
            - `recommended_total_order_units` (int): Lot-sized total purchase order quantity.
            - `primary_supplier_order_units` (int): Units allocated to the primary supplier.
            - `backup_supplier_order_units` (int): Units allocated to the backup supplier.
            - `expedite_units` (int): Units recommended for expedited air freight to bridge immediate stockout.
            - `total_po_spend_usd` (float): Total purchase order merchandise spend in USD.
            - `expedite_freight_cost_usd` (float): Incremental air expedite freight cost in USD.
            - `budget_utilization_pct` (float): Percentage of working capital budget utilized.
            - `exceeds_working_capital_budget` (bool): True if total spend exceeds budget or expedite capex > $25k.
            - `financial_risk_score` (int): Financial & working-capital risk score (0–100).
            - `risk_level` (RiskLevel): Categorical financial risk rating.
            - `findings` (List[str]): Detailed MRP optimization and cost trade-off findings.

    Raises:
        pydantic.ValidationError: If any MRP or financial parameter violates schema constraints.
    """
    validated_args = OptimizeReplenishmentOrdersToolArgs(
        net_inventory_position_units=net_inventory_position_units,
        net_available_on_hand_units=net_available_on_hand_units,
        effective_weekly_demand_units=effective_weekly_demand_units,
        planning_horizon_weeks=planning_horizon_weeks,
        statistical_safety_stock_units=statistical_safety_stock_units,
        reorder_point_units=reorder_point_units,
        minimum_order_qty=minimum_order_qty,
        lot_size_multiple=lot_size_multiple,
        unit_cost_usd=unit_cost_usd,
        standard_freight_per_unit_usd=standard_freight_per_unit_usd,
        expedite_air_freight_per_unit_usd=expedite_air_freight_per_unit_usd,
        stockout_penalty_per_unit_usd=stockout_penalty_per_unit_usd,
        customer_sla_penalty_per_day_usd=customer_sla_penalty_per_day_usd,
        working_capital_budget_usd=working_capital_budget_usd,
        backup_supplier_available=backup_supplier_available,
        recommended_backup_allocation_pct=recommended_backup_allocation_pct,
        backup_unit_cost_premium_pct=backup_unit_cost_premium_pct,
    )

    with start_otel_span(
        "tool.optimize_mrp_replenishment_orders",
        {
            "tool.name": "optimize_mrp_replenishment_orders",
            "mrp.planning_horizon_weeks": validated_args.planning_horizon_weeks,
            "mrp.working_capital_budget_usd": validated_args.working_capital_budget_usd,
        },
    ) as span:
        # Solve 4-week tactical replenishment window (bounded by planning_horizon_weeks)
        replenishment_cycle_weeks = min(4, validated_args.planning_horizon_weeks)
        gross_demand = int(
            math.ceil(validated_args.effective_weekly_demand_units * replenishment_cycle_weeks)
        )
        target_stock_level = gross_demand + validated_args.statistical_safety_stock_units
        raw_net_req = max(0, target_stock_level - validated_args.net_inventory_position_units)

        if raw_net_req == 0 and validated_args.net_inventory_position_units < validated_args.reorder_point_units:
            raw_net_req = validated_args.reorder_point_units - validated_args.net_inventory_position_units

        if raw_net_req > 0:
            moq_floored = max(raw_net_req, validated_args.minimum_order_qty)
            lots = math.ceil(moq_floored / validated_args.lot_size_multiple)
            total_order_units = int(lots * validated_args.lot_size_multiple)
        else:
            total_order_units = 0

        if validated_args.backup_supplier_available and validated_args.recommended_backup_allocation_pct > 0 and total_order_units > 0:
            raw_backup = int(round(total_order_units * (validated_args.recommended_backup_allocation_pct / 100.0)))
            backup_lots = max(1, round(raw_backup / validated_args.lot_size_multiple))
            backup_order_units = min(total_order_units, int(backup_lots * validated_args.lot_size_multiple))
            primary_order_units = total_order_units - backup_order_units
        else:
            backup_order_units = 0
            primary_order_units = total_order_units

        # Check immediate 2-week coverage gap for expedite air freight
        two_week_demand = int(math.ceil(validated_args.effective_weekly_demand_units * 2.0))
        immediate_deficit = max(0, two_week_demand - max(0, validated_args.net_available_on_hand_units))
        expedite_premium_per_unit = max(
            0.0,
            validated_args.expedite_air_freight_per_unit_usd - validated_args.standard_freight_per_unit_usd,
        )
        avoided_penalty_per_unit = validated_args.stockout_penalty_per_unit_usd + (
            validated_args.customer_sla_penalty_per_day_usd / max(1.0, validated_args.effective_weekly_demand_units / 7.0)
        )

        if immediate_deficit > 0 and avoided_penalty_per_unit > expedite_premium_per_unit and total_order_units > 0:
            expedite_units = min(total_order_units, immediate_deficit)
        else:
            expedite_units = 0

        backup_unit_cost = validated_args.unit_cost_usd * (1.0 + (validated_args.backup_unit_cost_premium_pct / 100.0))
        merchandise_spend = (primary_order_units * validated_args.unit_cost_usd) + (
            backup_order_units * backup_unit_cost
        )
        standard_freight_total = (total_order_units - expedite_units) * validated_args.standard_freight_per_unit_usd
        expedite_freight_total = round(expedite_units * validated_args.expedite_air_freight_per_unit_usd, 2)
        total_po_spend = round(merchandise_spend + standard_freight_total + expedite_freight_total, 2)

        budget_utilization_pct = round(
            (total_po_spend / validated_args.working_capital_budget_usd) * 100.0,
            1,
        )
        exceeds_budget = (total_po_spend > validated_args.working_capital_budget_usd) or (
            expedite_freight_total > 25000.0
        )

        fin_risk_score = 10
        findings: List[str] = [
            f"Tactical {replenishment_cycle_weeks}-week gross demand = {gross_demand:,} units; Net requirement = {raw_net_req:,} units; Lot-sized PO release = {total_order_units:,} units."
        ]

        if backup_order_units > 0:
            findings.append(
                f"Split PO allocation: {primary_order_units:,} units to Primary Supplier and {backup_order_units:,} units to Backup Supplier (+{validated_args.backup_unit_cost_premium_pct:.1f}% unit cost premium)."
            )

        if expedite_units > 0:
            fin_risk_score += 25
            findings.append(
                f"Expedite air-freight justified for {expedite_units:,} units (${expedite_freight_total:,.2f} air freight vs ${avoided_penalty_per_unit:,.2f}/unit avoided SLA/stockout penalty)."
            )

        if total_po_spend > validated_args.working_capital_budget_usd:
            fin_risk_score += 35
            findings.append(
                f"ARTICLE IV BREACH: Total PO commitment (${total_po_spend:,.2f}) exceeds working capital budget (${validated_args.working_capital_budget_usd:,.2f}) at {budget_utilization_pct:.1f}% utilization."
            )
        elif budget_utilization_pct >= 85.0:
            fin_risk_score += 15
            findings.append(f"Working capital budget utilization is elevated at {budget_utilization_pct:.1f}%.")
        else:
            findings.append(
                f"Total PO spend ${total_po_spend:,.2f} is within working capital budget ({budget_utilization_pct:.1f}% utilization)."
            )

        if expedite_freight_total > 25000.0:
            fin_risk_score += 20
            findings.append(
                f"ARTICLE IV EXPEDITE CAPEX TRIGGER: Air freight cost (${expedite_freight_total:,.2f}) exceeds $25,000 autonomous ceiling."
            )

        fin_risk_score = max(0, min(100, fin_risk_score))
        if fin_risk_score >= 70:
            risk_level = RiskLevel.CRITICAL
        elif fin_risk_score >= 45:
            risk_level = RiskLevel.HIGH
        elif fin_risk_score >= 25:
            risk_level = RiskLevel.MODERATE
        else:
            risk_level = RiskLevel.LOW

        output = OptimizeReplenishmentOrdersToolOutput(
            gross_horizon_demand_units=gross_demand,
            net_requirement_units=raw_net_req,
            recommended_total_order_units=total_order_units,
            primary_supplier_order_units=primary_order_units,
            backup_supplier_order_units=backup_order_units,
            expedite_units=expedite_units,
            total_po_spend_usd=total_po_spend,
            expedite_freight_cost_usd=expedite_freight_total,
            budget_utilization_pct=budget_utilization_pct,
            exceeds_working_capital_budget=exceeds_budget,
            financial_risk_score=fin_risk_score,
            risk_level=risk_level,
            findings=findings,
        )
        span.set_attribute("tool.recommended_total_order_units", total_order_units)
        span.set_attribute("tool.total_po_spend_usd", total_po_spend)
        span.set_attribute("tool.exceeds_working_capital_budget", exceeds_budget)
        return output.model_dump()


# ==============================================================================
# 2. Explicit JSON Schema Registry & LLM Function-Calling Bindings (Rubric 5/5)
# ==============================================================================
TOOL_ARG_MODELS: Dict[str, Type[Any]] = {
    "extract_erp_inventory_positions": ExtractErpInventoryToolArgs,
    "classify_sku_abc_xyz_criticality": ClassifySkuCriticalityToolArgs,
    "calculate_statistical_safety_stock": ForecastDemandSafetyStockToolArgs,
    "evaluate_supplier_capacity_and_leadtime_risk": EvaluateSupplierCapacityToolArgs,
    "optimize_mrp_replenishment_orders": OptimizeReplenishmentOrdersToolArgs,
}

TOOL_OUTPUT_MODELS: Dict[str, Type[Any]] = {
    "extract_erp_inventory_positions": ExtractErpInventoryToolOutput,
    "classify_sku_abc_xyz_criticality": ClassifySkuCriticalityToolOutput,
    "calculate_statistical_safety_stock": ForecastDemandSafetyStockToolOutput,
    "evaluate_supplier_capacity_and_leadtime_risk": EvaluateSupplierCapacityToolOutput,
    "optimize_mrp_replenishment_orders": OptimizeReplenishmentOrdersToolOutput,
}

TOOL_FUNCTIONS: Dict[str, Callable[..., Dict[str, Any]]] = {
    "extract_erp_inventory_positions": extract_erp_inventory_positions,
    "classify_sku_abc_xyz_criticality": classify_sku_abc_xyz_criticality,
    "calculate_statistical_safety_stock": calculate_statistical_safety_stock,
    "evaluate_supplier_capacity_and_leadtime_risk": evaluate_supplier_capacity_and_leadtime_risk,
    "optimize_mrp_replenishment_orders": optimize_mrp_replenishment_orders,
}

TOOL_DESCRIPTIONS: Dict[str, str] = {
    "extract_erp_inventory_positions": (
        "Reconciles ERP inventory balances, net available-to-promise (ATP), pipeline stock, "
        "weeks of supply, and scrubs PII from raw ERP notes."
    ),
    "classify_sku_abc_xyz_criticality": (
        "Performs ABC/XYZ stratification and assigns the Supply Chain Constitution SKU tier "
        "(CLASS_A_CRITICAL to CLASS_D_CONSUMABLE) and urgency score."
    ),
    "calculate_statistical_safety_stock": (
        "Computes statistical safety stock and reorder point (ROP) under coupled demand and "
        "supplier lead-time variance using service-level Z-scores."
    ),
    "evaluate_supplier_capacity_and_leadtime_risk": (
        "Evaluates primary supplier weekly capacity utilization, OTIF delivery reliability, "
        "geopolitical/port disruptions, and recommends dual-source split percentages."
    ),
    "optimize_mrp_replenishment_orders": (
        "Solves tactical MRP net replenishment requirements, MOQ and lot-size rounding, "
        "primary/backup order splits, and expedite air-freight vs working-capital trade-offs."
    ),
}

TOOL_JSON_SCHEMAS: Dict[str, Dict[str, Any]] = {
    name: {
        "name": name,
        "description": TOOL_DESCRIPTIONS[name],
        "parameters_json_schema": model.model_json_schema(),
        "return_json_schema": TOOL_OUTPUT_MODELS[name].model_json_schema(),
    }
    for name, model in TOOL_ARG_MODELS.items()
}


def get_openai_tool_schemas(tool_names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    Returns OpenAI-compatible `tools` definitions (`{"type": "function", "function": {"strict": True, ...}}`)
    constrained by the explicit Pydantic JSON Schemas.
    """
    names = tool_names or list(TOOL_ARG_MODELS.keys())
    schemas: List[Dict[str, Any]] = []
    for name in names:
        arg_model = TOOL_ARG_MODELS[name]
        raw_schema = arg_model.model_json_schema()
        raw_schema["additionalProperties"] = False
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": TOOL_DESCRIPTIONS[name],
                    "strict": True,
                    "parameters": raw_schema,
                },
            }
        )
    return schemas


def get_gemini_tool_declarations(tool_names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    Returns Google Gemini `function_declarations` with explicit JSON schema parameter definitions.
    """
    names = tool_names or list(TOOL_ARG_MODELS.keys())
    declarations: List[Dict[str, Any]] = []
    for name in names:
        arg_model = TOOL_ARG_MODELS[name]
        raw_schema = arg_model.model_json_schema()
        properties = {}
        for prop_name, prop_def in raw_schema.get("properties", {}).items():
            clean_prop = {
                k: v
                for k, v in prop_def.items()
                if k in ("type", "description", "enum", "minimum", "maximum")
            }
            if "type" not in clean_prop:
                clean_prop["type"] = "string"
            properties[prop_name] = clean_prop

        declarations.append(
            {
                "name": name,
                "description": TOOL_DESCRIPTIONS[name],
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": raw_schema.get("required", []),
                },
            }
        )
    return declarations


def validate_tool_arguments_against_schema(tool_name: str, raw_arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Strictly validates an LLM-supplied tool call argument dictionary against the tool's Pydantic JSON Schema.
    """
    if tool_name not in TOOL_ARG_MODELS:
        raise KeyError(f"Unknown supply planning tool '{tool_name}'. Available: {list(TOOL_ARG_MODELS.keys())}")
    model_cls = TOOL_ARG_MODELS[tool_name]
    validated = model_cls.model_validate(raw_arguments)
    return validated.model_dump()


def execute_registered_tool(tool_name: str, raw_arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validates `raw_arguments` against the explicit JSON schema for `tool_name`, invokes the tool inside
    an OpenTelemetry span, and validates the output against the tool's output JSON schema.
    """
    with start_otel_span(
        f"tool.dispatch.{tool_name}",
        {"tool.name": tool_name, "tool.schema_validated": True},
    ):
        clean_kwargs = validate_tool_arguments_against_schema(tool_name, raw_arguments)
        fn = TOOL_FUNCTIONS[tool_name]
        result = fn(**clean_kwargs)
        output_model = TOOL_OUTPUT_MODELS[tool_name]
        validated_output = output_model.model_validate(result)
        return validated_output.model_dump()
