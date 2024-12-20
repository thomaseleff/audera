#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Variables
GIT_REPO_URL="https://github.com/thomaseleff/audera.git"
CLONE_DIR="/home/dietpi/audera"
SHAIRPORT_CONFIG="/etc/shairport-sync.conf"
REPO_SHAIRPORT_CONFIG="$CLONE_DIR/os/dietpi/client/conf/shairport-sync.conf"

# Ensure the script is running as root
if [[ $EUID -ne 0 ]]; then
   echo "*** CRITICAL: The setup-script must be run as {sudo}." 
   exit 1
fi

# Clone the Git repository if not already cloned
if [ ! -d "$CLONE_DIR" ]; then
  echo ">>> Cloning the Git repository"
  git clone -b main "$GIT_REPO_URL" "$CLONE_DIR"
else
  echo ">>> Pulling the Git repository"
  cd "$CLONE_DIR" && git pull main
fi

# Check if shairport-sync is installed and install if necessary
if ! command -v shairport-sync &> /dev/null; then
  echo ">>> Installing shairport-sync"
  apt-get update && apt-get install -y shairport-sync
fi

# Replace shairport-sync configuration with the file from the repository
if [ -f "$REPO_CONFIG_FILE" ]; then
  echo ">>> Updating the shairport-sync configuration"
  cp "$REPO_CONFIG_FILE" "$SHAIRPORT_CONFIG"
  chmod 644 "$SHAIRPORT_CONFIG"
else
  echo ">>> Using default configuration"
fi

# Restart shairport-sync
echo ">>> Restarting shairport-sync"
systemctl restart shairport-sync

# Install Python requirements
if [ -f "$CLONE_DIR/requirements.txt" ]; then
  echo ">>> Installing Python requirements"
  pip3 install "$CLONE_DIR"
else
  echo " ** ERROR: Python requirements not found."
  exit 1
fi

# Run the Python script
if [ -f "$CLONE_DIR/$PYTHON_SCRIPT" ]; then
  echo "Running Python script..."
  python3 "$CLONE_DIR/$PYTHON_SCRIPT"
else
  echo "Python script $PYTHON_SCRIPT not found in repository root."
fi

echo ">>> Audera-playback-client setup completed successfully."
