"""Allow `python -m luckyd_code` to work."""
import sys
from .cli_entry import main

sys.exit(main())
