"""Beat Shabber AI — webcam Beat Saber clone (Computer Vision demo).

Run:  python main.py   (Python 3.11, see requirements.txt)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from game import run

if __name__ == "__main__":
    run()
