from sqlalchemy import inspect, text

from app.db import Base, get_engine


def test_migrations_build_the_schema_the_models_describe(client):
    """The test database is created by the migrations alone (see init_db); it must have
    every table and column the models declare."""
    engine = get_engine()
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert set(Base.metadata.tables) <= tables
    for name, table in Base.metadata.tables.items():
        columns = {column["name"] for column in inspector.get_columns(name)}
        assert {column.name for column in table.columns} <= columns, name
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
