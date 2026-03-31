from flask import Blueprint
from pathlib import Path

api_bp = Blueprint('api', __name__, url_prefix='/api')

BASE_DIR = Path(__file__).resolve().parent

from src.controller import eform_controller  # noqa: E402, F401
