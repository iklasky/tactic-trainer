#!/bin/bash
set -euo pipefail

# Install Python dependencies
echo "Installing Python dependencies..."
python -m pip install -r requirements.txt

# Install Node dependencies and build frontend
echo "Building frontend..."
npm install
npm run build

# Start the Flask backend with gunicorn
echo "Starting Flask backend..."
python -m gunicorn app_v2:app --bind 0.0.0.0:${PORT:-5000} --timeout 120 --workers 2
