import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DATA_SOURCE", "synthetic")
os.environ.setdefault("STATE_DIR", tempfile.mkdtemp())
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["COINGLASS_API_KEY"] = ""
os.environ["MANUAL_PAPER"] = "1"    # 포지션 감시·리스크 계산 테스트용으로만 수동 포지션을 만든다
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
