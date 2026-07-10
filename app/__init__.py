# The __init__.py file marks a directory as a regular Python package.
# So we can do this
"""
from app.main import app        # ← what uvicorn does with "app.main:app"
from app.config import Settings # ← what main.py itself does
"""
