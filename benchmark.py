"""
measures how import speed changes with the number of parallel workers.

every run resets the pipeline tables and imports the same files again, so the
database ends up holding one clean copy of the data. run it inside docker:

    docker compose run --rm etl_pipeline python benchmark.py

options: --workers 0 1 2 4 8 (worker counts to try), --repeats 3, and a path
(defaults to the same folder main.py uses).
"""
import os
import sys
import time
import logging
import argparse
import platform
import statistics

import main
from logger import console_handler


def count_files(path: str) -> int:
    """number of .dcm files that will be imported."""
    return sum(
        1
        for _, _, files in os.walk(path)
        for f in files
        if f.lower().endswith(".dcm")
    )


def run_import(path: str, workers: int) -> float:
    """one full import (tables reset first); returns the time in seconds."""
    start = time.perf_counter()
    exit_code = main.main([path, "--reset", "--no-azure", "--workers", str(workers)])
    elapsed = time.perf_counter() - start
    if exit_code != 0:
        raise SystemExit(f"import failed with exit code {exit_code} (workers={workers})")
    return elapsed


def run_benchmark(path: str, worker_counts, repeats: int, runner=run_import):
    """
    times every worker count `repeats` times and keeps the median.
    returns a list of (workers, median_seconds).
    """
    results = []
    for workers in worker_counts:
        times = []
        for attempt in range(1, repeats + 1):
            seconds = runner(path, workers)
            times.append(seconds)
            print(f"  workers={workers}  run {attempt}/{repeats}: {seconds:.2f}s", flush=True)
        results.append((workers, statistics.median(times)))
    return results


def format_table(results, n_files: int) -> str:
    """markdown table, ready to paste into the readme. speed-up is relative to the first row."""
    baseline = results[0][1]
    lines = [
        "| Workers | Time (s) | Files/sec | Speed-up |",
        "|---|---|---|---|",
    ]
    for workers, seconds in results:
        label = "0 (sequential)" if workers == 0 else str(workers)
        lines.append(
            f"| {label} | {seconds:.2f} | {n_files / seconds:.1f} | {baseline / seconds:.2f}x |"
        )
    return "\n".join(lines)


def parse_args(argv=None) -> argparse.Namespace:
    """reads the command-line options."""
    default_path = main.DOCKER_DATA_DIR if os.path.isdir(main.DOCKER_DATA_DIR) else main.LOCAL_DATA_DIR
    parser = argparse.ArgumentParser(description="Benchmark import speed for different worker counts.")
    parser.add_argument("path", nargs="?", default=default_path, help=f"folder to import (default: {default_path})")
    parser.add_argument("--workers", type=int, nargs="+", default=[0, 1, 2, 4, 8],
                        help="worker counts to try (default: 0 1 2 4 8)")
    parser.add_argument("--repeats", type=int, default=3, help="runs per worker count (default: 3)")
    return parser.parse_args(argv)


def benchmark(argv=None) -> int:
    """runs the benchmark and prints the results table."""
    args = parse_args(argv)
    n_files = count_files(args.path)
    if n_files == 0:
        print(f"no .dcm files found in {args.path}")
        return 2

    # hide the per-file log lines so only the timings are printed
    # (worker processes inherit this level when they start)
    console_handler.setLevel(logging.ERROR)

    print(f"benchmarking {n_files} files in {args.path}, {args.repeats} runs per worker count")
    results = run_benchmark(args.path, args.workers, args.repeats)

    print()
    print(f"machine: {os.cpu_count()} CPU cores, Python {platform.python_version()}, {platform.system()}")
    print(f"files: {n_files}, median of {args.repeats} runs, tables reset before every run")
    print()
    print(format_table(results, n_files))
    return 0


if __name__ == "__main__":
    sys.exit(benchmark())
