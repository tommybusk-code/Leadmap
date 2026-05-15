"""Parallellisering for analyse-pipeline."""
from concurrent.futures import ThreadPoolExecutor, as_completed

from state import _tick_safe

_PARALLEL_WORKERS = 8


def _parallel_run(items, fn, on_progress=None, max_workers=_PARALLEL_WORKERS):
    """Kjør fn(item) parallelt over alle items."""
    if not items:
        return []
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(fn, it): it for it in items}
        for fut in as_completed(futures):
            it = futures[fut]
            try:
                results.append((it, fut.result()))
            except Exception as e:
                print(f"[parallel] feil for {it}: {e}")
                results.append((it, None))
            if on_progress:
                on_progress()
    return results
