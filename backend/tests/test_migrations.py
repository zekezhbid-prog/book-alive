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


def test_existing_conversation_becomes_the_first_chat_thread(client):
    """0009 moves each project's messages into one thread named after its first question."""
    from alembic import command
    from alembic.config import Config

    from app.config import BACKEND_DIR

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    engine = get_engine()
    command.downgrade(config, "0008")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO projects (id, title, author, mode, source_filename, "
                    "split_method, style_id, style_text, created_at) VALUES ('mig9', 'M', '', "
                    "'reader', '', 'manual', '', '', now())"
                )
            )
            for n, (role, content) in enumerate(
                [("user", "Кто такая Люта?"), ("assistant", "Княжна."), ("user", "А Цмок?")]
            ):
                connection.execute(
                    text(
                        "INSERT INTO chat_messages (id, project_id, role, content, citations, "
                        "created_at) VALUES (:id, 'mig9', :role, :content, '[]', "
                        "now() + make_interval(secs => :n))"
                    ),
                    {"id": f"mig9m{n}", "role": role, "content": content, "n": n},
                )
    finally:
        command.upgrade(config, "head")
    with engine.connect() as connection:
        threads = connection.execute(
            text("SELECT id, title FROM chat_threads WHERE project_id = 'mig9'")
        ).all()
        assert [title for _, title in threads] == ["Кто такая Люта?"]
        owners = connection.execute(
            text("SELECT DISTINCT thread_id FROM chat_messages WHERE project_id = 'mig9'")
        ).scalars()
        assert list(owners) == [threads[0][0]]
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM projects WHERE id = 'mig9'"))
