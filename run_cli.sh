#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if command -v python3 >/dev/null 2>&1 && python3 -c "import pydantic" >/dev/null 2>&1; then
  exec python3 cli.py "$@"
fi

# Fallback to macOS built-in Ruby runtime when Xcode Command Line Tools / Python 3 are not installed
exec /usr/bin/ruby -E UTF-8:UTF-8 - "$@" << 'RUBY_EOF'
# encoding: UTF-8
require 'json'
require 'securerandom'
require 'time'

PRESETS = {
  "sku_a_critical_asic" => {
    sku_id: "SKU-ASIC-7NM-900",
    sku_name: "7nm AI Inference Accelerator Module (CoWoS-S)",
    product_family: "AI Server Hardware",
    plant_code: "US-TX-FAB01",
    target_service_level: 0.99,
    planning_horizon_weeks: 12,
    inventory: { on_hand_units: 850, allocated_units: 620, in_transit_units: 300, open_po_units: 400, quality_hold_units: 50, backorder_units: 120 },
    demand: { weekly_demand_mean: 420.0, weekly_demand_std_dev: 145.0, firm_customer_orders_4w: 1950, promotional_uplift_pct: 18.0, forecast_mape_pct: 24.5, seasonality_index: 1.22 },
    supplier: { primary_supplier_name: "Taiwan Precision Foundry Corp", primary_country: "Taiwan", backup_supplier_available: false, backup_supplier_name: nil, backup_unit_cost_premium_pct: 0.0, lead_time_days_mean: 42.0, lead_time_days_std_dev: 11.5, on_time_in_full_pct: 81.0, defect_rate_ppm: 450, max_weekly_capacity_units: 450, minimum_order_qty: 500, lot_size_multiple: 100, active_geopolitical_or_port_disruption: true, single_source_dependency: true },
    financials: { unit_cost_usd: 680.0, selling_price_usd: 1850.0, standard_freight_per_unit_usd: 8.5, expedite_air_freight_per_unit_usd: 48.0, stockout_penalty_per_unit_usd: 420.0, working_capital_budget_usd: 450000.0, is_revenue_critical_bom: true, customer_sla_penalty_per_day_usd: 35000.0 },
    unstructured_erp_notes: "ERP ALERT [2025-05-12]: Kaohsiung port congestion and CoWoS substrate tightness extending lead times by +9 days. Hyperscale customer 'CloudTitan' submitted a firm pull-in order of 350 additional units in Week 2. Single-source wafer dependency on Fab-12; no qualified secondary OSAT vendor. Planner contact: Maya Lin (+1-408-555-0192, maya.lin@corp.example.com)."
  },
  "sku_b_industrial_sensor" => {
    sku_id: "SKU-MEMS-LIDAR-402",
    sku_name: "Solid-State LiDAR Optical Transceiver Array",
    product_family: "Autonomous Robotics",
    plant_code: "DE-MUN-PLANT02",
    target_service_level: 0.97,
    planning_horizon_weeks: 8,
    inventory: { on_hand_units: 2400, allocated_units: 950, in_transit_units: 600, open_po_units: 800, quality_hold_units: 30, backorder_units: 0 },
    demand: { weekly_demand_mean: 650.0, weekly_demand_std_dev: 130.0, firm_customer_orders_4w: 2750, promotional_uplift_pct: 8.0, forecast_mape_pct: 15.0, seasonality_index: 1.08 },
    supplier: { primary_supplier_name: "Bavaria OptoElectronics GmbH", primary_country: "Germany", backup_supplier_available: true, backup_supplier_name: "Nordic Photonics AB", backup_unit_cost_premium_pct: 11.5, lead_time_days_mean: 21.0, lead_time_days_std_dev: 4.5, on_time_in_full_pct: 91.5, defect_rate_ppm: 320, max_weekly_capacity_units: 600, minimum_order_qty: 400, lot_size_multiple: 100, active_geopolitical_or_port_disruption: false, single_source_dependency: false },
    financials: { unit_cost_usd: 145.0, selling_price_usd: 360.0, standard_freight_per_unit_usd: 3.2, expedite_air_freight_per_unit_usd: 16.5, stockout_penalty_per_unit_usd: 95.0, working_capital_budget_usd: 320000.0, is_revenue_critical_bom: true, customer_sla_penalty_per_day_usd: 8500.0 },
    unstructured_erp_notes: "ERP NOTE: Primary supplier Bavaria OptoElectronics is running at 96% utilization due to scheduled cleanroom maintenance in Week 3. Dual-source partner Nordic Photonics AB has 250 units/week spare capacity available at an 11.5% cost premium."
  },
  "sku_c_power_supply" => {
    sku_id: "SKU-PSU-3000W-TITAN",
    sku_name: "3000W 80Plus Titanium Redundant Rack PSU",
    product_family: "Data Center Power & Cooling",
    plant_code: "MX-GDL-ASSY01",
    target_service_level: 0.95,
    planning_horizon_weeks: 8,
    inventory: { on_hand_units: 4200, allocated_units: 1100, in_transit_units: 1200, open_po_units: 1000, quality_hold_units: 0, backorder_units: 0 },
    demand: { weekly_demand_mean: 900.0, weekly_demand_std_dev: 95.0, firm_customer_orders_4w: 3500, promotional_uplift_pct: 0.0, forecast_mape_pct: 8.2, seasonality_index: 1.02 },
    supplier: { primary_supplier_name: "Monterrey Power Systems S.A.", primary_country: "Mexico", backup_supplier_available: true, backup_supplier_name: "DeltaTech Texas Manufacturing", backup_unit_cost_premium_pct: 7.0, lead_time_days_mean: 14.0, lead_time_days_std_dev: 2.0, on_time_in_full_pct: 96.8, defect_rate_ppm: 110, max_weekly_capacity_units: 1400, minimum_order_qty: 500, lot_size_multiple: 250, active_geopolitical_or_port_disruption: false, single_source_dependency: false },
    financials: { unit_cost_usd: 88.0, selling_price_usd: 195.0, standard_freight_per_unit_usd: 2.1, expedite_air_freight_per_unit_usd: 11.0, stockout_penalty_per_unit_usd: 45.0, working_capital_budget_usd: 350000.0, is_revenue_critical_bom: false, customer_sla_penalty_per_day_usd: 1500.0 },
    unstructured_erp_notes: "Steady-state cross-border trucking lane from Monterrey to Guadalajara/Austin. Consistent 96.8% OTIF performance over trailing 6 quarters. Standard MRP replenishment."
  },
  "sku_d_packaging_tray" => {
    sku_id: "SKU-ESD-TRAY-100",
    sku_name: "Thermoformed ESD Anti-Static Component Carrier Tray",
    product_family: "Packaging & Consumables",
    plant_code: "US-OH-LOG03",
    target_service_level: 0.92,
    planning_horizon_weeks: 6,
    inventory: { on_hand_units: 28000, allocated_units: 4000, in_transit_units: 5000, open_po_units: 10000, quality_hold_units: 0, backorder_units: 0 },
    demand: { weekly_demand_mean: 4500.0, weekly_demand_std_dev: 320.0, firm_customer_orders_4w: 17500, promotional_uplift_pct: 0.0, forecast_mape_pct: 6.0, seasonality_index: 1.0 },
    supplier: { primary_supplier_name: "Midwest Polymer Packaging Inc", primary_country: "United States", backup_supplier_available: true, backup_supplier_name: "GreatLakes Thermoform LLC", backup_unit_cost_premium_pct: 4.0, lead_time_days_mean: 7.0, lead_time_days_std_dev: 1.0, on_time_in_full_pct: 98.9, defect_rate_ppm: 45, max_weekly_capacity_units: 15000, minimum_order_qty: 5000, lot_size_multiple: 1000, active_geopolitical_or_port_disruption: false, single_source_dependency: false },
    financials: { unit_cost_usd: 1.4, selling_price_usd: 3.1, standard_freight_per_unit_usd: 0.08, expedite_air_freight_per_unit_usd: 0.65, stockout_penalty_per_unit_usd: 0.9, working_capital_budget_usd: 60000.0, is_revenue_critical_bom: false, customer_sla_penalty_per_day_usd: 0.0 },
    unstructured_erp_notes: "Low-cost Class-D packaging consumable with abundant domestic capacity and 7.3 weeks of on-hand + pipeline cover. Eligible for automated VMI/Kanban release."
  }
}

