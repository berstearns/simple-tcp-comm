"""Load .env file into os.environ. Zero deps."""
import os

def load(path=None):
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            k, _, v = line.partition("=")
            if k and _ == "=":
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))
