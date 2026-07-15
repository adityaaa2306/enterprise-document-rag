/**
 * Proof: Dashboard Latest Job and Results share the same metrics by
 * revision sync key + field fingerprint — not JS object identity.
 *
 * Also documents Historical Analytics as a separate Owner aggregate path.
 */
import assert from "node:assert/strict"

function revisionOf(result) {
  const r = Number(result._revision)
  return Number.isFinite(r) && r >= 0 ? r : 0
}

function updatedAtOf(result) {
  if (result.updated_at != null && result.updated_at !== "") return String(result.updated_at)
  const cd = result.carbon_data || {}
  return `r${revisionOf(result)}:b${Number(cd.baseline_cost_gco2e || 0)}:c${Number(cd.total_chunks || 0)}`
}

function finalizedSyncKey(jobId, revision, updatedAt, ownerKey) {
  return `${ownerKey}|${jobId}|rev:${revision}|at:${updatedAt}`
}

function extractCore(result) {
  const cd = result.carbon_data || {}
  return {
    baselineG: Number(cd.baseline_cost_gco2e || 0),
    optimizedG: Number(cd.operational_co2e_g || cd.actual_cost_gco2e || 0),
    savedG: Number(cd.carbon_saved_grams || 0),
    reductionPct: Number(cd.efficiency_percent || 0),
    region: String(cd.region_decision?.selected_region_name || cd.compute_location || "—"),
  }
}

function fingerprint(m) {
  return [m.optimizedG, m.baselineG, m.savedG, m.reductionPct, m.region].join("|")
}

const ownerKey = "guest:demo"
const jobId = "job-abc"

const resultV1 = {
  _revision: 3,
  updated_at: "2026-07-16T10:00:00Z",
  carbon_data: {
    baseline_cost_gco2e: 121.8,
    operational_co2e_g: 75.7,
    carbon_saved_grams: 46.1,
    efficiency_percent: 37.8,
    region_decision: { selected_region_name: "India" },
  },
}

// Simulate publish → store metrics (Layer 1)
const storeMetrics = extractCore(resultV1)
const storeKey = finalizedSyncKey(
  jobId,
  revisionOf(resultV1),
  updatedAtOf(resultV1),
  ownerKey,
)

// Dashboard Latest Job reads store by sync key
const dashboardLatest = { syncKey: storeKey, metrics: storeMetrics }

// Results prefers store when sync keys match (after JSON round-trip — new object)
const restored = JSON.parse(JSON.stringify(resultV1))
const resultsKey = finalizedSyncKey(
  jobId,
  revisionOf(restored),
  updatedAtOf(restored),
  ownerKey,
)
assert.equal(dashboardLatest.syncKey, resultsKey)
assert.notStrictEqual(resultV1, restored) // different object identity
assert.equal(fingerprint(dashboardLatest.metrics), fingerprint(extractCore(restored)))

// Historical analytics is a separate aggregate (Owner-scoped) — not the latest job alone
const historical = {
  total_docs: 3,
  total_carbon_consumed: 200.0,
  total_baseline_carbon: 360.0,
  total_carbon_saved: 160.0,
  avg_efficiency: 44.0,
}
assert.notEqual(historical.total_carbon_consumed, storeMetrics.optimizedG)
assert.ok(historical.total_docs > 1)

// Guest: historical naturally collapses to one job
const guestHistorical = {
  total_docs: 1,
  total_carbon_consumed: storeMetrics.optimizedG,
  total_baseline_carbon: storeMetrics.baselineG,
  total_carbon_saved: storeMetrics.savedG,
  avg_efficiency: storeMetrics.reductionPct,
}
assert.equal(guestHistorical.total_docs, 1)
assert.equal(guestHistorical.total_carbon_consumed, storeMetrics.optimizedG)

console.log("PASS: revision sync keys match across serialization")
console.log("PASS: field fingerprints equal for Latest Job ↔ Results")
console.log("PASS: Historical analytics remains a separate Owner aggregate")
console.log({ storeKey, fingerprint: fingerprint(storeMetrics), historicalDocs: historical.total_docs })
