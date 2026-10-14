from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text

from imgsr.db.models import Base
from imgsr.db.session import make_engine, migrate


def test_migration_matches_models(tmp_path):
    engine = make_engine(tmp_path / "m.sqlite3")
    migrate(engine)
    with engine.connect() as conn:
        context = MigrationContext.configure(conn, opts={"render_as_batch": True})
        assert compare_metadata(context, Base.metadata) == []
    migrate(engine)  # idempotent
    engine.dispose()


def test_foreign_keys_and_wal_enabled(tmp_path):
    engine = make_engine(tmp_path / "p.sqlite3")
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
    engine.dispose()
