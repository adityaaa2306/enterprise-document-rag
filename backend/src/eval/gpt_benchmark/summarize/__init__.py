"""Document Summarization workload for the offline benchmark framework."""

from src.eval.gpt_benchmark.summarize.runner import run_summarization_benchmark
from src.eval.gpt_benchmark.summarize.suites import list_summarization_suites

__all__ = [
    "run_summarization_benchmark",
    "list_summarization_suites",
]
