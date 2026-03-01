#!/bin/bash
# Start backend and frontend dev servers
trap 'kill 0' EXIT

cd "$(dirname "$0")"

(cd backend && PYTHONPATH=src uv run python -m ensemble) &
(cd frontend && npm run dev) &

wait
