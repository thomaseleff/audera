#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

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

AUTOSTART_DIRECTORY="/var/lib/dietpi/dietpi-autostart"
AUTOSTART_SCRIPT="$AUTOSTART_DIRECTORY/custom.sh"
REPO_AUTOSTART_SCRIPT="$WORKSPACE/os/dietpi/client/automation/autostart.sh"

# Start console logging
#   The logo must be wrapped in single quotes ' ' to avoid escaping characters
#       due to the nature of having double backslashes, like '\\' in the logo
echo ' ________  ___  ___  ________  _______  ________  ________      '
echo '|\   __  \|\  \|\  \|\   ___ \|\   ___\|\   __  \|\   __  \     '
echo '\ \  \|\  \ \  \\\  \ \  \_|\ \ \  \__|\ \  \|\  \ \  \|\  \    '
echo ' \ \   __  \ \  \\\  \ \  \ \\ \ \   __\\ \      /\ \   __  \   '
echo '  \ \  \ \  \ \  \\\  \ \  \_\\ \ \  \_|_\ \  \  \ \ \  \ \  \  '
echo '   \ \__\ \__\ \______/\ \______/\ \______\ \__\\ _\\ \__\ \__\ '
echo '    \|__|\|__|\|______| \|______| \|______|\|__|\|__|\|__|\|__| '
echo
echo ">>> Running the Audera playback-client setup & installation..."
echo
echo "    Script source {https://raw.githubusercontent.com/thomaseleff/audera/refs/heads/main/os/dietpi/client/automation/setup.sh}."

# Ensure the script is running as root
echo
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}*** CRITICAL: The setup-script must be run as {sudo}.${RESET}" 
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
    python3-venv \
    python3-pip \
    python3-dev \
    build-essential \
    python3-pyaudio \
    portaudio19-dev
echo -e "[  ${GREEN}OK${RESET}  ] Packages installed successfully"

# Clone the git repository
echo
if [ ! -d "$WORKSPACE" ]; then
  echo ">>> Cloning the Git repository"
  git clone -b main "$GIT_REPO_URL" "$WORKSPACE"
else
  echo ">>> Pulling the Git repository"
  cd "$WORKSPACE" && git pull main
fi
echo -e "[  ${GREEN}OK${RESET}  ] Git repository created successfully"

# Replace shairport-sync configuration with the file from the repository
echo
echo ">>> Creating the shairport-sync configuration"
cp "$REPO_SHAIRPORT_CONFIG" "$SHAIRPORT_CONFIG"
chmod 644 "$SHAIRPORT_CONFIG"
echo -e "[  ${GREEN}OK${RESET}  ] shairport-sync configured successfully"

# Create the Python virtual environment
echo
if [ ! -d "$WORKSPACE/.venv" ]; then
  echo ">>> Creating the Python virtual env {$WORKSPACE/.venv}"
  python3 -m venv "$WORKSPACE/.venv"
  echo ">>> Activating the Python virtual env"
  source "$WORKSPACE/.venv/bin/activate"
else
  echo ">>> Activating the Python virtual env"
  source "$WORKSPACE/.venv/bin/activate"
fi
echo -e "[  ${GREEN}OK${RESET}  ] Python virtual env created successfully"

# Install Python requirements
if [ -f "$WORKSPACE/requirements.txt" ]; then
  echo ">>> Installing the Python requirements"
  python3 -m pip install --upgrade pip
  pip3 install -e "$WORKSPACE"
else
  echo -e "${RED} ** ERROR: Failed to build & install audera.${RESET}"
  exit 1
fi
echo -e "[  ${GREEN}OK${RESET}  ] Python requirements installed successfully"

# Configure alsa
echo
echo ">>> Configuring alsa"
SOUNDCARD=$(sed -n '/^[[:blank:]]*CONFIG_SOUNDCARD=/{s/^[^=]*=//p;q}' /boot/dietpi.txt)
echo ">>> Assigning {$SOUNDCARD} as the default soundcard"
/boot/dietpi/func/dietpi-set_hardware soundcard $SOUNDCARD
echo -e "[  ${GREEN}OK${RESET}  ] alsa configured successfully"

# Set up the autostart script
echo
if [ ! -f "$AUTOSTART_DIRECTORY" ]; then
  echo ">>> Creating the custom autostart directory"
  mkdir "$AUTOSTART_DIRECTORY"
  echo ">>> Creating the custom autostart script"
  cp "$REPO_AUTOSTART_SCRIPT" "$AUTOSTART_SCRIPT"
  chmod +x "$AUTOSTART_SCRIPT"
else
  echo -e "${YELLOW}  * WARNING: Autostart script already exists.${RESET}"
fi
echo -e "[  ${GREEN}OK${RESET}  ] Custom autostart script created successfully"

# Log
echo
echo -e "[  ${GREEN}OK${RESET}  ] The Audera playback-client setup & installation completed successfully"

# Restart
echo ">>> Restarting the Audera playback-client in 5 [sec.] ..."
sleep 5
reboot