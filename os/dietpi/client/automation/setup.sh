#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Add dietpi scripts to path
export PATH=$PATH:/boot/dietpi

# Setup color formatting
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
RESET='\033[0m'

# Variables
GIT_REPO_URL="https://github.com/thomaseleff/audera.git"
WORKSPACE="/home/dietpi/audera"
SHAIRPORT_CONFIG="/etc/shairport-sync.conf"
REPO_SHAIRPORT_CONFIG="$WORKSPACE/os/dietpi/client/conf/shairport-sync.conf"

AUTOSTART_SCRIPT="/var/lib/dietpi/dietpi-autostart/custom.sh"
REPO_AUTOSTART_SCRIPT="$WORKSPACE/os/dietpi/client/automation/autostart.sh"

# Start console logging
echo -e " ________  ___  ___  ________  _______  ________  ________      "
echo -e "|\   __  \|\  \|\  \|\   ___ \|\   ___\|\   __  \|\   __  \     "
echo -e "\ \  \|\  \ \  \\\  \ \  \_|\ \ \  \__|\ \  \|\  \ \  \|\  \    "
echo -e " \ \   __  \ \  \\\  \ \  \ \\ \ \   __\\ \      /\ \   __  \   "
echo -e "  \ \  \ \  \ \  \\\  \ \  \_\\ \ \  \_|_\ \  \  \ \ \  \ \  \  "
echo -e "   \ \__\ \__\ \______/\ \______/\ \______\ \__\\ _\\ \__\ \__\ "
echo -e "    \|__|\|__|\|______| \|______| \|______|\|__|\|__|\|__|\|__| "
echo
echo ">>> Running the Audera playback-client setup & installation..."
echo
echo "    Script source {https://raw.githubusercontent.com/thomaseleff/audera/refs/heads/main/os/dietpi/client/automation/setup.sh}."

# Ensure the script is running as root
echo
if [[ $EUID -ne 0 ]]; then
   echo "${RED}*** CRITICAL: The setup-script must be run as {sudo}.${RESET}" 
   exit 1
fi

# Install build packages
echo ">>> Installing build packages"
apt-get update && \
apt-get install -y \
    alsa-utils \
    ffmpeg \
    shairport-sync \
    git \
    python3.11 \
    python3-dev \
    build-essential \
    python3-pyaudio \
    portaudio19-dev

# Clone the git repository
echo
if [ ! -d "$WORKSPACE" ]; then
  echo ">>> Cloning the Git repository"
  git clone -b main "$GIT_REPO_URL" "$WORKSPACE"
else
  echo ">>> Pulling the Git repository"
  cd "$WORKSPACE" && git pull main
fi

# Replace shairport-sync configuration with the file from the repository
echo
if [ -f "$SHAIRPORT_CONFIG" ]; then
  echo ">>> Updating the shairport-sync configuration"
  cp "$REPO_SHAIRPORT_CONFIG" "$SHAIRPORT_CONFIG"
  chmod 644 "$SHAIRPORT_CONFIG"
else
  echo ">>> Using default shairport-sync configuration"
fi

# Restart shairport-sync
echo ">>> Restarting shairport-sync"
systemctl restart shairport-sync

# Install Python requirements
echo
if [ -f "$WORKSPACE/requirements.txt" ]; then
  echo ">>> Installing Python requirements"
  pip3 install "$WORKSPACE" --root-user-action
else
  echo "${RED} ** ERROR: Failed to build & install audera.${RESET}"
  exit 1
fi

# Set up the autostart script
echo
if [ ! -f "$SHAIRPORT_CONFIG" ]; then
  echo ">>> Creating the custom autostart script"
  cp "$REPO_AUTOSTART_SCRIPT" "$AUTOSTART_SCRIPT"
  chmod +x "$AUTOSTART_SCRIPT"
else
  echo "${YELLOW}  * WARNING: Autostart script not found.${RESET}"
fi

# Log
echo
echo "[ ${GREEN}ok${RESET} ] The Audera playback-client setup & installation completed successfully"

# Restart
echo ">>> Restarting the Audera playback-client"
sleep 3
reboot