#!/bin/bash
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then
    python3 start.py
    result=$?
else
    echo "Install Python 3.10 or newer from python.org, then try again."
    result=1
fi
if [ "$result" -ne 0 ]; then
    read -r -p "Press Enter to close..." _reply
fi
exit "$result"
