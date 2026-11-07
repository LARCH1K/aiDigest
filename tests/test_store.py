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
