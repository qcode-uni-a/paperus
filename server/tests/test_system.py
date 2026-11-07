"""Settings kept in the database: the vectors in use and the backup
schedule."""

from sqlalchemy.orm import Session

from paperus import system


def test_vectors_in_use(db: Session) -> None:
    assert system.vectors_in_use(db, "bge-m3") == "bge-m3"
    system.save_vectors_in_use(db, "bge-m3", "bge-m3@fp16")
    system.save_vectors_in_use(db, "multilingual-e5-small", "e5@int8")
    db.commit()
    # Each model keeps its own.
    assert system.vectors_in_use(db, "bge-m3") == "bge-m3@fp16"
    assert system.vectors_in_use(db, "multilingual-e5-small") == "e5@int8"


def test_backup_schedule(db: Session) -> None:
    assert system.load_backup_config(db) == system.BackupConfig()
    chosen = system.BackupConfig(schedule="weekly", hour=4, keep=3)
    system.save_backup_config(db, chosen)
    db.commit()
    assert system.load_backup_config(db) == chosen
