import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import *
X = load_xl(sys.argv[1])
X.to_pickle("xl.pkl")
