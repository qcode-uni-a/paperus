"""Drop and create the end-to-end test database (never the dev database)."""

import os
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

url = make_url(os.environ["PAPERUS_DATABASE_URL"])
name = url.database or ""
if not name.endswith("_e2e"):
    sys.exit(f"refusing to reset {name!r}: the e2e database's name ends in _e2e")
admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
with admin.connect() as connection:
    connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    connection.execute(text(f'CREATE DATABASE "{name}"'))
admin.dispose()
