#!/bin/bash

# Maximum wait time in seconds (4 minutes)
MAX_WAIT_TIME=240
ELAPSED_TIME=0

while ! ping -c 1 -W 1 8.8.8.8; do
    echo "Waiting for internet connection..."
    sleep 2
    ELAPSED_TIME=$((ELAPSED_TIME + 2))

    if [ "$ELAPSED_TIME" -ge "$MAX_WAIT_TIME" ]; then
        echo "Failed to connect to the internet within 4 minutes. Exiting."
        exit 1
    fi
done

echo "Internet connected!"
exit 0