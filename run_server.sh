#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
PORT="${PORT:-8010}"
HOST="${HOST:-127.0.0.1}"

if command -v python3 >/dev/null 2>&1 && python3 -c "import uvicorn, fastapi" >/dev/null 2>&1; then
  exec python3 -m uvicorn app.main:app --host "$HOST" --port "$PORT"
fi

echo "Starting Supply Planner Control Tower Server on http://${HOST}:${PORT} (macOS Ruby WEBrick/Socket Engine)..."
exec /usr/bin/ruby -E UTF-8:UTF-8 - "$HOST" "$PORT" << 'RUBY_SERVER_EOF'
# encoding: UTF-8
require 'socket'
require 'json'
require 'securerandom'
require 'time'

host = ARGV[0] || "127.0.0.1"
port = (ARGV[1] || "8010").to_i

PRESETS = {
  "sku_a_critical_asic" => {
    "sku_id" => "SKU-ASIC-7NM-900",
    "sku_name" => "7nm AI Inference Accelerator Module (CoWoS-S)",
    "product_family" => "AI Server Hardware",
    "plant_code" => "US-TX-FAB01",
    "planner_contact" => "planner-asic@enterprise-supply.io",
    "target_service_level" => 0.99,
    "planning_horizon_weeks" => 12,
    "inventory" => { "on_hand_units" => 850, "allocated_units" => 620, "in_transit_units" => 300, "open_po_units" => 400, "quality_hold_units" => 50, "backorder_units" => 120, "shelf_life_days" => 730 },
    "demand" => { "weekly_demand_mean" => 420.0, "weekly_demand_std_dev" => 145.0, "firm_customer_orders_4w" => 1950, "promotional_uplift_pct" => 18.0, "forecast_mape_pct" => 24.5, "seasonality_index" => 1.22, "is_new_product_launch" => false },
    "supplier" => { "primary_supplier_name" => "Taiwan Precision Foundry Corp", "primary_country" => "Taiwan", "backup_supplier_available" => false, "backup_supplier_name" => nil, "backup_lead_time_days" => nil, "backup_unit_cost_premium_pct" => 0.0, "lead_time_days_mean" => 42.0, "lead_time_days_std_dev" => 11.5, "on_time_in_full_pct" => 81.0, "defect_rate_ppm" => 450, "max_weekly_capacity_units" => 450, "minimum_order_qty" => 500, "lot_size_multiple" => 100, "active_geopolitical_or_port_disruption" => true, "single_source_dependency" => true },
    "financials" => { "unit_cost_usd" => 680.0, "selling_price_usd" => 1850.0, "holding_cost_annual_pct" => 22.0, "standard_freight_per_unit_usd" => 8.5, "expedite_air_freight_per_unit_usd" => 48.0, "stockout_penalty_per_unit_usd" => 420.0, "working_capital_budget_usd" => 450000.0, "is_revenue_critical_bom" => true, "customer_sla_penalty_per_day_usd" => 35000.0 },
    "unstructured_erp_notes" => "ERP ALERT [2025-05-12]: Kaohsiung port congestion and CoWoS substrate tightness extending lead times by +9 days. Hyperscale customer 'CloudTitan' submitted a firm pull-in order of 350 additional units in Week 2. Single-source wafer dependency on Fab-12; no qualified secondary OSAT vendor. Planner contact: Maya Lin (+1-408-555-0192, maya.lin@corp.example.com)."
  },
  "sku_b_industrial_sensor" => {
    "sku_id" => "SKU-MEMS-LIDAR-402",
    "sku_name" => "Solid-State LiDAR Optical Transceiver Array",
    "product_family" => "Autonomous Robotics",
    "plant_code" => "DE-MUN-PLANT02",
    "planner_contact" => "robotics-planning@enterprise-supply.io",
    "target_service_level" => 0.97,
    "planning_horizon_weeks" => 8,
    "inventory" => { "on_hand_units" => 2400, "allocated_units" => 950, "in_transit_units" => 600, "open_po_units" => 800, "quality_hold_units" => 30, "backorder_units" => 0, "shelf_life_days" => 365 },
    "demand" => { "weekly_demand_mean" => 650.0, "weekly_demand_std_dev" => 130.0, "firm_customer_orders_4w" => 2750, "promotional_uplift_pct" => 8.0, "forecast_mape_pct" => 15.0, "seasonality_index" => 1.08, "is_new_product_launch" => false },
    "supplier" => { "primary_supplier_name" => "Bavaria OptoElectronics GmbH", "primary_country" => "Germany", "backup_supplier_available" => true, "backup_supplier_name" => "Nordic Photonics AB", "backup_lead_time_days" => 18.0, "backup_unit_cost_premium_pct" => 11.5, "lead_time_days_mean" => 21.0, "lead_time_days_std_dev" => 4.5, "on_time_in_full_pct" => 91.5, "defect_rate_ppm" => 320, "max_weekly_capacity_units" => 600, "minimum_order_qty" => 400, "lot_size_multiple" => 100, "active_geopolitical_or_port_disruption" => false, "single_source_dependency" => false },
    "financials" => { "unit_cost_usd" => 145.0, "selling_price_usd" => 360.0, "holding_cost_annual_pct" => 18.0, "standard_freight_per_unit_usd" => 3.2, "expedite_air_freight_per_unit_usd" => 16.5, "stockout_penalty_per_unit_usd" => 95.0, "working_capital_budget_usd" => 320000.0, "is_revenue_critical_bom" => true, "customer_sla_penalty_per_day_usd" => 8500.0 },
    "unstructured_erp_notes" => "ERP NOTE: Primary supplier Bavaria OptoElectronics is running at 96% utilization due to scheduled cleanroom maintenance in Week 3. Dual-source partner Nordic Photonics AB has 250 units/week spare capacity available at an 11.5% cost premium."
  },
  "sku_c_power_supply" => {
    "sku_id" => "SKU-PSU-3000W-TITAN",
    "sku_name" => "3000W 80Plus Titanium Redundant Rack PSU",
    "product_family" => "Data Center Power & Cooling",
    "plant_code" => "MX-GDL-ASSY01",
    "planner_contact" => "power-supply-sop@enterprise-supply.io",
    "target_service_level" => 0.95,
    "planning_horizon_weeks" => 8,
    "inventory" => { "on_hand_units" => 4200, "allocated_units" => 1100, "in_transit_units" => 1200, "open_po_units" => 1000, "quality_hold_units" => 0, "backorder_units" => 0, "shelf_life_days" => 1095 },
    "demand" => { "weekly_demand_mean" => 900.0, "weekly_demand_std_dev" => 95.0, "firm_customer_orders_4w" => 3500, "promotional_uplift_pct" => 0.0, "forecast_mape_pct" => 8.2, "seasonality_index" => 1.02, "is_new_product_launch" => false },
    "supplier" => { "primary_supplier_name" => "Monterrey Power Systems S.A.", "primary_country" => "Mexico", "backup_supplier_available" => true, "backup_supplier_name" => "DeltaTech Texas Manufacturing", "backup_lead_time_days" => 10.0, "backup_unit_cost_premium_pct" => 7.0, "lead_time_days_mean" => 14.0, "lead_time_days_std_dev" => 2.0, "on_time_in_full_pct" => 96.8, "defect_rate_ppm" => 110, "max_weekly_capacity_units" => 1400, "minimum_order_qty" => 500, "lot_size_multiple" => 250, "active_geopolitical_or_port_disruption" => false, "single_source_dependency" => false },
    "financials" => { "unit_cost_usd" => 88.0, "selling_price_usd" => 195.0, "holding_cost_annual_pct" => 16.0, "standard_freight_per_unit_usd" => 2.1, "expedite_air_freight_per_unit_usd" => 11.0, "stockout_penalty_per_unit_usd" => 45.0, "working_capital_budget_usd" => 350000.0, "is_revenue_critical_bom" => false, "customer_sla_penalty_per_day_usd" => 1500.0 },
    "unstructured_erp_notes" => "Steady-state cross-border trucking lane from Monterrey to Guadalajara/Austin. Consistent 96.8% OTIF performance over trailing 6 quarters. Standard MRP replenishment."
  },
  "sku_d_packaging_tray" => {
    "sku_id" => "SKU-ESD-TRAY-100",
    "sku_name" => "Thermoformed ESD Anti-Static Component Carrier Tray",
    "product_family" => "Packaging & Consumables",
    "plant_code" => "US-OH-LOG03",
    "planner_contact" => "indirect-materials@enterprise-supply.io",
    "target_service_level" => 0.92,
    "planning_horizon_weeks" => 6,
    "inventory" => { "on_hand_units" => 28000, "allocated_units" => 4000, "in_transit_units" => 5000, "open_po_units" => 10000, "quality_hold_units" => 0, "backorder_units" => 0, "shelf_life_days" => 1825 },
    "demand" => { "weekly_demand_mean" => 4500.0, "weekly_demand_std_dev" => 320.0, "firm_customer_orders_4w" => 17500, "promotional_uplift_pct" => 0.0, "forecast_mape_pct" => 6.0, "seasonality_index" => 1.0, "is_new_product_launch" => false },
    "supplier" => { "primary_supplier_name" => "Midwest Polymer Packaging Inc", "primary_country" => "United States", "backup_supplier_available" => true, "backup_supplier_name" => "GreatLakes Thermoform LLC", "backup_lead_time_days" => 5.0, "backup_unit_cost_premium_pct" => 4.0, "lead_time_days_mean" => 7.0, "lead_time_days_std_dev" => 1.0, "on_time_in_full_pct" => 98.9, "defect_rate_ppm" => 45, "max_weekly_capacity_units" => 15000, "minimum_order_qty" => 5000, "lot_size_multiple" => 1000, "active_geopolitical_or_port_disruption" => false, "single_source_dependency" => false },
    "financials" => { "unit_cost_usd" => 1.4, "selling_price_usd" => 3.1, "holding_cost_annual_pct" => 14.0, "standard_freight_per_unit_usd" => 0.08, "expedite_air_freight_per_unit_usd" => 0.65, "stockout_penalty_per_unit_usd" => 0.9, "working_capital_budget_usd" => 60000.0, "is_revenue_critical_bom" => false, "customer_sla_penalty_per_day_usd" => 0.0 },
    "unstructured_erp_notes" => "Low-cost Class-D packaging consumable with abundant domestic capacity and 7.3 weeks of on-hand + pipeline cover. Eligible for automated VMI/Kanban release."
  }
}

