#!/bin/bash
# Put a card on the R1's answer screen without asking Claude:  r1-card.sh '{"type":"fact",...}'
ssh -p 8022 -o ConnectTimeout=5 localhost "curl -s -X POST -H 'Content-Type: application/json' --data-binary @- localhost:8765/api/card" <<<"$1"
