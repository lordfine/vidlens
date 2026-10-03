"""S5: cross-process write lock for cache directories."""
import pytest

from vidlens.locking import LockTimeout, cache_write_lock


def test_lock_mutual_exclusion(tmp_path):
    with cache_write_lock(tmp_path):
        with pytest.raises(LockTimeout):
            with cache_write_lock(tmp_path, timeout=0.2):
                pass  # pragma: no cover


def test_lock_released_after_exit(tmp_path):
    with cache_write_lock(tmp_path):
        pass
    with cache_write_lock(tmp_path, timeout=0.2):
        pass  # reacquire must succeed


def test_lock_timeout_is_agent_contracted_error(tmp_path):
    err = LockTimeout("x")
    assert err.errcode == "lock_timeout"
    assert err.exit_code == 1
    assert err.hint is not None


def test_distinct_dirs_do_not_block(tmp_path):
    """Lock is per-directory: different videos never block each other."""
    with cache_write_lock(tmp_path / "a"):
        with cache_write_lock(tmp_path / "b", timeout=0.2):
            pass