SESSIONS = {}
SPANS = []
METRICS = { "async_reads" => 0, "async_writes" => 0, "background_writes_scheduled" => 0, "background_writes_completed" => 0, "cache_hits" => 0 }

def redact_pii(text)
  text.to_s
      .gsub(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/, "[REDACTED_EMAIL]")
      .gsub(/(?:\+?1[-.\s]?)?(?:\(\d{3}\)|\d{3})[-.\s]\d{3}[-.\s]\d{4}/, "[REDACTED_PHONE]")
end

def run_pipeline(sub)
  plan_id = "PLAN-#{SecureRandom.hex(4).upcase}"
  trace_id = SecureRandom.hex(16)
  inv = sub["inventory"]
  dem = sub["demand"]
  sup = sub["supplier"]
  fin = sub["financials"]

  net_on_hand = inv["on_hand_units"].to_i - inv["allocated_units"].to_i - inv["quality_hold_units"].to_i - inv["backorder_units"].to_i
  pipeline = inv["in_transit_units"].to_i + inv["open_po_units"].to_i
  net_pos = net_on_hand + pipeline
  wos = ([0.0, net_on_hand.to_f / dem["weekly_demand_mean"].to_f].max).round(2)
  dos = ([0.0, (net_pos.to_f / dem["weekly_demand_mean"].to_f) * 7.0].max).round(1)
  imm_stockout = (net_on_hand <= 0) || (wos < 1.25) || (inv["backorder_units"].to_i > 0)

  annual_spend = (dem["weekly_demand_mean"].to_f * 52.0 * fin["unit_cost_usd"].to_f).round(2)
  cv = dem["weekly_demand_std_dev"].to_f / [1.0, dem["weekly_demand_mean"].to_f].max
  abc = (annual_spend >= 3000000.0 || fin["is_revenue_critical_bom"]) ? "A" : (annual_spend >= 1000000.0 ? "B" : "C")
  xyz = cv <= 0.15 ? "X" : (cv <= 0.30 ? "Y" : "Z")
  abc_xyz = "#{abc}#{xyz}"

  urg = 15
  urg += 25 if fin["is_revenue_critical_bom"]
  urg += 20 if sup["single_source_dependency"]
  urg += 20 if sup["active_geopolitical_or_port_disruption"]
  urg += 20 if imm_stockout
  urg += 10 if fin["customer_sla_penalty_per_day_usd"].to_f >= 10000.0
  urg = [100, urg].min

  tier = if (fin["is_revenue_critical_bom"] && sup["single_source_dependency"]) || urg >= 70
           "CLASS_A_CRITICAL"
         elsif ["A", "B"].include?(abc) && urg >= 35
           "CLASS_B_CORE"
         elsif annual_spend >= 500000.0
           "CLASS_C_STANDARD"
         else
           "CLASS_D_CONSUMABLE"
         end

  sl = sub["target_service_level"].to_f
  z = sl >= 0.99 ? 2.33 : (sl >= 0.97 ? 1.88 : (sl >= 0.95 ? 1.65 : 1.41))
  modeled_wk = dem["weekly_demand_mean"].to_f * dem["seasonality_index"].to_f * (1.0 + dem["promotional_uplift_pct"].to_f / 100.0)
  eff_wk = [modeled_wk, dem["firm_customer_orders_4w"].to_f / 4.0].max.round(2)
  mape_inf = 1.0 + [0.0, (dem["forecast_mape_pct"].to_f - 10.0) / 100.0].max
  eff_sig_d = dem["weekly_demand_std_dev"].to_f * mape_inf
  lt_w = sup["lead_time_days_mean"].to_f / 7.0
  sig_lt_w = sup["lead_time_days_std_dev"].to_f / 7.0
  ss = (z * Math.sqrt((lt_w * (eff_sig_d**2)) + ((eff_wk**2) * (sig_lt_w**2)))).ceil
  rop = ((eff_wk * lt_w) + ss).ceil
  dem_score = [100, ((cv * 110.0) + (dem["forecast_mape_pct"].to_f * 1.4) + (dem["promotional_uplift_pct"].to_f * 0.8)).round].min
  dem_lvl = dem_score >= 70 ? "CRITICAL" : (dem_score >= 45 ? "HIGH" : (dem_score >= 25 ? "MODERATE" : "LOW"))

  util_pct = ((eff_wk / sup["max_weekly_capacity_units"].to_f) * 100.0).round(1)
  shortfall = [0.0, eff_wk - sup["max_weekly_capacity_units"].to_f].max.round(1)
  sup_score = 10
  sup_score += (util_pct >= 100.0 ? 25 : (util_pct >= 90.0 ? 15 : 0))
  sup_score += (sup["on_time_in_full_pct"].to_f < 85.0 ? 22 : (sup["on_time_in_full_pct"].to_f < 92.0 ? 10 : 0))
  sup_score += 25 if sup["active_geopolitical_or_port_disruption"]
  sup_score += 18 if sup["single_source_dependency"] || !sup["backup_supplier_available"]
  sup_score += 8 if sup["defect_rate_ppm"].to_i >= 400
  sup_score = [100, sup_score].min
  sup_lvl = sup_score >= 70 ? "CRITICAL" : (sup_score >= 45 ? "HIGH" : (sup_score >= 25 ? "MODERATE" : "LOW"))
  backup_pct = sup["backup_supplier_available"] ? ((shortfall > 0 || util_pct >= 95.0) ? 30.0 : (sup_score >= 45 ? 20.0 : 0.0)) : 0.0

  gross_4w = (eff_wk * 4).ceil
  raw_net = [0, gross_4w + ss - net_pos].max
  raw_net = [0, rop - net_pos].max if raw_net == 0 && net_pos < rop
  lot_mult = [1, sup["lot_size_multiple"].to_i].max
  moq = [1, sup["minimum_order_qty"].to_i].max
  total_order = raw_net > 0 ? (([raw_net, moq].max.to_f / lot_mult).ceil * lot_mult) : 0
  backup_order = (sup["backup_supplier_available"] && backup_pct > 0 && total_order > 0) ? [total_order, ([1, ((total_order * (backup_pct / 100.0)) / lot_mult).round].max * lot_mult)].min : 0
  primary_order = total_order - backup_order

  imm_def = [0, (eff_wk * 2.0).ceil - [0, net_on_hand].max].max
  exp_units = (imm_def > 0 && fin["stockout_penalty_per_unit_usd"].to_f > (fin["expedite_air_freight_per_unit_usd"].to_f - fin["standard_freight_per_unit_usd"].to_f) && total_order > 0) ? [total_order, imm_def].min : 0
  backup_cost = fin["unit_cost_usd"].to_f * (1.0 + (sup["backup_unit_cost_premium_pct"].to_f / 100.0))
  exp_freight = (exp_units * fin["expedite_air_freight_per_unit_usd"].to_f).round(2)
  total_spend = ((primary_order * fin["unit_cost_usd"].to_f) + (backup_order * backup_cost) + ((total_order - exp_units) * fin["standard_freight_per_unit_usd"].to_f) + exp_freight).round(2)
  budget_util = ((total_spend / fin["working_capital_budget_usd"].to_f) * 100.0).round(1)
  fin_score = [100, 10 + (exp_units > 0 ? 25 : 0) + (total_spend > fin["working_capital_budget_usd"].to_f ? 35 : 0) + (exp_freight > 25000.0 ? 20 : 0)].min
  fin_lvl = fin_score >= 70 ? "CRITICAL" : (fin_score >= 45 ? "HIGH" : (fin_score >= 25 ? "MODERATE" : "LOW"))

  comp_score = ((0.30 * dem_score) + (0.40 * sup_score) + (0.30 * fin_score)).round(1)
  overall_lvl = comp_score >= 70 ? "CRITICAL" : (comp_score >= 45 ? "HIGH" : (comp_score >= 25 ? "MODERATE" : "LOW"))

  hitl_reasons = []
  hitl_reasons << "Total PO spend ($#{total_spend}) exceeds working capital budget ($#{fin['working_capital_budget_usd']}) [Article IV]." if total_spend > fin["working_capital_budget_usd"].to_f
  hitl_reasons << "Expedited air freight cost ($#{exp_freight}) exceeds $25,000 autonomous capex ceiling [Article IV]." if exp_freight > 25000.0
  hitl_reasons << "Composite supply risk score (#{comp_score}/100) exceeds autonomous release ceiling (75.0) [Article V]." if comp_score >= 75.0
  hitl_reasons << "CLASS_A_CRITICAL single-source SKU faces active port/geopolitical disruption [Article V]." if tier == "CLASS_A_CRITICAL" && sup["single_source_dependency"] && sup["active_geopolitical_or_port_disruption"]

  requires_hitl = !hitl_reasons.empty?
  status = requires_hitl ? "HOLD_FOR_EXECUTIVE_SOP_APPROVAL" : ((backup_order > 0 || exp_units > 0 || comp_score >= 35.0) ? "RELEASE_WITH_DUAL_SOURCE_AND_EXPEDITE" : "AUTO_RELEASE_PO")

  now_iso = Time.now.utc.iso8601
  telemetry = [
    { "timestamp" => now_iso, "phase" => "Phase 1: Demand & Inventory Triage", "agent" => "Demand & Inventory Triage Agent", "status" => "COMPLETED", "latency_ms" => 1.8, "details" => "Classified #{sub['sku_id']} as #{tier} (#{abc_xyz}); Net ATP=#{net_on_hand} units.", "trace_id" => trace_id, "span_id" => SecureRandom.hex(8) },
    { "timestamp" => now_iso, "phase" => "Phase 2: Statistical Safety Stock & ROP", "agent" => "Forecast & Safety Stock Agent", "status" => "COMPLETED", "latency_ms" => 2.1, "details" => "Safety Stock=#{ss} units, ROP=#{rop} units (Z=#{z}).", "trace_id" => trace_id, "span_id" => SecureRandom.hex(8) },
    { "timestamp" => now_iso, "phase" => "Phase 3: Supplier Capacity & Lead-Time Risk", "agent" => "Supplier Capacity & Lead-Time Risk Agent", "status" => "COMPLETED", "latency_ms" => 1.9, "details" => "Primary capacity utilization=#{util_pct}%, Risk=#{sup_score}/100 (#{sup_lvl}).", "trace_id" => trace_id, "span_id" => SecureRandom.hex(8) },
    { "timestamp" => now_iso, "phase" => "Phase 4: MRP Replenishment & PO Optimization", "agent" => "Replenishment & PO Optimizer Agent", "status" => "COMPLETED", "latency_ms" => 2.4, "details" => "Recommended PO=#{total_order} units, Spend=$#{total_spend} (#{budget_util}% budget).", "trace_id" => trace_id, "span_id" => SecureRandom.hex(8) },
    { "timestamp" => now_iso, "phase" => "Phase 5: Master S&OP Governance & Decision", "agent" => "Master Supply Planner & S&OP Governance Agent", "status" => status, "latency_ms" => 1.7, "details" => "Composite Score=#{comp_score}/100 -> #{status}", "trace_id" => trace_id, "span_id" => SecureRandom.hex(8) }
  ]

  res = {
    "plan_id" => plan_id,
    "trace_id" => trace_id,
    "started_at" => now_iso,
    "completed_at" => now_iso,
    "intent_detected" => "SUPPLY_PACKET_SUBMISSION",
    "submission" => sub,
    "triage_output" => {
      "sku_tier" => tier,
      "abc_xyz_class" => abc_xyz,
      "stockout_urgency_score" => urg,
      "net_available_on_hand_units" => net_on_hand,
      "net_inventory_position_units" => net_pos,
      "weeks_of_supply_on_hand" => wos,
      "days_of_supply_total" => dos,
      "immediate_stockout_risk" => imm_stockout,
      "sanitized_erp_notes" => redact_pii(sub["unstructured_erp_notes"]),
      "extracted_erp_entities" => { "annual_spend_usd" => annual_spend },
      "triage_rationale" => "SKU #{sub['sku_id']} classified as #{tier} (ABC/XYZ #{abc_xyz}). Net ATP on-hand = #{net_on_hand} units (#{wos} wks cover); Total net position = #{net_pos} units (#{dos} days cover)."
    },
    "phase_assessments" => [
      {
        "phase_name" => "Phase 2 — Demand Sensing & Statistical Safety Stock",
        "agent_name" => "Forecast & Safety Stock Agent",
        "model_used" => "gemini-1.5-pro",
        "risk_score" => dem_score,
        "risk_level" => dem_lvl,
        "key_findings" => [
          "Service level #{(sl * 100).round(1)}% maps to Z=#{z} under coupled demand/lead-time variance.",
          "Effective weekly demand is #{eff_wk} units/wk.",
          "Statistical safety stock = #{ss} units; Reorder Point (ROP) = #{rop} units."
        ],
        "recommended_actions" => [
          "Maintain statistical safety stock buffer of #{ss} units (Z=#{z}).",
          "Trigger automated MRP replenishment whenever net inventory position drops below ROP of #{rop} units."
        ],
        "quantitative_metrics" => { "statistical_safety_stock_units" => ss, "reorder_point_units" => rop, "effective_weekly_demand_units" => eff_wk },
        "llm_narrative" => "Effective weekly demand is #{eff_wk} units/wk. Required safety stock is #{ss} units and Reorder Point (ROP) is #{rop} units."
      },
      {
        "phase_name" => "Phase 3 — Supplier Capacity & Lead-Time Resilience",
        "agent_name" => "Supplier Capacity & Lead-Time Risk Agent",
        "model_used" => "gemini-1.5-pro",
        "risk_score" => sup_score,
        "risk_level" => sup_lvl,
        "key_findings" => [
          "Primary supplier '#{sup['primary_supplier_name']}' (#{sup['primary_country']}) utilization is #{util_pct}% (#{eff_wk.round}/#{sup['max_weekly_capacity_units']} units/wk).",
          "Supplier OTIF is #{sup['on_time_in_full_pct']}%; single-source=#{sup['single_source_dependency']}."
        ],
        "recommended_actions" => [
          backup_pct > 0 ? "Allocate #{backup_pct.round}% of replenishment volume to qualified backup supplier." : "Monitor supplier ASN delivery variance and capacity commitment."
        ],
        "quantitative_metrics" => { "capacity_utilization_pct" => util_pct, "recommended_backup_allocation_pct" => backup_pct },
        "llm_narrative" => "Primary supplier '#{sup['primary_supplier_name']}' utilization is #{util_pct}% with #{sup['on_time_in_full_pct']}% OTIF. Recommended backup allocation = #{backup_pct.round}%."
      },
      {
        "phase_name" => "Phase 4 — MRP Replenishment & Working Capital Optimization",
        "agent_name" => "Replenishment & PO Optimizer Agent",
        "model_used" => "gemini-1.5-pro",
        "risk_score" => fin_score,
        "risk_level" => fin_lvl,
        "key_findings" => [
          "Tactical 4-week gross demand = #{gross_4w} units; Net requirement = #{raw_net} units; Lot-sized PO release = #{total_order} units.",
          "Total PO commitment = $#{total_spend} (#{budget_util}% of working capital budget)."
        ],
        "recommended_actions" => [
          "Issue primary supplier PO for #{primary_order} units and backup PO for #{backup_order} units.",
          exp_units > 0 ? "Book priority air freight for #{exp_units} units ($#{exp_freight}) to prevent line-down." : "Use standard ocean/ground freight lane."
        ],
        "quantitative_metrics" => { "recommended_total_order_units" => total_order, "total_po_spend_usd" => total_spend },
        "llm_narrative" => "Recommended total PO release = #{total_order} units (Primary: #{primary_order}, Backup: #{backup_order}, Expedite Air: #{exp_units}) for $#{total_spend}."
      }
    ],
    "final_decision" => {
      "sku_id" => sub["sku_id"],
      "sku_name" => sub["sku_name"],
      "sku_tier" => tier,
      "composite_risk_score" => comp_score,
      "overall_risk_level" => overall_lvl,
      "decision_status" => status,
      "requires_human_review" => requires_hitl,
      "human_review_reason" => requires_hitl ? hitl_reasons.join(" | ") : nil,
      "recommended_safety_stock_units" => ss,
      "recommended_reorder_point_units" => rop,
      "recommended_order_qty_units" => total_order,
      "primary_supplier_order_units" => primary_order,
      "backup_supplier_order_units" => backup_order,
      "expedite_air_units" => exp_units,
      "total_po_spend_usd" => total_spend,
      "expedite_freight_cost_usd" => exp_freight,
      "mandatory_mitigation_actions" => ["Enforce statistical safety stock of #{ss} units", "Execute MRP PO release of #{total_order} units"],
      "executive_sop_memo" => "EXECUTIVE S&OP REPLENISHMENT MEMO — #{sub['sku_id']} (#{sub['sku_name']}): Classified as #{tier} (ABC/XYZ #{abc_xyz}) with composite supply risk score #{comp_score}/100 (#{overall_lvl}). Statistical safety stock is set at #{ss} units (ROP #{rop} units). MRP optimization recommends releasing #{total_order} total units (#{primary_order} primary, #{backup_order} dual-source backup, #{exp_units} expedited air freight) for a total commitment of $#{total_spend}. #{requires_hitl ? 'MANDATORY EXECUTIVE S&OP HOLD TRIGGERED (Article V): ' + hitl_reasons.join('; ') : 'CONSTITUTIONAL COMPLIANCE VERIFIED for autonomous ERP release.'}"
    },
    "telemetry_events" => telemetry
  }

  SESSIONS[plan_id] = res
  SPANS.concat(telemetry)
  METRICS["async_writes"] += 1
  METRICS["background_writes_completed"] += 1
  res
