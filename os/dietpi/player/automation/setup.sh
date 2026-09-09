#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Parse arguments
if [ -n "$1" ]; then
    GIT_BRANCH="$1"
else
    GIT_BRANCH="main"
fi

AUDIO_DEVICE="$2"

# Whether to reboot at the end (default 1). provision.sh passes 0 for --no-reboot / --wipe-networks
#   so the operator can inspect the device; an explicit argument rather than provision.sh editing
#   these lines out of this script by regex.
REBOOT="${3:-1}"

# Operator hostname (empty ⇒ MAC-derived) and opt-in WiFi carry-over (0/1), passed as positional
#   args rather than provision.sh regex-editing this script.
HOSTNAME_ARG="${4:-}"
CARRY_WIFI="${5:-0}"

# Fetch and load shared config-injection helpers
curl -fsSL "https://raw.githubusercontent.com/Eleff-org/audera/${GIT_BRANCH}/os/dietpi/lib/config.sh" -o /tmp/audera_config_lib.sh
source /tmp/audera_config_lib.sh

# Fetch and load shared install/setup helpers
curl -fsSL "https://raw.githubusercontent.com/Eleff-org/audera/${GIT_BRANCH}/os/dietpi/lib/common.sh" -o /tmp/audera_common_lib.sh
source /tmp/audera_common_lib.sh

# Variables
GIT_REPO_URL="https://github.com/Eleff-org/audera.git"
CAMILLADSP_VERSION="3.0.1"
CAMILLADSP_CONFIG_DIR="/etc/camilladsp"
CAMILLADSP_CONFIG="$CAMILLADSP_CONFIG_DIR/config.yml"


# Start console logging

print_logo
echo
echo ">>> Running the Audera player setup & installation..."
echo
echo "    Script source {https://raw.githubusercontent.com/Eleff-org/audera/${GIT_BRANCH}/os/dietpi/player/automation/setup.sh}."

# Ensure the script is running as root
require_root

# Install build packages
echo
echo ">>> Installing build packages"
apt-get update && \
apt-get install -y \
    wget \
    curl \
    git \
    network-manager \
    dnsmasq \
    alsa-utils \
    avahi-daemon \
    snapclient \
    python3.13 \
    python3-dev \
    build-essential && \
