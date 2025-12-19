#!/bin/bash
# OmniLocation Installer

set -e

# --- Constants & Configuration ---

readonly REPO_URL="${REPO_URL:-https://github.com/JasperXzy/OmniLocation.git}"
readonly BRANCH="${BRANCH:-main}"
readonly OS_NAME="$(uname -s)"

# Colors
readonly GREEN='\033[0;32m'
readonly BLUE='\033[0;34m'
readonly RED='\033[0;31m'
readonly NC='\033[0m'

# Global State (mutable)
INSTALL_DIR=""
PROJECT_DIR=""
IS_CHINA=false

# --- Logging Functions ---

log_info() {
  echo -e "${GREEN}[INFO] $1${NC}"
}

log_step() {
  echo -e "${BLUE}[STEP] $1${NC}"
}

log_err() {
  echo -e "${RED}[ERROR] $1${NC}"
}

# --- Helper Functions ---

# Executes a command with sudo if the current user is not root.
run_sudo() {
  if [[ "$EUID" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

# Writes content to a file, using sudo if necessary.
# Arguments:
#   $1: filepath
#   $2: content
write_file_sudo() {
  local filepath="$1"
  local content="$2"
  if [[ "$EUID" -eq 0 ]]; then
    echo "$content" > "$filepath"
  else
    echo "$content" | sudo tee "$filepath" > /dev/null
  fi
}

# Detects if the user is in China to use domestic mirrors.
detect_region() {
  log_info "Detecting network region..."
  # Try ip-api.com with a short timeout
  if curl -s --max-time 2 http://ip-api.com/json | grep -q '"countryCode":"CN"'; then
    IS_CHINA=true
    log_info "Region: China (Using domestic mirrors)"
  else
    log_info "Region: Global (Using official sources)"
  fi
}

# Sets up the INSTALL_DIR variable based on OS.
setup_paths() {
  if [[ "$OS_NAME" == "Darwin" ]]; then
    INSTALL_DIR="${INSTALL_DIR:-$HOME/Projects/OmniLocation}"
  else
    # Linux default: /opt/omnilocation
    INSTALL_DIR="${INSTALL_DIR:-/opt/omnilocation}"
  fi
  PROJECT_DIR="$INSTALL_DIR"
}

# Generates the uninstallation script.
generate_uninstaller() {
  local uninstall_script="$INSTALL_DIR/uninstall.sh"
  log_info "Generating uninstaller at $uninstall_script..."

  cat > uninstall_temp.sh <<EOF
#!/bin/bash
# OmniLocation Uninstaller

GREEN='\033[0;32m'
NC='\033[0m'
log_info() { echo -e "\${GREEN}[INFO] \$1\${NC}"; }

OS_NAME=\$(uname -s)

if [[ "\$OS_NAME" == "Darwin" ]]; then
    log_info "Stopping macOS services..."
    launchctl unload ~/Library/LaunchAgents/com.omnilocation.web.plist 2>/dev/null || true
    sudo launchctl unload /Library/LaunchDaemons/com.omnilocation.tunneld.plist 2>/dev/null || true
    
    log_info "Removing service files..."
    rm -f ~/Library/LaunchAgents/com.omnilocation.web.plist
    sudo rm -f /Library/LaunchDaemons/com.omnilocation.tunneld.plist
    
elif [[ "\$OS_NAME" == "Linux" ]]; then
    log_info "Stopping Linux services..."
    sudo systemctl stop omni-web omni-tunneld usbmuxd-proxy netmuxd 2>/dev/null || true
    sudo systemctl disable omni-web omni-tunneld usbmuxd-proxy netmuxd 2>/dev/null || true
    
    log_info "Removing service files..."
    sudo rm -f /etc/systemd/system/omni-web.service
    sudo rm -f /etc/systemd/system/omni-tunneld.service
    sudo rm -f /etc/systemd/system/usbmuxd-proxy.service
    sudo rm -f /etc/systemd/system/netmuxd.service
    sudo systemctl daemon-reload
fi

log_info "Removing application directory: $INSTALL_DIR"
if [[ "$INSTALL_DIR" != "/" ]]; then
    sudo rm -rf "$INSTALL_DIR"
fi

log_info "Uninstall Complete."
EOF

  mv uninstall_temp.sh "$uninstall_script"
  chmod +x "$uninstall_script"
}

# Initializes the .env file from example or defaults.
init_env_file() {
  log_info "Initializing configuration..."
  if [[ ! -f "$PROJECT_DIR/.env" ]]; then
    if [[ -f "$PROJECT_DIR/.env.example" ]]; then
      cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
    else
      cat > "$PROJECT_DIR/.env" <<EOF
TIANDITU_KEY=
HOST=0.0.0.0
PORT=5005
EOF
    fi
    log_info "Created default .env file."
  else
    log_info ".env file already exists. Skipping."
  fi
}

# Gets the local IP address for display.
get_local_ip() {
  local ip_addr=""
  if [[ "$OS_NAME" == "Darwin" ]]; then
    ip_addr=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null)
  else
    ip_addr=$(hostname -I | awk '{print $1}')
  fi
  echo "${ip_addr:-localhost}"
}

# --- Phase 0: Preparation ---

install_git() {
  log_info "Checking requirements..."
  if ! command -v git &> /dev/null; then
    if [[ "$OS_NAME" == "Linux" ]]; then
      log_info "Installing git..."
      run_sudo apt-get update -qq && run_sudo apt-get install -y git
    else
      log_err "Git not found. Please install Xcode Command Line Tools."
      exit 1
    fi
  fi
}

clone_repo() {
  log_info "Preparing installation directory..."
  if [[ "$OS_NAME" == "Linux" ]]; then
    if [[ ! -d "$INSTALL_DIR" ]]; then
      log_info "Creating $INSTALL_DIR..."
      run_sudo mkdir -p "$INSTALL_DIR"
      run_sudo chown "$USER:$USER" "$INSTALL_DIR"
    fi
  else
    mkdir -p "$(dirname "$INSTALL_DIR")"
  fi

  log_info "Fetching source code..."
  if [[ -d "$INSTALL_DIR/.git" ]]; then
    log_info "Updating existing installation at $INSTALL_DIR..."
    git config --global --add safe.directory "$INSTALL_DIR"
    cd "$INSTALL_DIR"
    git fetch origin
    git reset --hard "origin/$BRANCH"
  else
    log_info "Cloning into $INSTALL_DIR..."
    git clone -b "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
  fi
  log_info "Working directory: $INSTALL_DIR"
}

# --- Phase 1: macOS Installation ---

install_macos() {
  log_info "Detected OS: macOS"
  
  # 1. Python Env
  log_info "Setting up Python environment..."
  if [[ ! -d "venv" ]]; then python3 -m venv venv; fi
  source venv/bin/activate
  
  local pip_args="-r requirements.txt"
  if [[ "$IS_CHINA" == "true" ]]; then
    pip_args="$pip_args -i https://pypi.tuna.tsinghua.edu.cn/simple"
  fi
  pip install $pip_args
  
  init_env_file
  
  # 2. Startup Scripts
  log_info "Creating startup scripts..."
  mkdir -p logs
  
  cat > start_tunneld_macos.sh <<EOF
#!/bin/bash
cd "$PROJECT_DIR"
source venv/bin/activate
exec python3 -m pymobiledevice3 remote tunneld
EOF
  chmod +x start_tunneld_macos.sh

  cat > start_web_macos.sh <<EOF
#!/bin/bash
cd "$PROJECT_DIR"
source venv/bin/activate
exec python3 run.py
EOF
  chmod +x start_web_macos.sh

  # 3. Services
  log_info "Configuring Services..."
  
  log_info "Configuring Tunneld (Requires Sudo)..."
  local tunneld_plist="/Library/LaunchDaemons/com.omnilocation.tunneld.plist"
  
  local content_tunneld=$(cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.omnilocation.tunneld</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PROJECT_DIR/start_tunneld_macos.sh</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$PROJECT_DIR/logs/tunneld.stdout.log</string>
    <key>StandardErrorPath</key>
    <string>$PROJECT_DIR/logs/tunneld.stderr.log</string>
    <key>WorkingDirectory</key>
    <string>$PROJECT_DIR</string>
</dict>
</plist>
EOF
)
  echo "$content_tunneld" > com.omnilocation.tunneld.plist
  run_sudo mv com.omnilocation.tunneld.plist "$tunneld_plist"
  run_sudo chown root:wheel "$tunneld_plist"
  
  log_info "Configuring Web App..."
  local web_plist="$HOME/Library/LaunchAgents/com.omnilocation.web.plist"
  
  cat > "$web_plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.omnilocation.web</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PROJECT_DIR/start_web_macos.sh</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$PROJECT_DIR/logs/web.stdout.log</string>
    <key>StandardErrorPath</key>
    <string>$PROJECT_DIR/logs/web.stderr.log</string>
    <key>WorkingDirectory</key>
    <string>$PROJECT_DIR</string>
</dict>
</plist>
EOF

  # 4. Load
  log_info "Loading services..."
  run_sudo launchctl unload "$tunneld_plist" 2>/dev/null || true
  run_sudo launchctl load "$tunneld_plist"
  
  launchctl unload "$web_plist" 2>/dev/null || true
  launchctl load "$web_plist"
  
  generate_uninstaller
  
  log_info "Deployment Complete (macOS)"
  log_info "IMPORTANT: Edit '$PROJECT_DIR/.env' to set your TIANDITU_KEY."
  log_info "Then restart: launchctl kickstart -k gui/$(id -u)/com.omnilocation.web"
  log_info "Web UI: http://$(get_local_ip):5005"
}

# --- Phase 2: Linux Installation ---

install_linux() {
  log_info "Detected OS: Linux (Ubuntu)"

  # 1. Netmuxd Infrastructure
  if pgrep -x "netmuxd" > /dev/null || systemctl is-active --quiet netmuxd; then
    log_info "Netmuxd is already running. Skipping infrastructure build."
  else
    log_info "Setting up Netmuxd infrastructure..."
    
    log_info "Cleaning up system usbmuxd..."
    run_sudo systemctl stop usbmuxd || true
    run_sudo systemctl disable usbmuxd || true
    run_sudo killall -9 usbmuxd || true

    log_info "Installing system dependencies..."
    run_sudo apt-get update -qq
    run_sudo apt-get install -y make automake autoconf libtool pkg-config gcc git socat python3-venv python3-pip
    
    if ! run_sudo apt-get install -y libimobiledevice-utils libimobiledevice-glue-dev libusbmuxd-dev 2>/dev/null; then
        log_info "Newer libimobiledevice packages not found. Trying legacy packages..."
        run_sudo apt-get install -y libimobiledevice-dev libusbmuxd-dev libimobiledevice-utils
    fi

    log_info "Checking Rust environment..."
    if ! command -v rustc &> /dev/null; then
      log_info "Installing Rust..."
      if [[ "$IS_CHINA" == "true" ]]; then
        export RUSTUP_DIST_SERVER="https://mirrors.tuna.tsinghua.edu.cn/rustup"
        export RUSTUP_UPDATE_ROOT="https://mirrors.tuna.tsinghua.edu.cn/rustup/rustup"
      fi
      curl https://sh.rustup.rs -sSf | sh -s -- -y
      source "$HOME/.cargo/env"
    fi
    
    if [[ "$IS_CHINA" == "true" ]]; then
      mkdir -p ~/.cargo
      cat > ~/.cargo/config.toml <<EOF
[source.crates-io]
replace-with = 'rsproxy-sparse'
[source.rsproxy]
registry = "https://rsproxy.cn/crates.io-index"
[source.rsproxy-sparse]
registry = "sparse+https://rsproxy.cn/index/"
[registries.rsproxy]
index = "https://rsproxy.cn/crates.io-index"
[net]
git-fetch-with-cli = true
EOF
    fi

    local netmuxd_build_dir="$HOME/.omnilocation_build/netmuxd"
    log_info "Compiling Netmuxd..."
    
    mkdir -p "$netmuxd_build_dir"
    if [[ -d "$netmuxd_build_dir/.git" ]]; then
      cd "$netmuxd_build_dir" && git pull
    else
      git clone https://github.com/jkcoxson/netmuxd.git "$netmuxd_build_dir"
      cd "$netmuxd_build_dir"
    fi

    log_info "Patching source code..."
    sed -i 's/idevice.start_session(&pairing_file)/idevice.start_session(\&pairing_file, false)/g' src/heartbeat.rs
    
    cargo install --path .

    log_info "Configuring base services (Netmuxd + Proxy)..."
    local cargo_bin_dir="$HOME/.cargo/bin"
    
    local content_netmuxd=$(cat <<EOF
[Unit]
Description=Netmuxd
After=network.target
[Service]
ExecStart=$cargo_bin_dir/netmuxd --host 127.0.0.1 --port 27015 --disable-unix
Restart=always
User=root
[Install]
WantedBy=multi-user.target
EOF
)
    write_file_sudo "/etc/systemd/system/netmuxd.service" "$content_netmuxd"

    local content_proxy=$(cat <<EOF
[Unit]
Description=Socat Proxy
After=netmuxd.service
Requires=netmuxd.service
[Service]
ExecStartPre=/bin/rm -f /var/run/usbmuxd
ExecStart=/usr/bin/socat UNIX-LISTEN:/var/run/usbmuxd,fork,mode=777 TCP:127.0.0.1:27015
Restart=always
User=root
[Install]
WantedBy=multi-user.target
EOF
)
    write_file_sudo "/etc/systemd/system/usbmuxd-proxy.service" "$content_proxy"

    run_sudo systemctl daemon-reload
    run_sudo systemctl enable netmuxd usbmuxd-proxy
    run_sudo systemctl restart netmuxd
    sleep 2
    run_sudo systemctl restart usbmuxd-proxy
  fi

  # 2. App Deployment
  log_info "Deploying OmniLocation App..."
  cd "$PROJECT_DIR"

  if [[ ! -d "venv" ]]; then python3 -m venv venv; fi
  source venv/bin/activate
  
  local pip_args="-r requirements.txt"
  if [[ "$IS_CHINA" == "true" ]]; then
    pip_args="$pip_args -i https://pypi.tuna.tsinghua.edu.cn/simple"
  fi
  pip install $pip_args
  
  init_env_file
  mkdir -p logs

  cat > start_tunneld_linux.sh <<EOF
#!/bin/bash
cd "$PROJECT_DIR"
source venv/bin/activate
exec python3 -m pymobiledevice3 remote tunneld
EOF
  chmod +x start_tunneld_linux.sh

  local content_omni_tunneld=$(cat <<EOF
[Unit]
Description=OmniLocation Tunneld
After=usbmuxd-proxy.service network-online.target
[Service]
Type=simple
WorkingDirectory=$PROJECT_DIR
ExecStart=$PROJECT_DIR/start_tunneld_linux.sh
Restart=always
User=root
[Install]
WantedBy=multi-user.target
EOF
)
  write_file_sudo "/etc/systemd/system/omni-tunneld.service" "$content_omni_tunneld"

  cat > start_web_linux.sh <<EOF
#!/bin/bash
cd "$PROJECT_DIR"
source venv/bin/activate
exec python3 run.py
EOF
  chmod +x start_web_linux.sh

  local content_omni_web=$(cat <<EOF
[Unit]
Description=OmniLocation Web
After=omni-tunneld.service
[Service]
Type=simple
WorkingDirectory=$PROJECT_DIR
ExecStart=$PROJECT_DIR/start_web_linux.sh
Restart=always
User=root
[Install]
WantedBy=multi-user.target
EOF
)
  write_file_sudo "/etc/systemd/system/omni-web.service" "$content_omni_web"

  # 3. Launch
  log_info "Launching services..."
  run_sudo systemctl daemon-reload
  run_sudo systemctl enable omni-tunneld omni-web
  run_sudo systemctl restart omni-tunneld
  sleep 2
  run_sudo systemctl restart omni-web

  generate_uninstaller

  sleep 2
  if systemctl is-active --quiet omni-web; then
    log_info "Deployment Complete (Linux)"
    log_info "IMPORTANT: Edit '$PROJECT_DIR/.env' to set your TIANDITU_KEY."
    log_info "Then restart: sudo systemctl restart omni-web"
    log_info "IP: http://$(get_local_ip):5005"
  else
    log_err "Service failed. Check logs: journalctl -u omni-web"
  fi
}

# --- Main Execution ---

detect_region
setup_paths
install_git
clone_repo

if [[ "$OS_NAME" == "Darwin" ]]; then
  install_macos
elif [[ "$OS_NAME" == "Linux" ]]; then
  install_linux
else
  log_err "Unsupported OS: $OS_NAME"
  exit 1
fi
