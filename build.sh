#!/usr/bin/env bash
# Render Build Script — builds both frontend and backend

set -o errexit  # Exit on error

echo "=== [1/3] Installing Node dependencies ==="
npm install

echo "=== [2/3] Building React frontend ==="
npm run build

echo "=== [3/3] Installing Python dependencies ==="
pip install --upgrade pip
pip install -r requirements.txt

echo "=== ✅ Build complete ==="
