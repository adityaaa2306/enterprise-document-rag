"""Plain-language quality insights derived from stored aggregates only."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.eval.gpt_benchmark.participants import display_name


def _num(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def build_quality_insights(aggregates: Dict[str, Any]) -> List[str]:
    """
    Generate observations such as router retaining quality vs cost/latency/CO₂e.
    Purely from summary aggregates — no LLM calls.
    """
    per_model: Dict[str, Dict[str, Any]] = dict(aggregates.get("per_model") or {})
    if not per_model:
        return []

    scored = []
    for mid, stats in per_model.items():
        q = _num(stats.get("avg_quality_score"))
        if q is None:
            continue
        scored.append((mid, stats, q))
    if not scored:
        return [
            "Quality scores were unavailable for this campaign "
            "(no reference answers or all evaluations skipped)."
        ]

    scored.sort(key=lambda t: t[2], reverse=True)
    best_id, best_stats, best_q = scored[0]
    best_label = display_name(best_id)
    lines: List[str] = [
        f"{best_label} produced the highest average quality "
        f"({best_q:.1f}/100) among participants with reference answers."
    ]

    router = None
    for mid, stats, q in scored:
        if mid == "intelligent-router":
            router = (mid, stats, q)
            break

    if router and best_id != "intelligent-router":
        _, rstats, rq = router
        pct_of_best = (rq / best_q * 100.0) if best_q > 0 else 0.0
        cost_r = _num(rstats.get("total_estimated_api_cost_usd"))
        cost_b = _num(best_stats.get("total_estimated_api_cost_usd"))
        lat_r = _num(rstats.get("avg_latency_ms"))
        lat_b = _num(best_stats.get("avg_latency_ms"))
        co2_r = _num(rstats.get("avg_estimated_co2e_g"))
        co2_b = _num(best_stats.get("avg_estimated_co2e_g"))

        cost_note = ""
        if cost_r is not None and cost_b is not None and cost_b > 0:
            reduction = (1.0 - cost_r / cost_b) * 100.0
            if reduction > 2:
                cost_note = f" while reducing estimated cost by {reduction:.0f}%"
            elif reduction < -2:
                cost_note = f" at {abs(reduction):.0f}% higher estimated cost"
        lines.append(
            f"The Intelligent Router achieved {pct_of_best:.0f}% of the highest "
            f"quality score ({rq:.1f} vs {best_q:.1f}){cost_note}."
        )

        if lat_r is not None and lat_b is not None and lat_b > 0:
            lat_delta = (1.0 - lat_r / lat_b) * 100.0
            if abs(lat_delta) >= 5:
                direction = "lower" if lat_delta > 0 else "higher"
                lines.append(
                    f"Router average latency was {abs(lat_delta):.0f}% {direction} "
                    f"than {best_label}."
                )
        if co2_r is not None and co2_b is not None and co2_b > 0:
            c_delta = (1.0 - co2_r / co2_b) * 100.0
            if abs(c_delta) >= 5:
                direction = "lower" if c_delta > 0 else "higher"
                lines.append(
                    f"Router estimated CO₂e was {abs(c_delta):.0f}% {direction} "
                    f"than {best_label}."
                )
    elif router and best_id == "intelligent-router":
        # Router is best quality — compare cost to cheapest GPT if present
        gpt = [
            (mid, st, q)
            for mid, st, q in scored
            if mid != "intelligent-router"
        ]
        if gpt:
            # highest quality among GPT for messaging
            gpt.sort(key=lambda t: t[2], reverse=True)
            g_id, g_stats, g_q = gpt[0]
            g_label = display_name(g_id)
            cost_r = _num(router[1].get("total_estimated_api_cost_usd"))
            cost_g = _num(g_stats.get("total_estimated_api_cost_usd"))
            if cost_r is not None and cost_g is not None and cost_r > 0:
                ratio = cost_g / cost_r
                if ratio >= 1.5:
                    lines.append(
                        f"{g_label} trailed slightly on quality "
                        f"({g_q:.1f} vs {best_q:.1f}) but required "
                        f"{ratio:.1f}× the estimated cost of the Intelligent Router."
                    )

    # Expensive high-quality callout
    if best_id != "intelligent-router":
        costs = [
            (_num(st.get("total_estimated_api_cost_usd")), mid, q)
            for mid, st, q in scored
        ]
        costs = [(c, m, q) for c, m, q in costs if c is not None and c > 0]
        if costs:
            cheap = min(costs, key=lambda t: t[0])
            if cheap[1] != best_id and cheap[0] > 0:
                ratio = (_num(best_stats.get("total_estimated_api_cost_usd")) or 0) / cheap[0]
                if ratio >= 3:
                    lines.append(
                        f"{best_label} produced the highest quality responses but "
                        f"required {ratio:.0f}× the estimated cost of "
                        f"{display_name(cheap[1])}."
                    )

    return lines