def redact_pii(text)
  text.to_s
      .gsub(/[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/, "[REDACTED_EMAIL]")
      .gsub(/(?:\+?1[-.\s]?)?(?:\(\d{3}\)|\d{3})[-.\s]\d{3}[-.\s]\d{4}/, "[REDACTED_PHONE]")
end

def evaluate_sku(sub)
  inv = sub[:inventory]
  dem = sub[:demand]
  sup = sub[:supplier]
  fin = sub[:financials]

  net_on_hand = inv[:on_hand_units] - inv[:allocated_units] - inv[:quality_hold_units] - inv[:backorder_units]
  pipeline = inv[:in_transit_units] + inv[:open_po_units]
  net_pos = net_on_hand + pipeline
  wos = ([0.0, net_on_hand.to_f / dem[:weekly_demand_mean]].max).round(2)
  dos = ([0.0, (net_pos.to_f / dem[:weekly_demand_mean]) * 7.0].max).round(1)
  imm_stockout = (net_on_hand <= 0) || (wos < 1.25) || (inv[:backorder_units] > 0)

  annual_spend = (dem[:weekly_demand_mean] * 52.0 * fin[:unit_cost_usd]).round(2)
  cv = dem[:weekly_demand_std_dev] / [1.0, dem[:weekly_demand_mean]].max
  abc = (annual_spend >= 3000000.0 || fin[:is_revenue_critical_bom]) ? "A" : (annual_spend >= 1000000.0 ? "B" : "C")
  xyz = cv <= 0.15 ? "X" : (cv <= 0.30 ? "Y" : "Z")
  abc_xyz = "#{abc}#{xyz}"

  urg = 15
  urg += 25 if fin[:is_revenue_critical_bom]
  urg += 20 if sup[:single_source_dependency]
  urg += 20 if sup[:active_geopolitical_or_port_disruption]
  urg += 20 if imm_stockout
  urg += 10 if fin[:customer_sla_penalty_per_day_usd] >= 10000.0
  urg = [100, urg].min

  tier = if (fin[:is_revenue_critical_bom] && sup[:single_source_dependency]) || urg >= 70
           "CLASS_A_CRITICAL"
         elsif ["A", "B"].include?(abc) && urg >= 35
           "CLASS_B_CORE"
         elsif annual_spend >= 500000.0
           "CLASS_C_STANDARD"
         else
           "CLASS_D_CONSUMABLE"
         end

  sl = sub[:target_service_level]
  z = sl >= 0.99 ? 2.33 : (sl >= 0.97 ? 1.88 : (sl >= 0.95 ? 1.65 : 1.41))
  modeled_wk = dem[:weekly_demand_mean] * dem[:seasonality_index] * (1.0 + dem[:promotional_uplift_pct] / 100.0)
  eff_wk = [modeled_wk, dem[:firm_customer_orders_4w] / 4.0].max.round(2)
  mape_inf = 1.0 + [0.0, (dem[:forecast_mape_pct] - 10.0) / 100.0].max
  eff_sig_d = dem[:weekly_demand_std_dev] * mape_inf
  lt_w = sup[:lead_time_days_mean] / 7.0
  sig_lt_w = sup[:lead_time_days_std_dev] / 7.0
  ss = (z * Math.sqrt((lt_w * (eff_sig_d**2)) + ((eff_wk**2) * (sig_lt_w**2)))).ceil
  rop = ((eff_wk * lt_w) + ss).ceil
  dem_score = [100, ((cv * 110.0) + (dem[:forecast_mape_pct] * 1.4) + (dem[:promotional_uplift_pct] * 0.8)).round].min

  util_pct = ((eff_wk / sup[:max_weekly_capacity_units]) * 100.0).round(1)
  shortfall = [0.0, eff_wk - sup[:max_weekly_capacity_units]].max.round(1)
  sup_score = 10
  sup_score += (util_pct >= 100.0 ? 25 : (util_pct >= 90.0 ? 15 : 0))
  sup_score += (sup[:on_time_in_full_pct] < 85.0 ? 22 : (sup[:on_time_in_full_pct] < 92.0 ? 10 : 0))
  sup_score += 25 if sup[:active_geopolitical_or_port_disruption]
  sup_score += 18 if sup[:single_source_dependency] || !sup[:backup_supplier_available]
  sup_score += 8 if sup[:defect_rate_ppm] >= 400
  sup_score = [100, sup_score].min
  backup_pct = sup[:backup_supplier_available] ? ((shortfall > 0 || util_pct >= 95.0) ? 30.0 : (sup_score >= 45 ? 20.0 : 0.0)) : 0.0

  gross_4w = (eff_wk * 4).ceil
  raw_net = [0, gross_4w + ss - net_pos].max
  raw_net = [0, rop - net_pos].max if raw_net == 0 && net_pos < rop
  total_order = raw_net > 0 ? (([raw_net, sup[:minimum_order_qty]].max.to_f / sup[:lot_size_multiple]).ceil * sup[:lot_size_multiple]) : 0
  backup_order = (sup[:backup_supplier_available] && backup_pct > 0 && total_order > 0) ? [total_order, ([1, ((total_order * (backup_pct / 100.0)) / sup[:lot_size_multiple]).round].max * sup[:lot_size_multiple])].min : 0
  primary_order = total_order - backup_order

  imm_def = [0, (eff_wk * 2.0).ceil - [0, net_on_hand].max].max
  exp_units = (imm_def > 0 && fin[:stockout_penalty_per_unit_usd] > (fin[:expedite_air_freight_per_unit_usd] - fin[:standard_freight_per_unit_usd]) && total_order > 0) ? [total_order, imm_def].min : 0
  backup_cost = fin[:unit_cost_usd] * (1.0 + (sup[:backup_unit_cost_premium_pct] / 100.0))
  exp_freight = (exp_units * fin[:expedite_air_freight_per_unit_usd]).round(2)
  total_spend = ((primary_order * fin[:unit_cost_usd]) + (backup_order * backup_cost) + ((total_order - exp_units) * fin[:standard_freight_per_unit_usd]) + exp_freight).round(2)
  fin_score = 10 + (exp_units > 0 ? 25 : 0) + (total_spend > fin[:working_capital_budget_usd] ? 35 : 0) + (exp_freight > 25000.0 ? 20 : 0)
  fin_score = [100, fin_score].min

  comp_score = ((0.30 * dem_score) + (0.40 * sup_score) + (0.30 * fin_score)).round(1)
  overall_lvl = comp_score >= 70 ? "CRITICAL" : (comp_score >= 45 ? "HIGH" : (comp_score >= 25 ? "MODERATE" : "LOW"))

  hitl_reasons = []
  hitl_reasons << "Total PO spend ($#{total_spend}) exceeds working capital budget ($#{fin[:working_capital_budget_usd]}) [Article IV]" if total_spend > fin[:working_capital_budget_usd]
  hitl_reasons << "Expedited air freight ($#{exp_freight}) exceeds $25,000 autonomous capex ceiling [Article IV]" if exp_freight > 25000.0
  hitl_reasons << "Composite supply risk score (#{comp_score}/100) exceeds autonomous release ceiling (75.0) [Article V]" if comp_score >= 75.0
  hitl_reasons << "CLASS_A_CRITICAL single-source SKU faces active port/geopolitical disruption [Article V]" if tier == "CLASS_A_CRITICAL" && sup[:single_source_dependency] && sup[:active_geopolitical_or_port_disruption]

  requires_hitl = !hitl_reasons.empty?
  status = requires_hitl ? "HOLD_FOR_EXECUTIVE_SOP_APPROVAL" : ((backup_order > 0 || exp_units > 0 || comp_score >= 35.0) ? "RELEASE_WITH_DUAL_SOURCE_AND_EXPEDITE" : "AUTO_RELEASE_PO")

  {
    plan_id: "PLAN-#{SecureRandom.hex(4).upcase}",
    trace_id: SecureRandom.hex(16),
    sku_id: sub[:sku_id],
    sku_name: sub[:sku_name],
    plant_code: sub[:plant_code],
    sku_tier: tier,
    abc_xyz_class: abc_xyz,
    urgency_score: urg,
    net_on_hand: net_on_hand,
    wos: wos,
    safety_stock: ss,
    rop: rop,
    total_order: total_order,
    primary_order: primary_order,
    backup_order: backup_order,
    expedite_units: exp_units,
    total_spend: total_spend,
    expedite_freight: exp_freight,
    composite_score: comp_score,
    overall_level: overall_lvl,
    decision_status: status,
    requires_hitl: requires_hitl,
    hitl_reason: hitl_reasons.join(" | "),
    sanitized_notes: redact_pii(sub[:unstructured_erp_notes])
  }
end

keys = ARGV.include?("--all") ? PRESETS.keys : ["sku_a_critical_asic"]
keys.each do |k|
  r = evaluate_sku(PRESETS[k])
  puts "=" * 88
  puts "SUPPLY PLAN ID   : #{r[:plan_id]}  |  W3C TRACE ID: #{r[:trace_id]}"
  puts "SKU              : #{r[:sku_id]} — #{r[:sku_name]} (#{r[:plant_code]})"
  puts "ABC/XYZ TIER     : #{r[:sku_tier]} (#{r[:abc_xyz_class]}) | Urgency: #{r[:urgency_score]}/100"
  puts "NET ATP ON-HAND  : #{r[:net_on_hand]} units (#{r[:wos]} wks cover)"
  puts "SAFETY STOCK/ROP : Safety Stock = #{r[:safety_stock]} units | ROP = #{r[:rop]} units"
  puts "RECOMMENDED PO   : #{r[:total_order]} units (Primary: #{r[:primary_order]} | Backup: #{r[:backup_order]} | Expedite Air: #{r[:expedite_units]})"
  puts "TOTAL PO SPEND   : $#{'%.2f' % r[:total_spend]} (Expedite Freight: $#{'%.2f' % r[:expedite_freight]})"
  puts "COMPOSITE RISK   : #{r[:composite_score]}/100 (#{r[:overall_level]})"
  puts "S&OP DECISION    : #{r[:decision_status]} (Requires HITL: #{r[:requires_hitl]})"
  puts "HITL CODE STOP   : #{r[:hitl_reason]}" unless r[:hitl_reason].empty?
  puts "PII-SCRUBBED ERP : #{r[:sanitized_notes]}"
  puts "=" * 88
  puts ""
end
RUBY_EOF
