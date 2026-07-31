#!/bin/bash
# Double-click to start Direct Lab (app + MongoDB, via Docker Compose) and open the site.
cd "$(dirname "$0")"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker isn't installed. Install Docker (or colima + docker-compose via Homebrew) first."
  read -r -p "Press Enter to close..."
  exit 1
fi

if lsof -ti :4174 >/dev/null 2>&1; then
  open "http://localhost:4174"
  echo "Direct Lab already running - opened http://localhost:4174"
  exit 0
fi

( sleep 3; open "http://localhost:4174" ) &
echo "Starting Direct Lab (app + MongoDB) on http://localhost:4174"
echo "Submissions are saved into Mongo, and into: $(pwd)/submissions"
echo "Keep this window open. Press Ctrl+C to stop."
exec docker-compose up --build
