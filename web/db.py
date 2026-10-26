import sqlite3
from pathlib import Path

import click
from flask import current_app, g
from flask.cli import with_appcontext


def get_db():
    if "db" not in g:
        db_path = Path(current_app.config["DATABASE"])

        db_path.parent.mkdir(parents=True, exist_ok=True)

        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row

        connection.execute("PRAGMA foreign_keys = ON")

        g.db = connection

    return g.db


def close_db(error=None):
    db = g.pop("db", None)

    if db is not None:
        db.close()


def init_db():
    db = get_db()

    with current_app.open_resource("schema.sql") as file:
        db.executescript(file.read().decode("utf-8"))

    db.commit()


@click.command("init-db")
@with_appcontext
def init_db_command():
    init_db()
    click.echo("Khoi tao SQLite thanh cong!")


def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
