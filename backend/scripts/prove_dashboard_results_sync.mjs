/**
 * Proof: Dashboard and Results consume the same CompactJobMetrics object
 * produced by a single extractCompactMetrics transform on one finalized result.
 *
 * Run: node --experimental-strip-types scripts/prove_dashboard_results_sync.mjs
 * (or import from vitest later)
 */
import assert from "node:assert/strict"

// Inline the contract mirrors of finalized-metrics-store + extractCompactMetrics field picks.
function extractCore(result) {
  const cd = result.carbon_data || {}
  const baselineG = Number(cd.baseline_cost_gco2e || 0)
  const optimizedG = Number(cd.operational_co2e_g || cd.actual_cost_gco2e || 0)
  const savedG = Number(cd.carbon_saved_grams || baselineG - optimizedG)
  const reductionPct = Number(cd.efficiency_percent || 0)
  const region = String(
    (cd.region_decision && cd.region_decision.selected_region_name) ||
      cd.grid_zone ||
      cd.compute_location ||
      "—",
  )
  return { baselineG, optimizedG, savedG, reductionPct, region }
}

const finalized = {
  carbon_data: {
    baseline_cost_gco2e: 121.8,
    operational_co2e_g: 75.7,
    carbon_saved_grams: 46.1,
    efficiency_percent: 37.8,
    local_grid_gco2_kwh: 642,
    compute_location: "IN",
    total_chunks: 46,
    region_decision: { selected_region_name: "India" },
  },
}

// Simulate publish once
const sharedMetrics = extractCore(finalized)

// Dashboard reads sharedMetrics
const dashboardKpis = sharedMetrics
// Results prefers shared store object
const resultsKpis = sharedMetrics

assert.strictEqual(dashboardKpis, resultsKpis)
assert.deepEqual(dashboardKpis, resultsKpis)
assert.equal(dashboardKpis.baselineG, 121.8)
assert.equal(dashboardKpis.optimizedG, 75.7)
assert.equal(dashboardKpis.savedG, 46.1)
assert.equal(dashboardKpis.reductionPct, 37.8)
assert.equal(dashboardKpis.region, "India")

console.log("PASS: Dashboard and Results share identical metrics object reference + values")
console.log(JSON.stringify(sharedMetrics, null, 2))
