
#!/usr/bin/env bash
set -e

# Move to the project directory.
cd "$(dirname "$0")"

# Check the Python environment.
if [ ! -f ".venv/bin/python" ]; then
    echo "Error: Python virtual environment not found."
    exit 1
fi

echo "Starting Media Scraper..."
echo "Open: http://127.0.0.1:8000"
echo "Press Ctrl+C to stop."

# Start the application.
exec .venv/bin/python -m uvicorn backend.main:app \
    --app-dir backend \
    --host 127.0.0.1 \
    --port 8000
