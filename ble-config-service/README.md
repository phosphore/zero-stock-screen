# ZeroStock BLE Config Service

This folder contains the Bluetooth Low Energy (BLE) configuration service, web UI, and systemd unit for provisioning a ZeroStock screen on a Raspberry Pi Zero W running Raspberry Pi OS 13 (Debian Bookworm, 32-bit legacy).

## Contents

- `ble_config.py`: Bluezero-based GATT peripheral daemon.
- `config.html`: Mobile-friendly Web Bluetooth configuration page.
- `zero-stock-ble-config.service`: systemd unit to start the BLE daemon on boot.

## Raspberry Pi OS 13 (32-bit legacy) install

> Run the following as `root` or with `sudo`.

### 1) Install system packages

```sh
sudo apt update
sudo apt install -y bluetooth bluez python3 python3-pip python3-venv libglib2.0-dev
sudo apt update
sudo apt install -y bluez bluetooth python3-gi python3-gi-cairo python3-dbus
sudo systemctl enable --now bluetooth
```

### 2) Enable Bluetooth service

```sh
sudo systemctl enable bluetooth
sudo systemctl start bluetooth
```

### 3) Install Python dependency (bluezero)

```sh
python3 -m pip install --upgrade pip
python3 -m pip install bluezero
```

### 4) Deploy the service files

```sh
sudo mkdir -p /home/pi/zero-stock-screen/ble-config-service
sudo cp /home/pi/zero-stock-screen/ble-config-service/ble_config.py /home/pi/zero-stock-screen/ble-config-service/ble_config.py
sudo cp /home/pi/zero-stock-screen/ble-config-service/config.html /home/pi/zero-stock-screen/ble-config-service/config.html
sudo cp /home/pi/zero-stock-screen/ble-config-service/zero-stock-ble-config.service /etc/systemd/system/zero-stock-ble-config.service
```

### 5) Start on boot

```sh
sudo systemctl daemon-reload  
sudo systemctl enable zero-stock-ble-config.service
sudo systemctl start zero-stock-ble-config.service
```

### 6) Check logs

```sh
sudo journalctl -u zero-stock-ble-config.service -f
```

## Usage

- Open `config.html` from an HTTPS server or `localhost` (Web Bluetooth requirement).
- Connect to the device advertising **ZeroStock Config**.
- Read current values and submit updates.

## Notes

- The BLE daemon runs as root to update WiFi and restart the screen service.
- Web Bluetooth is supported in Android Chrome/Edge. iOS Safari does not support it.
