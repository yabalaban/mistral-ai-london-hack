#!/bin/bash
cd "$(dirname "$0")"
PYTHONPATH=src uv run python -m ensemble
