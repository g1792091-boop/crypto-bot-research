import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DATA_SOURCE", "synthetic")
os.environ.setdefault("STATE_DIR", tempfile.mkdtemp())
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["COINGLASS_API_KEY"] = ""
os.environ["MANUAL_PAPER"] = "1"    # 포지션 감시·리스크 계산 테스트용으로만 수동 포지션을 만든다
os.environ.setdefault("SCENBOT_OFF", "1")  # 시나리오 진입 봇 백그라운드 학습은 테스트에서 끈다 (test_scenbot 이 직접 부른다)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
