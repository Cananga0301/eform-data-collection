"""
Flask route handlers for the E-Form Data Collection API.
All management flows are served via the Streamlit UI (src/streamlit_app.py).
These endpoints are minimal — mainly health-check and thin API surface for Streamlit calls.
"""
import logging

from flask import jsonify

from blueprint import api_bp

logger = logging.getLogger(__name__)


@api_bp.route('/health-check', methods=['GET'])
def health_check():
    return jsonify({'status': 'ok', 'version': '0.1.0'})
