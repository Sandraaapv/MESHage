#!/usr/bin/env bash
# =========================================================
# MESHage Termux Setup Script
# Installs Python, pip dependencies (Flask, Cryptography),
# Git, and networking tools for Android phones.
# Run once with an active internet connection:
#   bash scripts/setup_termux.sh
# =========================================================

set -e

echo "=================================================="
echo "         MESHage Android Termux Setup             "
echo "=================================================="
echo ""

# 1. Check if running inside Termux or standard Linux
IS_TERMUX=false
if [ -d "/data/data/com.termux" ] || command -v pkg >/dev/null 2>&1; then
    IS_TERMUX=true
    echo "[+] Detected Android Termux environment."
else
    echo "[+] Detected standard Linux/Unix environment."
fi

# 2. Update system package repositories
echo ""
echo "[1/4] Updating package repositories..."
if [ "$IS_TERMUX" = true ]; then
    pkg update -y
elif command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -y
fi
echo "      -> Repositories updated successfully."

# 3. Install core packages: Python, Git, and networking utilities
echo ""
echo "[2/4] Installing core packages (Python, Git, net-tools, iproute2)..."
if [ "$IS_TERMUX" = true ]; then
    # In Termux, python-cryptography provides pre-compiled binaries
    # avoiding slow on-device C/Rust compilation
    pkg install -y python git iproute2 net-tools libffi openssl
    pkg install -y python-cryptography 2>/dev/null || true
elif command -v apt-get >/dev/null 2>&1; then
    sudo apt-get install -y python3 python3-pip git iproute2 net-tools libffi-dev libssl-dev
fi
echo "      -> System packages installed."

# 4. Upgrade pip and install Python packages
echo ""
echo "[3/4] Installing Python packages (Flask, Cryptography)..."
# Locate python and pip binaries
PYTHON_BIN="python3"
if ! command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python"
fi

# Upgrade pip
"$PYTHON_BIN" -m pip install --upgrade pip --quiet 2>/dev/null || true

# Install flask and cryptography
"$PYTHON_BIN" -m pip install flask cryptography --quiet

echo "      -> Python dependencies installed."

# 5. Acquire Termux wake-lock to prevent background suspension
echo ""
echo "[4/4] Configuring background execution..."
if command -v termux-wake-lock >/dev/null 2>&1; then
    termux-wake-lock
    echo "      -> Termux wake-lock acquired (prevents Android sleep)."
else
    echo "      -> (termux-wake-lock utility not found; remember to keep Termux in background whitelist)."
fi

# 6. Verify and summary print
echo ""
echo "=================================================="
echo "               Setup Verification                 "
echo "=================================================="

PYTHON_VER=$("$PYTHON_BIN" --version 2>&1)
GIT_VER=$(git --version 2>&1 || echo "Git not found")
FLASK_VER=$("$PYTHON_BIN" -c "import flask; print('Flask ' + flask.__version__)" 2>&1 || echo "Flask check failed")
CRYPTO_VER=$("$PYTHON_BIN" -c "import cryptography; print('Cryptography ' + cryptography.__version__)" 2>&1 || echo "Cryptography check failed")

echo " [✓] Python:       $PYTHON_VER"
echo " [✓] Git:          $GIT_VER"
echo " [✓] Web Server:   $FLASK_VER"
echo " [✓] Security:     $CRYPTO_VER"
echo ""
echo "=================================================="
echo " Setup complete! What this script did:"
echo " 1. Updated Termux/apt packages"
echo " 2. Installed Python, Git, and network tools"
echo " 3. Installed Flask and Cryptography Python packages"
echo " 4. Acquired Termux wake-lock to keep node alive"
echo ""
echo " Next steps:"
echo " 1. Turn off mobile data & connect to mesh hotspot"
echo " 2. Start this phone's node:"
echo "      bash scripts/run_node.sh"
echo "=================================================="
