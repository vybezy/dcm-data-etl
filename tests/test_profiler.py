import builtins

import utils


def _sample(x):
    return x * 2


def test_profiling_disabled_by_default(monkeypatch):
    monkeypatch.delenv("DICOM_PROFILE", raising=False)
    assert utils.profiling_enabled() is False
    # decorator returns the exact same function object: zero overhead
    assert utils.Profiler(_sample) is _sample


def test_profiling_enabled_values(monkeypatch):
    for value in ("1", "true", "YES"):
        monkeypatch.setenv("DICOM_PROFILE", value)
        assert utils.profiling_enabled() is True
    monkeypatch.setenv("DICOM_PROFILE", "0")
    assert utils.profiling_enabled() is False


def test_profiling_without_line_profiler_falls_back(monkeypatch):
    """If line_profiler is missing, the function still runs, just unprofiled."""
    monkeypatch.setenv("DICOM_PROFILE", "1")
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "line_profiler":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    wrapped = utils.Profiler(_sample)
    assert wrapped is _sample
    assert wrapped(21) == 42
