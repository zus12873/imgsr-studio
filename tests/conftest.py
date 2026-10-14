import pytest

from imgsr.db.models import Base
from imgsr.db.session import make_engine, make_session_factory


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(tmp_path / "db" / "test.sqlite3")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def sf(engine):
    return make_session_factory(engine)
