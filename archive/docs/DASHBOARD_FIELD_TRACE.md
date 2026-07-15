# Dashboard Field Trace — Carbon / Routing / Region

Investigation of blank dashboard cards after completed jobs (2026-07-16).

## Root causes (proven)

| # | Breakpoint | Evidence |
|---|------------|----------|
| 1 | `deliver_summary` imported `build_processing_insights` from **wrong module** (`explainability.builder`) | ImportError swallowed → **no `processing_insights`** at Summary Ready (job `e3487747…`) |
| 2 | `_patch_result_carbon` only copied a **short allow-list** of carbon keys | Dropped `local_grid_gco2_kwh`, `compute_location`, `breakdown`, energies, tokens, etc. even when accounting produced them |
| 3 | `/job-result` **invented** `local_grid=0` / `compute_location=unknown` | Hid real values already on `region_decision.grid_carbon_intensity_gco2_kwh=643` / `selected_region_name=India` |
| 4 | `document_profile` exposed `complexity_class` only | Frontend reads `profile.complexity` → always "—" |
| 5 | Jobs stuck mid-background (`e3487747`) never reached finalize patch | Carbon stayed at Summary Ready placeholders (baseline/saved = 0) |

## Field trace (Search Ready job `d63ee215-…`)

| Field | Produced by | Stored in | Persisted to | API | Frontend |
|-------|-------------|-----------|--------------|-----|----------|
| baseline_co2e | `accounting.calculate_*` | `carbon_data.baseline_cost_gco2e` | `_patch_result_carbon` → `result_json` | `/job-result` | Hero tiles |
| optimized_co2e | DAG rollups + accounting | `operational_co2e_g` / `actual_cost_gco2e` | deliver + patch | same | same |
| carbon_saved | accounting | `carbon_saved_grams` | patch | same | same |
| reduction_percent | accounting | `efficiency_percent` | patch | same | same |
| grid_intensity | Region scheduler → EM | `region_decision.grid_carbon_intensity_gco2_kwh` + promoted `local_grid_gco2_kwh` | patch + promote | same | Region tab |
| compute_region | RegionDecision | `selected_region_name` → `compute_location` | promote | same | Region tab |
| electricity_provider | RegionDecision | `region_decision.provider` | patch | same | Region tab |
| tier_distribution | chunk router | `routing_distribution` + PI | deliver + patch | same | Routing panel |
| chunk_routing | map phase | `chunk_routing` / `chunk_routing_sample` | deliver + patch | same | Routing table |
| escalation_count | accounting + decision | `PI.escalation` / `chunks_escalated` | patch | same | Routing |
| document_type | features / router | `PI.document_type` | deliver (fixed import) | same | Region & Strategy |
| complexity | capability profile | `document_profile.complexity` (alias of `complexity_class`) | PI builder | same | Region & Strategy |
| confidence | validation | `PI.confidence` | deliver + patch | same | Region & Strategy |
| strategy | pipeline intelligence | `processing_strategy` / report | PI | same | Region & Strategy |

## Before vs After (API `/job-result` for `d63ee215`)

**Before (broken top-level):**
```json
"local_grid_gco2_kwh": 0.0,
"compute_location": "unknown",
"report_card": { "grid_carbon_intensity_gco2_kwh": 0.0 }
```
(while `region_decision.grid_carbon_intensity_gco2_kwh` was already `643.0`)

**After:**
```json
"baseline_cost_gco2e": 23.24,
"actual_cost_gco2e": 13.21,
"carbon_saved_grams": 8.94,
"efficiency_percent": 38.5,
"local_grid_gco2_kwh": 643.0,
"compute_location": "India",
"grid_zone": "IN-WE",
"processing_insights.document_type": "technical_documentation",
"processing_insights.document_profile.complexity": "simple|moderate",
"processing_insights.routing_distribution": { "light": 8, "medium": 3, "heavy": 0, "total": 11 },
"processing_insights.chunk_routing_sample": [11 rows]
```

## Files changed

- `backend/src/core/carbon_result_merge.py` (new)
- `backend/src/core/background_services.py` — full additive carbon + PI refresh
- `backend/src/core/orchestrator.py` — fix PI import; stamp document_type
- `backend/src/core/processing_insights.py` — complexity alias; no fake empty routing
- `backend/src/api/schemas.py` — carbon fields Optional (no invented zeros)
- `backend/src/api/main.py` — promote region on `/job-result` (no invent)
- `backend/tests/test_carbon_result_merge.py`
- `backend/tests/test_job_result_partial_carbon.py`

## Note on `e3487747-…`

Still Summary Ready–partial (no `region_decision` in DB) — background finalize never patched. New jobs after this fix get correct PI at Summary Ready and full carbon/region on Search Ready. Re-run that document to populate the dashboard.
