#!/bin/bash

# Shared install/setup helpers for Audera device setup scripts.
# Sourced by player/automation/setup.sh and streamer/automation/setup.sh.

# Color formatting
# shellcheck disable=SC2034  # GREEN is read by scripts that source this file
RED='\033[0;31m'
GREEN='\033[0;32m'
RESET='\033[0m'

# Prints the Audera ASCII-art logo to the console
# The logo must be wrapped in single quotes ' ' to avoid escaping characters
#   due to the nature of having double backslashes, like '\\' in the logo
print_logo() {
    echo ' ________  ___  ___  ________  _______  ________  ________      '
    echo '|\   __  \|\  \|\  \|\   ___ \|\   ___\|\   __  \|\   __  \     '
    echo '\ \  \|\  \ \  \\\  \ \  \_|\ \ \  \__|\ \  \|\  \ \  \|\  \    '
    echo ' \ \   __  \ \  \\\  \ \  \ \\ \ \   __\\ \      /\ \   __  \   '
    echo '  \ \  \ \  \ \  \\\  \ \  \_\\ \ \  \_|_\ \  \  \ \ \  \ \  \  '
    echo '   \ \__\ \__\ \______/\ \______/\ \______\ \__\\ _\\ \__\ \__\ '
    echo '    \|__|\|__|\|______| \|______| \|______|\|__|\|__|\|__|\|__| '
}

# Ensures the script is running as root
require_root() {
    if [[ $EUID -ne 0 ]]; then
        echo -e "${RED}*** CRITICAL: The setup-script must be run as {sudo}.${RESET}"
        exit 1
    fi
}

# Loads the ALSA loopback module (needed for CamillaDSP <-> Snapclient audio path)
# index=7 keeps the loopback off hw:0 so physical card indices are stable
setup_alsa_loopback() {
    echo "options snd-aloop index=7" > /etc/modprobe.d/snd-aloop.conf
    echo "snd-aloop" > /etc/modules-load.d/snd-aloop.conf
    modprobe snd-aloop
}

# Downloads, extracts, and installs the given CamillaDSP version to /usr/local/bin
install_camilladsp() {
    local version="$1"
    local archive
    case "$(uname -m)" in
        armv6l)  archive="camilladsp-linux-armv6.tar.gz" ;;
        armv7l)  archive="camilladsp-linux-armv7.tar.gz" ;;
        *)       archive="camilladsp-linux-aarch64.tar.gz" ;;
    esac
    local url="https://github.com/HEnquist/camilladsp/releases/download/v${version}/${archive}"
    wget -q "$url" -O "/tmp/${archive}"
    tar -xzf "/tmp/${archive}" -C /usr/local/bin/
    chmod +x /usr/local/bin/camilladsp
    rm "/tmp/${archive}"
    mkdir -p /etc/camilladsp
}

# Installs uv if it is not already present
install_uv() {
    if ! command -v uv &> /dev/null; then
        curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
    fi
}

# Installs the audera CLI from the given git repo/branch.
#
# piwheels ships prebuilt ARM wheels (incl. armv6l) for the Rust deps that PyPI has
# only as sdists — pydantic-core, orjson, watchfiles — so uv downloads them instead of
# cargo-building on-device. `unsafe-best-match` is uv's scary name for pip-normal
# behaviour: consider PyPI + piwheels together and pick the best wheel, rather than
# stopping at the first index (PyPI, sdist-only). No-op off ARM; dev machines are
# unaffected since this lives in the device installer, not pyproject.
install_audera_cli() {
    local repo_url="$1"
    local branch="$2"
    UV_TOOL_BIN_DIR=/usr/local/bin uv tool install --reinstall \
        --index-strategy unsafe-best-match \
        --extra-index-url https://www.piwheels.org/simple \
        "git+${repo_url}@${branch}"
    export PATH="/usr/local/bin:$PATH"
}

# Purges ifupdown, which will conflict with Network-Manager if both are installed,
#   and comments out all configuration from `/etc/network/interfaces`
purge_ifupdown() {
    if systemctl is-active --quiet ifupdown; then
        systemctl stop ifupdown
        systemctl disable ifupdown
    fi
    apt-get purge -y ifupdown
    sed -i '/^[[:space:]]*[^#[:space:]]/s/^/# /' /etc/network/interfaces
}

# Sets up network-manager to manage all network devices, even those configured
#   within `/etc/network/interfaces`
setup_network_manager() {
    sed -i '/^\[ifupdown\]/,/^\[/s/managed=false/managed=true/' /etc/NetworkManager/NetworkManager.conf
    systemctl enable NetworkManager
    systemctl start NetworkManager
    nmcli networking on
}