apt-get clean && \
rm -rf /var/lib/apt/lists/*
echo -e "[  ${GREEN}OK${RESET}  ] Packages installed successfully"

# Load ALSA loopback module (needed for CamillaDSP ↔ Snapclient audio path)
# index=7 keeps the loopback off hw:0 so physical card indices are stable
echo
echo ">>> Enabling ALSA loopback module"
setup_alsa_loopback
echo -e "[  ${GREEN}OK${RESET}  ] ALSA loopback module enabled"

# Configure audio device dtoverlay (opt-in; leaves existing dtoverlay untouched if unset)
echo
configure_audio_device "$AUDIO_DEVICE"

# Install CamillaDSP
echo
echo ">>> Installing CamillaDSP v${CAMILLADSP_VERSION}"
install_camilladsp "$CAMILLADSP_VERSION"
echo -e "[  ${GREEN}OK${RESET}  ] CamillaDSP installed successfully"

# Install uv
echo
echo ">>> Installing uv"
install_uv
echo -e "[  ${GREEN}OK${RESET}  ] uv installed successfully"

# Install a Rust toolchain on armv6 — pydantic-core / orjson / watchfiles ship no armv6
#   wheels, so uv cargo-builds them from source and needs a compiler on PATH.
if [ "$(uname -m)" = "armv6l" ]; then
    echo
    echo ">>> Installing Rust toolchain (armv6 has no prebuilt wheels)"
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
    . "$HOME/.cargo/env"
    export CARGO_BUILD_JOBS=1   # ponytail: 512MB RAM, single core — parallel cargo OOMs
    echo -e "[  ${GREEN}OK${RESET}  ] Rust toolchain installed"
fi

# Install audera CLI
echo
echo ">>> Installing audera"
install_audera_cli "$GIT_REPO_URL" "$GIT_BRANCH"
echo -e "[  ${GREEN}OK${RESET}  ] audera installed successfully"

# Write CamillaDSP configuration
echo
echo ">>> Creating the CamillaDSP configuration"
audera player conf camilladsp.yml \
    --playback-format "$(camilladsp_playback_format "$AUDIO_DEVICE")" \
    --playback-device "$(camilladsp_playback_device "$AUDIO_DEVICE")" > "$CAMILLADSP_CONFIG"
chmod 644 "$CAMILLADSP_CONFIG"
echo -e "[  ${GREEN}OK${RESET}  ] CamillaDSP configured successfully"

# Install systemd service units
#   Each unit is rendered by the CLI and redirected into place. `snapclient.service` is role-branched:
#   the player's has no `--host` and no ordering after a local snapserver, since it reaches one over the
#   network. A render that exits non-zero leaves a zero-byte unit and `set -e` aborts before `systemctl`.
echo
echo ">>> Installing systemd service units"

# snapclient service — outputs to ALSA loopback; CamillaDSP reads from the paired device
audera player conf snapclient.service    > /etc/systemd/system/snapclient.service

# camilladsp service — captures from ALSA loopback, plays to physical DAC (hw:0)
audera player conf camilladsp.service    > /etc/systemd/system/camilladsp.service

# audera-player service — one-shot that starts audera player on boot
audera player conf audera-player.service > /etc/systemd/system/audera-player.service

systemctl daemon-reload
systemctl enable snapclient camilladsp audera-player

# Start the backends now, but only enable `audera-player`, do not start it here. `audera-player`
#   runs the boot-time connectivity gate that launches the interactive WiFi wizard when offline;
#   started here — before `setup_network_manager` (line 154) and the WiFi carry-over (line 158) —
#   the gate sees no network and drops into the wizard, and the oneshot `start` blocks on it, so the
#   flash hangs mid-install. Enabled here, it starts on the post-provision reboot with the network
#   up and exits cleanly.
systemctl start snapclient camilladsp
echo -e "[  ${GREEN}OK${RESET}  ] systemd service units installed successfully"

# Purge ifupdown

# ifupdown will conflict with Network-Manager if
#   both are installed. Comment out all configuration
#   from `/etc/network/interfaces`.

echo
echo ">>> Purging ifupdown"
purge_ifupdown
echo -e "[  ${GREEN}OK${RESET}  ] ifupdown purged successfully"

# Configure hostname (operator-supplied, else MAC-derived fallback)
echo
echo ">>> Configuring hostname"
NEW_HOSTNAME=$(configure_hostname "$HOSTNAME_ARG")
echo -e "[  ${GREEN}OK${RESET}  ] Hostname configured as {${NEW_HOSTNAME}}"

# Setup network-manager

# Network-manager should manage all network devices,
#   even those configured within `/etc/network/interfaces`.

echo
echo ">>> Setting up network-manager"
setup_network_manager
echo -e "[  ${GREEN}OK${RESET}  ] Network-manager setup successfully"

# Opt-in WiFi credential carry-over (default off keeps the setup wizard tested)
if [[ "$CARRY_WIFI" == "1" ]]; then
    echo
    echo ">>> Carrying over existing WiFi credentials"
    migrate_wifi_credentials
    echo -e "[  ${GREEN}OK${RESET}  ] WiFi credential carry-over completed"
fi

# Disable WiFi power save globally
disable_wifi_powersave
echo -e "[  ${GREEN}OK${RESET}  ] WiFi power save disabled globally"

# Disable NetworkManager connectivity checking (the setup AP has no upstream internet by design)
disable_connectivity_check
echo -e "[  ${GREEN}OK${RESET}  ] NetworkManager connectivity check disabled"

# Setup dnsmasq
echo
echo ">>> Setting up dnsmasq"
systemctl disable dnsmasq
echo -e "[  ${GREEN}OK${RESET}  ] dnsmasq setup successfully"

# Write boot banner
echo
echo ">>> Writing boot banner"
write_boot_banner
echo -e "[  ${GREEN}OK${RESET}  ] Boot banner written"

# Log
echo
echo -e "[  ${GREEN}OK${RESET}  ] The Audera player setup & installation completed successfully"

# Restart
if [[ "${REBOOT:-1}" == "1" ]]; then
    echo
    echo ">>> Restarting the Audera player in 5 [sec.] ..."
    sleep 5
    reboot
fi
