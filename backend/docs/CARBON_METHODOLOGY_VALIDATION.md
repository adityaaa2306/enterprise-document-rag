# Carbon Methodology Refactor — Validation Report

Date: 2026-07-13  
Scope: `backend/src/carbon/*`, results/dashboard UI labels, `backend/docs/CARBON_ACCOUNTING.md`

## 1. What changed

1. **Removed** `BASELINE_SERVING_OVERHEAD` (and any silent calibration multiplier).
2. **Introduced** `assumptions.py` with documented `PUE`, `INFRASTRUCTURE_FACTOR`, and
   `J_PER_TOKEN` tables (low / typical / high) plus stage J/token constants.
3. **Rewrote** energy math as:
   `tokens × J/token → × PUE → kWh → Electricity Maps intensity → CO₂e`.
4. **Redefined baseline** as conventional map-reduce (medium map + heavy compile)
   without smart tier routing — fair counterfactual to the green router.
5. **Added** Reporting Boundary A (operational) with reserved B/C enums.
6. **Renamed** UI/API terminology to *Estimated Baseline/Optimized Pipeline Emissions*.
7. **Exposed** stage CO₂e breakdown, routing impact stats, and uncertainty bands.
8. **Documented** equations, assumptions, and references in `CARBON_ACCOUNTING.md`.
9. **Preserved** Electricity Maps live intensity, dashboard metric set, and routing architecture.
10. **Frontier comparison** no longer uses `baseline_CO₂ × arbitrary factor`. It re-prices
    effective tokens at each model's documented J/token × PUE × the same live grid intensity.
11. **Job Report Card** receives a flattened `report_card` payload so tokens / energy /
    timestamps / stages cannot render as `—` when breakdown is present in storage.

## 2. Why it changed

The prior baseline (~28 g) was dominated by a **4.5× serving overhead** tuned to land in a
20–50 g UI band. That made the accounting internally consistent but not scientifically
transparent for a capstone defense. The refactor keeps the same architecture while making
every constant auditable and literature-aligned.

## 3. Why the new methodology is more defensible

| Criterion | Before | After |
|-----------|--------|-------|
| Primary equation | Wh/token × opaque overhead | J/token × PUE × grid intensity |
| Calibration knobs | `BASELINE_SERVING_OVERHEAD=4.5` | None (PUE=1.15 from datacenter literature) |
| Scope | Unclear | Explicit Boundary A (operational) |
| Uncertainty | Point estimate only | Optional low/typical/high bands |
| Stage transparency | Aggregate only | Parse / chunk / embed / inference / infra |
| Routing story | Implicit | Explicit chunk tier + compile call stats |

Electricity Maps remains the sole source of regional gCO₂e/kWh.

## 4. Assumptions that remain (provider limits)

Cloud LLM APIs do **not** expose metered facility joules per request. Therefore:

- J/token values are **literature-anchored estimates** (medium tier from arXiv:2505.09598),
  not NVIDIA NIM invoices.
- Token counts may use `len(text)/4` when provider usage metadata is absent.
- Heavy/light relative intensities are documented engineering judgments vs the mini-class anchor.
- Network egress, object-storage I/O, and hardware manufacturing remain **out of Boundary A**.

## 5. Verification checklist

- [x] No `BASELINE_SERVING_OVERHEAD` in runtime modules
- [x] Every constant in `assumptions.py` has source/units comments
- [x] `estimate_workflow_carbon` returns stages, routing_impact, uncertainty, assumptions_panel
- [x] Dashboard/report card use “Estimated …” terminology
- [x] Electricity Maps still supplies intensity / zone / timestamp
- [x] Unit tests: `tests/test_carbon_accounting.py`, `tests/test_frontier_carbon_compare.py` (15 passed)

## 6. Test command

```bash
cd backend
python -m pytest tests/test_carbon_accounting.py tests/test_frontier_carbon_compare.py -q
```
