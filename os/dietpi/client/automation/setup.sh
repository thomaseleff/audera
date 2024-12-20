#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Add dietpi scripts to path
export PATH=$PATH:/boot/dietpi

# Variables
GIT_REPO_URL="https://github.com/thomaseleff/audera.git"
WORKSPACE="/home/dietpi/audera"
SHAIRPORT_CONFIG="/etc/shairport-sync.conf"
REPO_SHAIRPORT_CONFIG="$WORKSPACE/os/dietpi/client/conf/shairport-sync.conf"

# Ensure the script is running as root
if [[ $EUID -ne 0 ]]; then
   echo "*** CRITICAL: The setup-script must be run as {sudo}." 
   exit 1
fi

# Install software

#   id   software
#   ---  --------------
#   5    alsa
#   7    ffmpeg
#   17   git
#   37   shairport-sync
#   130  python3

echo ">>> Installing optimized software"
dietpi-software install 5 7 17 37 130

echo ">>> Installing build package software"
apt-get update && apt-get install python3-dev build-essential python3-pyaudio portaudio19-dev -y

# Clone the git repository
if [ ! -d "$WORKSPACE" ]; then
  echo ">>> Cloning the Git repository"
  git clone -b main "$GIT_REPO_URL" "$WORKSPACE"
else
  echo ">>> Pulling the Git repository"
  cd "$WORKSPACE" && git pull main
fi

# Replace shairport-sync configuration with the file from the repository
if [ -f "$REPO_SHAIRPORT_CONFIG" ]; then
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
if [ -f "$WORKSPACE/requirements.txt" ]; then
  echo ">>> Installing Python requirements"
  pip3 install "$WORKSPACE"
else
  echo " ** ERROR: Python requirements not found."
  exit 1
fi

echo ">>> Audera-playback-client setup completed successfully."