# Opt-in WiFi carry-over: migrates the SSID/PSK from `wpa_supplicant.conf` into a NetworkManager
#   profile so the device rejoins its network without the setup wizard. Mirrors `netifaces.connect`.
#   No credentials -> notice + `return 0`, so it never trips `set -e` when called bare (Trap #2).
migrate_wifi_credentials() {
    local conf='/etc/wpa_supplicant/wpa_supplicant.conf'
    local ssid psk

    if [[ ! -f "$conf" ]]; then
        echo ">>> No {${conf}} found; skipping WiFi credential carry-over"
        echo -e "[  ${GREEN}OK${RESET}  ] No WiFi credentials to migrate"
        return 0
    fi

    # Isolate the first `network={ ... }` block so the ssid and psk come from the SAME network;
    #   parsing each field independently across the file can pair one block's ssid with another's psk.
    local block
    block=$(awk '/^[[:space:]]*network[[:space:]]*=[[:space:]]*\{/{f=1} f{print} f&&/\}/{exit}' "$conf")

    # Parse the ssid / psk from that first block.
    ssid=$(printf '%s\n' "$block" | grep -m1 -oP '^\s*ssid="\K[^"]*' || true)
    psk=$(printf '%s\n' "$block" | grep -m1 -oP '^\s*psk="\K[^"]*' || true)
    if [[ -z "$psk" ]]; then
        # A pre-computed PSK is stored unquoted as 64 hex chars; nmcli takes it verbatim.
        psk=$(printf '%s\n' "$block" | grep -m1 -oP '^\s*psk=\K[0-9a-fA-F]{64}' || true)
    fi

    if [[ -z "$ssid" ]]; then
        echo ">>> No WiFi SSID found in {${conf}}; skipping WiFi credential carry-over"
        echo -e "[  ${GREEN}OK${RESET}  ] No WiFi credentials to migrate"
        return 0
    fi

    # Delete any same-named profile then re-create it, mirroring `netifaces.connect`.
    nmcli connection delete "$ssid" 2> /dev/null || true

    local -a add_args=(connection add type wifi con-name "$ssid" ssid "$ssid" connection.autoconnect yes)
    if [[ -n "$psk" ]]; then
        add_args+=(wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$psk")
    fi

    if ! nmcli "${add_args[@]}"; then
        echo ">>> Failed to create NetworkManager profile for {${ssid}}; falling back to the setup wizard"
        echo -e "[  ${GREEN}OK${RESET}  ] No WiFi credentials migrated"
        return 0
    fi

    echo ">>> Migrated WiFi network {${ssid}} from wpa_supplicant into NetworkManager"
    return 0
}

# Disables WiFi power save globally
disable_wifi_powersave() {
    mkdir -p /etc/NetworkManager/conf.d
    cat > /etc/NetworkManager/conf.d/wifi-powersave.conf <<'EOF'
[connection]
wifi.powersave = 2
EOF
}

# Disables NetworkManager's connectivity check. The setup AP has no upstream internet by design,
#   so the check only churns, repeatedly marking ap0/wlan0 "limited". Standard for an AP portal.
disable_connectivity_check() {
    mkdir -p /etc/NetworkManager/conf.d
    cat > /etc/NetworkManager/conf.d/connectivity.conf <<'EOF'
[connectivity]
enabled=false
EOF
}

# Sets the hostname, appends it to /etc/hosts, and echoes it back. Shared by both branches.
_apply_hostname() {
    local new_hostname="$1"
    hostnamectl set-hostname "$new_hostname"
    echo "127.0.1.1   $new_hostname" >> /etc/hosts
    echo "$new_hostname"
}

# Derives the hostname from the eth0 (else wlan0) MAC and applies it. The `configure_hostname`
#   fallback when no operator name is given.
derive_hostname_from_mac() {
    local mac short new_hostname
    mac=$(cat /sys/class/net/eth0/address 2>/dev/null || cat /sys/class/net/wlan0/address)
    short=$(echo "$mac" | tr -d ':' | tail -c 7)
    new_hostname="audera-${short}"
    _apply_hostname "$new_hostname"
}

# Applies $1 as the hostname when non-empty (operator's friendly name, which flows to DHCP and the
#   setup-hotspot SSID), else the MAC-derived default. Echoes the applied name.
configure_hostname() {
    local explicit="$1"
    if [[ -n "$explicit" ]]; then
        _apply_hostname "$explicit"
    else
        derive_hostname_from_mac
    fi
}

# Writes the boot banner printed at login
write_boot_banner() {
    cat > /etc/profile.d/50-audera-banner.sh <<'EOF'
#!/bin/sh
printf '\033[36m'
cat << 'LOGO'
 ________  ___  ___  ________  _______  ________  ________
|\   __  \|\  \|\  \|\   ___ \|\   ___\|\   __  \|\   __  \
\ \  \|\  \ \  \\\  \ \  \_|\ \ \  \__|\ \  \|\  \ \  \|\  \
 \ \   __  \ \  \\\  \ \  \ \\ \ \   __\\ \      /\ \   __  \
  \ \  \ \  \ \  \\\  \ \  \_\\ \ \  \_|_\ \  \  \ \ \  \ \  \
   \ \__\ \__\ \______/\ \______/\ \______\ \__\\ _\\ \__\ \__\
    \|__|\|__|\|______| \|______| \|______|\|__|\|__|\|__|\|__|
LOGO
printf '\033[0m\n'
printf '  \033[1maudera\033[0m — composable audio for your hardware\n\n'
printf '  \033[33m!\033[0m Do not use \033[1mdietpi-config\033[0m to manage WiFi or audio hardware.\n'
printf '    WiFi:   nmcli device wifi connect <SSID> password <PASS>\n'
printf '    Audio:  aplay -l  |  nano /boot/firmware/config.txt\n\n'
EOF
    chmod +x /etc/profile.d/50-audera-banner.sh
}
