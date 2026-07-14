"""
Enhanced profiling helpers — waterfall charts + resource samples.

Wraps IngestionLatencyTracker; does not alter pipeline behavior.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# Optional psutil for memory/CPU — degrade gracefully
try:
    import psutil  # type: ignore

    _PROC = psutil.Process()
    _HAS_PSUTIL = True
except Exception:
    _PROC = None
    _HAS_PSUTIL = False


def sample_resources() -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "wall_ms": round(time.perf_counter() * 1000.0, 3),
        "cpu_process_ms": round(time.process_time() * 1000.0, 3),
    }
    if _HAS_PSUTIL and _PROC is not None:
        try:
            mem = _PROC.memory_info()
            out["rss_mb"] = round(mem.rss / (1024 * 1024), 2)
            out["cpu_percent"] = _PROC.cpu_percent(interval=None)
            out["num_threads"] = _PROC.num_threads()
        except Exception:
            pass
    # Optional NVIDIA GPU stats via pynvml / nvidia-ml-py — never required
    try:
        import pynvml  # type: ignore

        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
        meminfo = pynvml.nvmlDeviceGetMemoryInfo(handle)
        out["gpu_util_percent"] = float(util.gpu)
        out["gpu_mem_used_mb"] = round(meminfo.used / (1024 * 1024), 2)
        out["gpu_mem_total_mb"] = round(meminfo.total / (1024 * 1024), 2)
        pynvml.nvmlShutdown()
    except Exception:
        out["gpu_util_percent"] = None
        out["gpu_mem_used_mb"] = None
    return out


def format_waterfall(stages_ms: Dict[str, float], *, bar_width: int = 40) -> str:
    """ASCII waterfall like the phase-1 brief."""
    if not stages_ms:
        return "(no stages)"
    # Exclude total from bar scaling so stages sum visually
    items = [(k, float(v)) for k, v in stages_ms.items() if k != "total_ms" and v is not None]
    if not items:
        items = [(k, float(v)) for k, v in stages_ms.items()]
    peak = max((v for _, v in items), default=1.0) or 1.0
    lines = ["=== Waterfall (relative to slowest stage) ==="]
    for name, ms in items:
        n = max(1, int(round((ms / peak) * bar_width))) if ms > 0 else 0
        bar = "█" * n
        lines.append(f"{name:28} {bar} {ms/1000.0:7.1f}s")
    if "total_ms" in stages_ms:
        lines.append(f"{'TOTAL':28} {float(stages_ms['total_ms'])/1000.0:7.1f}s")
    return "\n".join(lines)


def rank_bottlenecks(stages_ms: Dict[str, float], top_n: int = 10) -> List[Dict[str, Any]]:
    ranked = sorted(
        ((k, float(v)) for k, v in stages_ms.items() if k != "total_ms"),
        key=lambda kv: kv[1],
        reverse=True,
    )
    total = sum(v for _, v in ranked) or 1.0
    out = []
    for i, (name, ms) in enumerate(ranked[:top_n], start=1):
        out.append(
            {
                "rank": i,
                "stage": name,
                "ms": round(ms, 1),
                "sec": round(ms / 1000.0, 2),
                "pct_of_stages": round(100.0 * ms / total, 1),
            }
        )
    return out


def attach_resource_snapshot(latency: Dict[str, Any], label: str = "end") -> Dict[str, Any]:
    meta = dict(latency.get("meta") or {})
    snaps = list(meta.get("resource_snapshots") or [])
    snaps.append({"label": label, **sample_resources()})
    meta["resource_snapshots"] = snaps[-20:]
    latency["meta"] = meta
    return latency
