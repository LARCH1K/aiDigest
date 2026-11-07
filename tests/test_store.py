import pytest

from aidigest.store import CaseStore, StoreData


def test_missing_file_gives_empty_store(tmp_path):
    d = CaseStore(tmp_path / "cases.json").load()
    assert d.cases == [] and d.processed_urls == set()


def test_store_roundtrip(tmp_path, make_case):
    st = CaseStore(tmp_path / "cases.json")
    st.save(StoreData([make_case()], {"https://a.ru/1"}))
    d = st.load()
    assert len(d.cases) == 1 and d.processed_urls == {"https://a.ru/1"}
    text = (tmp_path / "cases.json").read_text(encoding="utf-8")
    assert "регионы РФ" in text and '"flags"' in text


def test_failed_save_keeps_old_file(tmp_path, make_case, monkeypatch):
    p = tmp_path / "cases.json"
    st = CaseStore(p)
    st.save(StoreData([make_case()], set()))
    before = p.read_text(encoding="utf-8")

    def boom(*a):
        raise OSError("диск")
    monkeypatch.setattr("aidigest.store.os.replace", boom)
    with pytest.raises(OSError):
        st.save(StoreData([], set()))
    assert p.read_text(encoding="utf-8") == before


def test_save_retries_transient_windows_lock(tmp_path, make_case, monkeypatch):
    import os as real_os
    p = tmp_path / "cases.json"
    calls = {"n": 0}
    real_replace = real_os.replace

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("файл занят другим процессом")
        return real_replace(src, dst)
    monkeypatch.setattr("aidigest.store.os.replace", flaky)
    monkeypatch.setattr("aidigest.store.time.sleep", lambda s: None)
    CaseStore(p).save(StoreData([make_case()], set()))
    assert calls["n"] == 3 and len(CaseStore(p).load().cases) == 1


def test_save_gives_up_after_retries(tmp_path, make_case, monkeypatch):
    def locked(src, dst):
        raise PermissionError("занят")
    monkeypatch.setattr("aidigest.store.os.replace", locked)
    monkeypatch.setattr("aidigest.store.time.sleep", lambda s: None)
    with pytest.raises(PermissionError):
        CaseStore(tmp_path / "c.json").save(StoreData([], set()))
