# Dupli klik na ovaj fajl pokrece mailconv GUI (Windows: bez crnog prozora).
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mailconv.gui import main  # noqa: E402

raise SystemExit(main())
