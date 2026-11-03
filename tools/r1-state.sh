#!/bin/bash
# Print the voice UI's current state (JSON) from the R1.
ssh -p 8022 -o ConnectTimeout=5 localhost 'curl -s -m 2 -N localhost:8765/api/events | grep -m1 "^data:" | cut -c7-'
