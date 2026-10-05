import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["CDS_MODE"] = "offline"
os.environ["CDS_VECTOR_BACKEND"] = "local"
os.environ.setdefault("AWS_REGION", "us-east-1")
