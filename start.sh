#!/bin/bash

# Build the frontend
echo "Building frontend..."
npm install
npm run build

# Start the Flask backend with gunicorn
echo "Starting Flask backend..."
gunicorn --bind 0.0.0.0:$PORT app_v2:app --timeout 120

