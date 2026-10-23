import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS / "tap"))
sys.path.insert(0, str(_SCRIPTS / "ci"))
sys.path.insert(0, str(_SCRIPTS / "builder"))
sys.path.insert(0, str(_SCRIPTS / "audit"))
