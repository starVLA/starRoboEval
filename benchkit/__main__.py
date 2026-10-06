"""Allow ``python -m benchkit`` to invoke the CLI."""

from benchkit.cli import main

raise SystemExit(main())
