#!/bin/bash
# Double-click to start the Direct Lab intake server and open the site.
cd "$(dirname "$0")"

# already running? just open the browser
if lsof -ti :4174 >/dev/null 2>&1; then
  open "http://localhost:4174"
  echo "Direct Lab already running - opened http://localhost:4174"
  exit 0
fi

( sleep 1; open "http://localhost:4174" ) &
echo "Starting Direct Lab on http://localhost:4174"
echo "Submissions are saved into: $(pwd)/submissions"
echo "Keep this window open. Press Ctrl+C to stop."
exec python3 server.py
