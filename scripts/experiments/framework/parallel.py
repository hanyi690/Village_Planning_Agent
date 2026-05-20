"""Parallel experiment scheduler — run multiple sessions concurrently."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List

from .config import ExperimentConfig

logger = logging.getLogger(__name__)


class ParallelExperimentScheduler:
    """Schedule multiple experiment runners with bounded concurrency.

    Each runner uses a unique session_id, so SQLite WAL + SSE per-session
    queues + LangGraph thread_id isolation ensure safe parallelism.
    The global LLM_SEMAPHORE(3) caps total API concurrency.
    """

    def __init__(self, config: ExperimentConfig, max_parallel: int = 2):
        self.config = config
        self.max_parallel = max_parallel
        self._semaphore = asyncio.Semaphore(max_parallel)

    async def run_experiments_parallel(
        self,
        runners: List[Any],
    ) -> List[Any]:
        """Run multiple ExperimentRunner instances in parallel.

        Returns list of results (or Exception on failure).
        """
        async def _run_with_semaphore(runner):
            async with self._semaphore:
                logger.info(
                    "[Scheduler] Acquired slot for %s", runner.config.experiment_id
                )
                try:
                    return await runner.run()
                except Exception as e:
                    logger.error(
                        "[Scheduler] %s failed: %s", runner.config.experiment_id, e
                    )
                    return e

        tasks = [_run_with_semaphore(r) for r in runners]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error("[Scheduler] Experiment %d failed: %s", i, result)

        return list(results)

    async def run_sequential(
        self,
        runners: List[Any],
    ) -> List[Any]:
        """Run experiments one at a time (for debugging)."""
        results = []
        for runner in runners:
            try:
                result = await runner.run()
                results.append(result)
            except Exception as e:
                logger.error("[Scheduler] %s failed: %s", runner.config.experiment_id, e)
                results.append(e)
        return results