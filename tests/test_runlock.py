import pytest

from aidigest.runlock import RunLocked, run_lock


def test_second_lock_is_refused(tmp_path):
    with run_lock(tmp_path):
        with pytest.raises(RunLocked):
            run_lock(tmp_path).__enter__()


def test_lock_released_after_exception(tmp_path):
    with pytest.raises(ValueError):
        with run_lock(tmp_path):
            raise ValueError
    with run_lock(tmp_path):
        pass
