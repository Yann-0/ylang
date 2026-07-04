"""Open all Ylang stores on a single shared SQLite connection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ylang.core.db import YlangDatabase
from ylang.core.memory import MemoryStore
from ylang.library.store import Library, from_connection as library_from_connection
from ylang.usage.store import UsageStore, from_database as usage_from_database


@dataclass(frozen=True, slots=True)
class YlangStores:
    """Usage, library, and memory stores sharing one SQLite connection."""

    database: YlangDatabase
    store: UsageStore
    library: Library
    memory: MemoryStore

    def close(self) -> None:
        """Close the shared database connection."""
        self.database.close()

    def reconnect_shared(self) -> None:
        """Reopen SQLite after permissions change and refresh all store handles."""
        self.database.reconnect()
        connection = self.database.connection
        self.store._connection = connection
        self.library._connection = connection
        self.memory._connection = connection


def open_stores(db_path: Path) -> YlangStores:
    """Open all stores on a single shared SQLite connection."""
    database = YlangDatabase.open(db_path)
    connection = database.connection
    store = usage_from_database(database)
    library = library_from_connection(connection)
    memory = MemoryStore.from_connection(connection)
    stores = YlangStores(
        database=database,
        store=store,
        library=library,
        memory=memory,
    )
    store.bind_reconnect(stores.reconnect_shared)
    return stores
