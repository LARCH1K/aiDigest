from aidigest.store import MemoryStore, StoreData


def test_memory_store_starts_empty():
    d = MemoryStore().load()
    assert d.cases == [] and d.processed_urls == set()


def test_memory_store_keeps_copy(make_case):
    st = MemoryStore()
    data = StoreData([make_case(title="А")], {"https://a.ru/1"})
    st.save(data)
    data.cases[0].title = "Б"          # не сохранено — в хранилище прежнее значение
    data.processed_urls.add("https://a.ru/2")
    assert st.load().cases[0].title == "А" and st.load().processed_urls == {"https://a.ru/1"}
    loaded = st.load()
    loaded.cases[0].title = "В"        # правка загруженного без save тоже не попадает в хранилище
    assert st.load().cases[0].title == "А"
