import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DATA_SOURCE", "synthetic")
os.environ.setdefault("STATE_DIR", tempfile.mkdtemp())
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["COINGLASS_API_KEY"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
