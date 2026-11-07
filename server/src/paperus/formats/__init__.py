"""Writing a library for other reference managers: the import's common
form (``paperus.importing.Export``) the other way round.

Each format's ``write(export)`` gives a ``Written``: the file, a name for
it, what the format cannot hold (``warnings``) and a README saying how to
import it. File paths are written as the export gives them, relative to
the written file, so the files go beside it (e.g. in ``files/``).
"""

from paperus.formats import jabref, ris, zotero
from paperus.formats.common import Written

# Program → its writer, for "an export for Zotero / JabRef / Mendeley".
WRITERS = {"zotero": zotero.write, "jabref": jabref.write, "mendeley": ris.write}

__all__ = ["WRITERS", "Written", "jabref", "ris", "zotero"]
