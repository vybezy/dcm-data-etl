from unittest.mock import patch

import benchmark


def test_run_benchmark_keeps_the_median_per_worker_count():
    fake_times = iter([3.0, 1.0, 2.0,   1.0, 9.0, 1.2])  # 2 worker counts x 3 runs
    results = benchmark.run_benchmark("x", [0, 2], repeats=3, runner=lambda path, w: next(fake_times))
    assert results == [(0, 2.0), (2, 1.2)]


def test_format_table_computes_rate_and_speedup():
    table = benchmark.format_table([(0, 10.0), (4, 4.0)], n_files=80)
    lines = table.splitlines()
    assert lines[0] == "| Workers | Time (s) | Files/sec | Speed-up |"
    assert lines[2] == "| 0 (sequential) | 10.00 | 8.0 | 1.00x |"
    assert lines[3] == "| 4 | 4.00 | 20.0 | 2.50x |"


def test_count_files_only_counts_dcm(tmp_path):
    for name in ("a.dcm", "b.DCM", "notes.txt"):
        (tmp_path / name).write_bytes(b"x")
    assert benchmark.count_files(str(tmp_path)) == 2


def test_failed_import_stops_the_benchmark():
    with patch("benchmark.main.main", return_value=1):
        try:
            benchmark.run_import("x", 2)
        except SystemExit as e:
            assert "exit code 1" in str(e)
        else:
            raise AssertionError("expected SystemExit")


def test_run_import_passes_reset_and_worker_count():
    with patch("benchmark.main.main", return_value=0) as fake_main:
        benchmark.run_import("/data", 4)
    assert fake_main.call_args[0][0] == ["/data", "--reset", "--no-azure", "--workers", "4"]


def test_empty_folder_returns_2(tmp_path):
    assert benchmark.benchmark([str(tmp_path)]) == 2
