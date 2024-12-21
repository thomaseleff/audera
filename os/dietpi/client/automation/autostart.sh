#!/bin/bash
# DietPi-AutoStart custom script
# Location: /var/lib/dietpi/dietpi-autostart/custom.sh

# Exit immediately if a command exits with a non-zero status
set -e

# Setup color formatting
RED='\033[0;31m'
RESET='\033[0m'

# Variables
WORKSPACE="/home/dietpi/audera"

# Activate the python environment
if [ -f "$WORKSPACE/.venv/bin/activate" ]; then
  source "$WORKSPACE/.venv/bin/activate"
else
   echo -e "${RED}*** CRITICAL: The Python virtual environment does not exist.${RESET}" 
   exit 1
fi

audera run client
exit 0