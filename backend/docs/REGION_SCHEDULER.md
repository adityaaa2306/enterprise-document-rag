# Carbon-Aware Region Scheduling Architecture

## Purpose

This system includes a **production-ready Carbon-Aware Region Scheduling**
layer. The architecture matches how a cloud carbon scheduler would be
structured in production, while the **current live implementation supports
one execution region** (configured default: India) because the Electricity
Maps free tier exposes live intensity for the configured zone only.

**This is not a fake global scheduler.** The UI and logs state single-region
mode explicitly. Multi-region carbon-optimized selection is designed but not
activated until additional live regions are licensed.

---

## Two independent schedulers

```
Document Upload
  → Document Parsing
  → Capability Analysis
  → Workload Estimation
  → Carbon-Aware Region Scheduler   ← where (region + grid intensity)
  → Model Scheduler                 ← how (light/medium/heavy, QVA, compile)
  → Execution
  → Carbon Accounting
  → Dashboard
```

| Scheduler | Package | Responsibility |
|-----------|---------|----------------|
| **Region Scheduler** | `src.carbon.scheduler` | Select execution region, fetch intensity via provider, emit `RegionDecision` |
| **Model Scheduler** | existing `chunk_router` / `intelligent_router` / orchestrator (facade: `src.core.model_scheduler`) | Tier routing, escalation, compile, validation |

They must not depend on each other. Model routing still uses static
`LOCAL_GRID_INTENSITY` as an optimization *constraint* during the job;
**final CO₂e accounting** always takes intensity from the Region Scheduler.

---

## Current Implementation vs Future Extension

### Current Implementation

- **Mode:** `single-region` (`REGION_SCHEDULER_MODE`)
- **Default region:** configured via `REGION_SCHEDULER_DEFAULT_REGION` (default `india`)
- **Provider:** `electricity_maps` → live `GET /v3/carbon-intensity/latest` for the
  region’s zone or lat/lon (default Pune coordinates → western India / IN-WE)
- **Registry:** one `ACTIVE` / `supports_execution=true` region
- **Dashboard:** “Execution Region” panel shows Selected Region, Provider,
  Intensity, Scheduling Mode = Single Region, Data Source, Execution Status =
  Configured Region, Future support = Multi-region scheduling

### Future Extension

- Register additional `ExecutionRegion` entries (Finland, France, Singapore, …)
- Set `REGION_SCHEDULER_MODE=carbon-optimized`
- Optionally add another `CarbonProvider` implementation
- **No changes** required to carbon equations, model routing, or the scheduler
  algorithm surface (`schedule(workload) → RegionDecision`)

---

## Package layout

```
backend/src/carbon/scheduler/
  region_scheduler.py          # RegionScheduler.schedule(workload)
  registry.py                  # RegionRegistry (config-driven)
  models/
    region.py                  # ExecutionRegion
    decision.py                # RegionDecision, WorkloadEstimate
    grid_data.py               # GridCarbonData
  providers/
    carbon_provider.py         # Abstract CarbonProvider
    electricity_maps_provider.py
    future_provider.py         # Placeholder
```

Application code must **not** call Electricity Maps from accounting or the
API. Intensity flows:

```
RegionScheduler → CarbonProvider → GridCarbonData → estimate_workflow_carbon
```

Low-level HTTP remains in `src.carbon.electricity_maps` and is used only by
`ElectricityMapsProvider`.

---

## Configuration

```env
REGION_SCHEDULER_MODE=single-region
REGION_SCHEDULER_DEFAULT_REGION=india
REGION_SCHEDULER_DEFAULT_REGION_NAME=India
REGION_SCHEDULER_PROVIDER=electricity_maps
ELECTRICITY_MAPS_API_KEY=...
ELECTRICITY_MAPS_ZONE=          # empty → lat/lon
ELECTRICITY_MAPS_LAT=18.52
ELECTRICITY_MAPS_LON=73.85
```

India is **not** hardcoded inside scheduling algorithm branches — it is the
default registry entry built from these settings.

---

## RegionDecision (logged + stored)

Every job finalization attaches `carbon_data.region_decision` with:

- Selected region (id, display name)
- Reason (honest single-region explanation)
- Grid carbon intensity + zone
- Provider
- Timestamp
- Data freshness (`live` / `cached` / `fallback`)
- Confidence
- Scheduling mode
- Execution status
- Future support note

Logs include: region, provider, zone, intensity, mode, freshness, confidence, job id.

---

## Constraints preserved

Unchanged by this refactor:

- Carbon-aware chunk / model routing behaviour
- Carbon accounting **equations** (tokens → J → PUE → kWh × intensity)
- Baseline / optimized methodology definitions
- Validation pipeline
- Existing performance optimizations

Only the **source of grid intensity** and the **architecture boundaries** changed.