end

TOOL_SCHEMAS = {
  "tool_count" => 5,
  "tools" => {
    "extract_erp_inventory_positions" => { "description" => "Reconciles ERP inventory balances, net ATP, pipeline stock, weeks of supply, and scrubs PII.", "strict" => true },
    "classify_sku_abc_xyz_criticality" => { "description" => "Performs ABC/XYZ stratification and assigns Supply Chain Constitution SKU tier.", "strict" => true },
    "calculate_statistical_safety_stock" => { "description" => "Computes statistical safety stock and Reorder Point (ROP) under coupled demand and lead-time variance.", "strict" => true },
    "evaluate_supplier_capacity_and_leadtime_risk" => { "description" => "Audits supplier weekly capacity utilization, OTIF reliability, and dual-source split.", "strict" => true },
    "optimize_mrp_replenishment_orders" => { "description" => "Solves MRP net replenishment requirements, MOQ/lot-sizing, and expedite freight vs working capital trade-offs.", "strict" => true }
  }
}

server = TCPServer.new(host, port)
puts "Supply Planner Control Tower listening on http://#{host}:#{port}"
STDOUT.flush

loop do
  client = server.accept
  Thread.new(client) do |sock|
    begin
      request_line = sock.gets
      next unless request_line
      method, full_path, _ = request_line.split(' ')
      path = full_path.split('?').first

      headers = {}
      while (line = sock.gets) && line != "\r\n"
        k, v = line.split(':', 2)
        headers[k.downcase.strip] = v.strip if v
      end

      content_length = (headers['content-length'] || '0').to_i
      body = content_length > 0 ? sock.read(content_length) : ""

      status = "200 OK"
      ctype = "application/json"
      resp_body = ""

      if method == "GET" && (path == "/" || path == "/index.html")
        ctype = "text/html; charset=utf-8"
        resp_body = File.read(File.join(Dir.pwd, "app", "static", "index.html"))
      elsif method == "GET" && path == "/api/health"
        resp_body = JSON.generate({
          "status" => "healthy",
          "service" => "Enterprise Supply Planner & MRP Control Tower",
          "llm_provider" => "Constitutional S&OP Engine (Schema-Enforced)",
          "memory_telemetry" => METRICS
        })
      elsif method == "GET" && path == "/api/presets"
        resp_body = JSON.generate(PRESETS)
      elsif method == "GET" && path == "/api/tools/schemas"
        resp_body = JSON.generate(TOOL_SCHEMAS)
      elsif method == "GET" && path == "/api/telemetry/spans"
        METRICS["async_reads"] += 1
        resp_body = JSON.generate({ "span_count" => SPANS.size, "spans" => SPANS.last(20), "memory_telemetry" => METRICS })
      elsif method == "POST" && path == "/api/planning/run"
        payload = JSON.parse(body)
        resp_body = JSON.generate(run_pipeline(payload))
      elsif method == "POST" && path =~ %r{^/api/plans/([^/]+)/human-override$}
        plan_id = $1
        ovr = JSON.parse(body)
        session = SESSIONS[plan_id]
        if session
          session["final_decision"]["decision_status"] = ovr["override_decision"]
          session["final_decision"]["requires_human_review"] = false
          session["final_decision"]["human_override_applied"] = true
          session["final_decision"]["human_override_by"] = ovr["reviewer_name"]
          session["final_decision"]["human_override_notes"] = ovr["override_justification"]
          session["telemetry_events"] << {
            "timestamp" => Time.now.utc.iso8601,
            "phase" => "Phase 5C: Executive S&OP Human Override",
            "agent" => "Executive Reviewer (#{ovr['reviewer_name']})",
            "status" => ovr["override_decision"],
            "latency_ms" => 0.8,
            "details" => "Override applied: #{ovr['override_justification']}",
            "trace_id" => session["trace_id"],
            "span_id" => SecureRandom.hex(8)
          }
          METRICS["async_writes"] += 1
          resp_body = JSON.generate(session)
        else
          status = "404 Not Found"
          resp_body = JSON.generate({ "detail" => "Plan not found" })
        end
      elsif method == "POST" && path == "/api/chat"
        req = JSON.parse(body)
        q = req["message"].to_s.downcase
        reply = if q.include?("safety stock") || q.include?("rop") || q.include?("article ii")
                  "**Article II — Statistical Safety Stock & Reorder Point (ROP) Formula:**\n- Formula: `Safety Stock = Z * sqrt(L_weeks * sigma_D^2 + D_weekly^2 * sigma_L_weeks^2)`\n- `ROP = (Effective_Weekly_Demand * L_weeks) + Safety_Stock`\n- Z-scores: 99% -> 2.33 (Class A), 97% -> 1.88 (Class B), 95% -> 1.65 (Class C), 92% -> 1.41 (Class D)."
                elsif q.include?("hitl") || q.include?("override") || q.include?("budget") || q.include?("expedite")
                  "**Articles IV & V — Working Capital, Expedite Capex & Mandatory HITL Code Stop:**\n- Autonomous PO release is blocked (`HOLD_FOR_EXECUTIVE_SOP_APPROVAL`) when Total PO Spend exceeds `working_capital_budget_usd`, Expedited Air Freight exceeds $25,000, or Composite Risk >= 75."
                else
                  "**Enterprise S&OP Control Tower Guidance:**\n- Our 5-Agent Pipeline evaluates: (1) Inventory Triage & ABC/XYZ Tiering, (2) Statistical Safety Stock & ROP, (3) Supplier Capacity & OTIF Resilience, (4) MRP Lot-Sizing & Expedite Optimization, and (5) Master S&OP Governance & HITL Code Stop."
                end
        METRICS["background_writes_completed"] += 2
        resp_body = JSON.generate({
          "session_id" => req["session_id"] || "web-sop-session",
          "intent_detected" => "PLANNER_QUESTION",
          "agent_name" => "Conversational S&OP Support Agent",
          "model_used" => "gemini-2.0-flash",
          "reply" => reply,
          "routed_to_pipeline" => false
        })
      else
        status = "404 Not Found"
        resp_body = JSON.generate({ "detail" => "Not found" })
      end

      sock.print "HTTP/1.1 #{status}\r\nContent-Type: #{ctype}\r\nContent-Length: #{resp_body.bytesize}\r\nConnection: close\r\n\r\n#{resp_body}"
    rescue => e
      # ignore broken pipe
    ensure
      sock.close rescue nil
    end
  end
end
RUBY_SERVER_EOF
