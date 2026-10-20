"""端到端: 真实数据版概率实验室 (12 步 + Step 13 DrawScope)"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / 'third_party'))

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from analytics.probability_lab import run_full_lab

game = sys.argv[1] if len(sys.argv) > 1 else 'dlt'
run_full_lab(game=game)