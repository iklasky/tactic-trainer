# Multi-stage build for Node.js frontend
FROM node:18-slim AS frontend-builder

WORKDIR /app

# Copy package files and install dependencies
COPY package*.json ./
COPY tsconfig*.json ./
COPY vite.config.ts ./
COPY postcss.config.js ./
COPY tailwind.config.js ./
COPY index.html ./

RUN npm install

# Copy source files
COPY src/ ./src/

# Build frontend
RUN npm run build

# Final stage with Python
FROM python:3.9-slim

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

# Copy Python files
COPY app_v2.py .
COPY config.py .
COPY chess_analyzer*.py ./

# Copy data files
COPY analysis_results_v5.fixed4.csv .
COPY fetched_games_v5.json .

# Copy built frontend from previous stage
COPY --from=frontend-builder /app/dist ./dist

# Set environment variable
ENV PYTHONUNBUFFERED=1

# Expose port (platform will provide $PORT)
EXPOSE 8000

# Start command (avoid PATH dependency on gunicorn)
CMD ["sh", "-c", "python -m gunicorn app_v2:app --bind 0.0.0.0:${PORT:-8000} --timeout 120 --workers 2"]
