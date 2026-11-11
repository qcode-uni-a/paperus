"""``python -m paperus``: the command line, where no ``paperus`` script is
installed or its path is not known (the app's library on this computer,
docs/apps.md)."""

import sys

from paperus.cli import main

sys.exit(main())
