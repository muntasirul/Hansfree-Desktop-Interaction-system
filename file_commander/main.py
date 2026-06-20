"""
main.py — Entry point for AI File Commander.
Run this file to launch the app: python main.py
"""

import os
import sys

# Ensure we can import from this folder
sys.path.insert(0, os.path.dirname(__file__))

from gui import FileCommanderApp

if __name__ == "__main__":
    app = FileCommanderApp()
    app.mainloop()
