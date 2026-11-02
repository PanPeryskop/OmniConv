import os
import sys
import warnings

warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app import create_app

create_app().run(host='127.0.0.1', port=int(sys.argv[1]), debug=False, use_reloader=False)
