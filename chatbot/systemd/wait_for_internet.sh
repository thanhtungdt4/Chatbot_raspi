#!/bin/bash

while ! ping -c 1 -W 1 8.8.8.8; do
    echo "Waiting for internet connection..."
    sleep 2
done

echo "Internet connected!"
exit 0