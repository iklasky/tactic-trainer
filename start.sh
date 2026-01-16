#!/bin/bash

# Install Python dependencies
echo "Installing Python dependencies..."
pip install -r requirements.txt

# Install Node dependencies and build frontend
echo "Building frontend..."
npm install
npm run build

# Start the Flask backend with gunicorn
echo "Starting Flask backend..."
gunicorn --bind 0.0.0.0:${PORT:-5000} app_v2:app --timeout 120

