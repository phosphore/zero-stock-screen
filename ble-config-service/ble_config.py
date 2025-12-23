#!/usr/bin/env python3
import grp
import json
import logging
import os
import pwd
import re
import shutil
import subprocess
import tempfile
import time
from typing import Dict, List, Optional, Tuple

from bluezero import adapter, peripheral

SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
RX_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
TX_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
RD_UUID = "6e400004-b5a3-f393-e0a9-e50e24dcca9e"

CONFIG_PATH = "/home/pi/zero-stock-screen/configuration.cfg"
SCREEN_SERVICE = "stock-screen.service"
CONFIG_OWNER_USER = "pi"
CONFIG_OWNER_GROUP = "pi"


def _resolve_owner_ids(user: str, group: Optional[str]) -> Optional[Tuple[int, int]]:
    try:
        uid = pwd.getpwnam(user).pw_uid
    except KeyError:
        return None

    gid = None
    if group:
        try:
            gid = grp.getgrnam(group).gr_gid
        except KeyError:
            gid = None
    if gid is None:
        gid = pwd.getpwnam(user).pw_gid
    return uid, gid

def _read_lines(path: str) -> List[str]:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.readlines()


def _section_ranges(lines: List[str]) -> Dict[str, Tuple[int, int]]:
    sections: Dict[str, Tuple[int, int]] = {}
    current: Optional[str] = None
    start_index: Optional[int] = None
    for idx, line in enumerate(lines):
        match = re.match(r"\s*\[(.+?)\]\s*$", line)
        if match:
            if current is not None and start_index is not None:
                sections[current] = (start_index, idx)
            current = match.group(1).strip()
            start_index = idx
    if current is not None and start_index is not None:
        sections[current] = (start_index, len(lines))
    return sections


def _ensure_section(lines: List[str], section: str) -> None:
    ranges = _section_ranges(lines)
    if section in ranges:
        return
    if lines and not lines[-1].endswith("\n"):
        lines[-1] = f"{lines[-1]}\n"
    if lines and lines[-1].strip():
        lines.append("\n")
    lines.append(f"[{section}]\n")


def _find_key(lines: List[str], section: str, key: str) -> Optional[Tuple[int, re.Match]]:
    ranges = _section_ranges(lines)
    if section not in ranges:
        return None
    start, end = ranges[section]
    pattern = re.compile(rf"^(\s*{re.escape(key)}\s*[:=]\s*)([^#;\n]*)(\s*(#.*)?)$")
    for idx in range(start + 1, end):
        line = lines[idx]
        match = pattern.match(line.rstrip("\n"))
        if match:
            return idx, match
    return None


def _set_key(lines: List[str], section: str, key: str, value: str) -> None:
    _ensure_section(lines, section)
    found = _find_key(lines, section, key)
    if found:
        idx, match = found
        newline = "\n" if lines[idx].endswith("\n") else ""
        lines[idx] = f"{match.group(1)}{value}{match.group(3)}{newline}"
        return

    ranges = _section_ranges(lines)
    start, end = ranges[section]
    insert_at = start + 1
    for idx in range(end - 1, start, -1):
        if lines[idx].strip():
            insert_at = idx + 1
            break
    lines.insert(insert_at, f"{key} : {value}\n")


def _get_value(lines: List[str], section: str, key: str) -> Optional[str]:
    found = _find_key(lines, section, key)
    if not found:
        return None
    _, match = found
    return match.group(2).strip()


def _load_config_values(path: str) -> Dict[str, Dict[str, object]]:
    lines = []
    if os.path.exists(path):
        lines = _read_lines(path)
    result: Dict[str, Dict[str, object]] = {}
    base: Dict[str, object] = {}
    refresh = _get_value(lines, "base", "refresh_interval_minutes")
    if refresh is not None:
        try:
            base["refresh_interval_minutes"] = int(refresh)
        except ValueError:
            base["refresh_interval_minutes"] = refresh
    data_range = _get_value(lines, "base", "data_range_days")
    if data_range is not None:
        try:
            base["data_range_days"] = float(data_range)
        except ValueError:
            base["data_range_days"] = data_range
    base_url = _get_value(lines, "base", "data_api_base_url")
    if base_url is not None:
        base["data_api_base_url"] = base_url
    ticker = _get_value(lines, "base", "ticker")
    if ticker is not None:
        base["ticker"] = ticker
    if base:
        result["base"] = base

    epd: Dict[str, object] = {}
    mode = _get_value(lines, "epd2in13v3", "mode")
    if mode is not None:
        epd["mode"] = mode
    if epd:
        result["epd2in13v3"] = epd
    wifi = _load_wifi_details()
    if wifi:
        result["wifi"] = wifi
    return result


def _write_config(path: str, updates: Dict[str, Dict[str, object]]) -> None:
    existing_stat: Optional[os.stat_result] = None
    if os.path.exists(path):
        existing_stat = os.stat(path)

    lines = []
    if os.path.exists(path):
        lines = _read_lines(path)

    if "base" in updates:
        base_updates = updates["base"]
        if "refresh_interval_minutes" in base_updates:
            _set_key(lines, "base", "refresh_interval_minutes", str(base_updates["refresh_interval_minutes"]))
        if "data_range_days" in base_updates:
            _set_key(lines, "base", "data_range_days", str(base_updates["data_range_days"]))
        if "data_api_base_url" in base_updates:
            _set_key(lines, "base", "data_api_base_url", str(base_updates["data_api_base_url"]))
        if "ticker" in base_updates:
            _set_key(lines, "base", "ticker", str(base_updates["ticker"]))

    if "epd2in13v3" in updates:
        epd_updates = updates["epd2in13v3"]
        if "mode" in epd_updates:
            _set_key(lines, "epd2in13v3", "mode", str(epd_updates["mode"]))

    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp_handle = tempfile.NamedTemporaryFile("w", delete=False, dir=os.path.dirname(path), encoding="utf-8")
    try:
        temp_handle.writelines(lines)
        temp_handle.flush()
        os.fsync(temp_handle.fileno())
    finally:
        temp_handle.close()

    if os.path.exists(path):
        shutil.copy2(path, f"{path}.bak")
    os.replace(temp_handle.name, path)
    if existing_stat is None:
        try:
            existing_stat = os.stat(os.path.dirname(path))
        except OSError:
            existing_stat = None
    owner_ids = _resolve_owner_ids(CONFIG_OWNER_USER, CONFIG_OWNER_GROUP)
    target_ids = owner_ids
    if target_ids is None and existing_stat is not None:
        target_ids = (existing_stat.st_uid, existing_stat.st_gid)
    if target_ids is not None:
        try:
            os.chown(path, target_ids[0], target_ids[1])
            if existing_stat is not None:
                os.chmod(path, existing_stat.st_mode)
        except OSError:
            pass


def _validate_updates(payload: Dict[str, object]) -> Dict[str, Dict[str, object]]:
    updates: Dict[str, Dict[str, object]] = {}
    if "base" in payload:
        base_payload = payload["base"]
        if not isinstance(base_payload, dict):
            raise ValueError("base must be an object")
        base_updates: Dict[str, object] = {}
        if "refresh_interval_minutes" in base_payload:
            value = base_payload["refresh_interval_minutes"]
            if not isinstance(value, int):
                raise ValueError("refresh_interval_minutes must be int")
            if value < 1 or value > 1440:
                raise ValueError("refresh_interval_minutes out of range")
            base_updates["refresh_interval_minutes"] = value
        if "data_range_days" in base_payload:
            value = base_payload["data_range_days"]
            if not isinstance(value, (int, float)):
                raise ValueError("data_range_days must be number")
            value_float = float(value)
            if value_float < 0.1 or value_float > 365.0:
                raise ValueError("data_range_days out of range")
            base_updates["data_range_days"] = value_float
        if "data_api_base_url" in base_payload:
            value = base_payload["data_api_base_url"]
            if not isinstance(value, str):
                raise ValueError("data_api_base_url must be string")
            trimmed = value.strip()
            if not trimmed:
                raise ValueError("data_api_base_url cannot be empty")
            base_updates["data_api_base_url"] = trimmed
        if "ticker" in base_payload:
            value = base_payload["ticker"]
            if not isinstance(value, str):
                raise ValueError("ticker must be string")
            trimmed = value.strip()
            if not trimmed:
                raise ValueError("ticker cannot be empty")
            base_updates["ticker"] = trimmed
        if base_updates:
            updates["base"] = base_updates

    if "epd2in13v3" in payload:
        epd_payload = payload["epd2in13v3"]
        if not isinstance(epd_payload, dict):
            raise ValueError("epd2in13v3 must be an object")
        epd_updates: Dict[str, object] = {}
        if "mode" in epd_payload:
            value = epd_payload["mode"]
            if not isinstance(value, str):
                raise ValueError("mode must be string")
            trimmed = value.strip().lower()
            if trimmed not in {"candle", "line"}:
                raise ValueError("mode must be candle or line")
            epd_updates["mode"] = trimmed
        if epd_updates:
            updates["epd2in13v3"] = epd_updates

    return updates


def _run_command(command: List[str], *, input_text: Optional[str] = None) -> Tuple[bool, str]:
    try:
        result = subprocess.run(
            command,
            input=input_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except FileNotFoundError:
        return False, f"command not found: {command[0]}"

    if result.returncode != 0:
        return False, result.stderr.strip() or result.stdout.strip()
    return True, result.stdout.strip()


def _get_active_wifi_connection() -> Tuple[Optional[str], Optional[str]]:
    if not shutil.which("nmcli"):
        return None, None
    success, output = _run_command(["nmcli", "-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active"])
    if not success:
        return None, None
    for line in output.splitlines():
        if not line.strip():
            continue
        try:
            name, connection_type, device = line.rsplit(":", 2)
        except ValueError:
            continue
        if connection_type == "wifi":
            return name, device
    return None, None


def _get_active_ssid() -> Optional[str]:
    if shutil.which("nmcli"):
        success, output = _run_command(["nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi"])
        if success:
            for line in output.splitlines():
                if line.startswith("yes:"):
                    ssid = line.split(":", 1)[1].strip()
                    return ssid or None
    if shutil.which("iwgetid"):
        success, output = _run_command(["iwgetid", "-r"])
        if success:
            ssid = output.strip()
            return ssid or None
    return None


def _get_active_psk(connection_name: Optional[str], ssid: Optional[str]) -> Optional[str]:
    if connection_name and shutil.which("nmcli"):
        success, output = _run_command(
            ["nmcli", "-s", "-g", "802-11-wireless-security.psk", "connection", "show", connection_name]
        )
        if success:
            psk = output.strip()
            if psk:
                return psk

    if not ssid:
        return None
    supplicant_path = "/etc/wpa_supplicant/wpa_supplicant.conf"
    if not os.path.exists(supplicant_path):
        return None
    try:
        with open(supplicant_path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return None

    in_network = False
    current_ssid = None
    current_psk = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("network={"):
            in_network = True
            current_ssid = None
            current_psk = None
            continue
        if in_network and stripped.startswith("}"):
            if current_ssid == ssid and current_psk:
                return current_psk
            in_network = False
            current_ssid = None
            current_psk = None
            continue
        if not in_network:
            continue
        ssid_match = re.match(r'ssid\s*=\s*"(.+)"', stripped)
        if ssid_match:
            current_ssid = ssid_match.group(1)
            continue
        psk_match = re.match(r'#?psk\s*=\s*"(.+)"', stripped)
        if psk_match:
            current_psk = psk_match.group(1)
            continue
    return None


def _get_wifi_status() -> Optional[str]:
    if not shutil.which("nmcli"):
        return "Unknown"
    success, output = _run_command(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL", "dev", "wifi"])
    if success:
        for line in output.splitlines():
            if not line.strip():
                continue
            parts = line.split(":", 2)
            if len(parts) != 3:
                continue
            in_use, ssid, signal = parts
            if in_use != "*":
                continue
            readable_ssid = ssid.strip()
            signal_value = signal.strip()
            if signal_value.isdigit():
                if readable_ssid:
                    return f"Connected to {readable_ssid} (signal {signal_value}%)"
                return f"Connected (signal {signal_value}%)"
            if readable_ssid:
                return f"Connected to {readable_ssid}"
            return "Connected"
    success, output = _run_command(["nmcli", "-t", "-f", "DEVICE,STATE,TYPE", "dev", "status"])
    if success:
        for line in output.splitlines():
            if not line.strip():
                continue
            parts = line.split(":", 2)
            if len(parts) != 3:
                continue
            _device, state, device_type = parts
            if device_type == "wifi":
                if state == "connected":
                    return "Connected"
                if state == "disconnected":
                    return "Disconnected"
                return state.replace("-", " ").title()
    return "Unknown"


def _load_wifi_details() -> Dict[str, str]:
    connection_name, _device = _get_active_wifi_connection()
    ssid = _get_active_ssid()
    psk = _get_active_psk(connection_name, ssid)
    status = _get_wifi_status()
    wifi: Dict[str, str] = {}
    if ssid:
        wifi["ssid"] = ssid
    if psk:
        wifi["psk"] = psk
    if status:
        wifi["status"] = status
    return wifi


def _provision_wifi(ssid: str, psk: str) -> Tuple[bool, str]:
    if shutil.which("nmcli"):
        success, output = _run_command(
            ["nmcli", "dev", "wifi", "connect", ssid, "password", psk, "ifname", "wlan0"]
        )
        if success:
            return True, "connected"
        return False, output or "nmcli failed"

    if not shutil.which("wpa_passphrase"):
        return False, "wpa_passphrase not available"

    success, output = _run_command(["wpa_passphrase", ssid, psk])
    if not success:
        return False, output or "wpa_passphrase failed"

    supplicant_path = "/etc/wpa_supplicant/wpa_supplicant.conf"
    existing = ""
    if os.path.exists(supplicant_path):
        with open(supplicant_path, "r", encoding="utf-8") as handle:
            existing = handle.read()

    network_block = output.strip()
    ssid_pattern = re.escape(f'ssid="{ssid}"')
    existing = re.sub(
        rf"network=\{{[^\}}]*{ssid_pattern}[^\}}]*\}}\s*",
        "",
        existing,
        flags=re.MULTILINE,
    )
    if existing and not existing.endswith("\n"):
        existing += "\n"
    existing += f"\n{network_block}\n"

    with open(supplicant_path, "w", encoding="utf-8") as handle:
        handle.write(existing)

    success, output = _run_command(["wpa_cli", "-i", "wlan0", "reconfigure"])
    if success:
        return True, "reconfigured"
    return False, output or "wpa_cli reconfigure failed"


def _restart_screen_service() -> Tuple[bool, str]:
    return _run_command(["systemctl", "restart", SCREEN_SERVICE])


def _decode_value(value: List[int]) -> str:
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8")
    return bytes(value).decode("utf-8")


def _encode_value(text: str) -> List[int]:
    return list(text.encode("utf-8"))


class BleConfigServer:
    def __init__(self) -> None:
        adapters = list(adapter.Adapter.available())
        if not adapters:
            raise RuntimeError("No Bluetooth adapters found")
        adapter_address = self._resolve_adapter_address(adapters[0])
        use_adapter = adapter.Adapter(adapter_address)
        self._ensure_adapter_powered(use_adapter)
        self.peripheral = peripheral.Peripheral(
            adapter_address=adapter_address,
            local_name="ZeroStock Config",
        )
        self.peripheral.add_service(srv_id=1, uuid=SERVICE_UUID, primary=True)
        self.peripheral.add_characteristic(
            srv_id=1,
            chr_id=1,
            uuid=RX_UUID,
            value=[],
            notifying=False,
            flags=["write", "write-without-response"],
            write_callback=self._on_write,
        )
        self.tx_characteristic = self.peripheral.add_characteristic(
            srv_id=1,
            chr_id=2,
            uuid=TX_UUID,
            value=[],
            notifying=False,
            flags=["notify"],
        )
        self.peripheral.add_characteristic(
            srv_id=1,
            chr_id=3,
            uuid=RD_UUID,
            value=[],
            notifying=False,
            flags=["read"],
            read_callback=self._on_read,
        )
    @staticmethod
    def _resolve_adapter_address(adapter_entry):
        if isinstance(adapter_entry, str):
            return adapter_entry
        for attr_name in ("address", "adapter_address", "adapter_addr", "mac_address"):
            if hasattr(adapter_entry, attr_name):
                value = getattr(adapter_entry, attr_name)
                if isinstance(value, str):
                    return value
        raise RuntimeError("Bluetooth adapter address not found")

    @staticmethod
    def _ensure_adapter_powered(use_adapter) -> None:
        for _ in range(5):
            try:
                if use_adapter.powered:
                    return
                use_adapter.powered = True
            except Exception as exc:
                logging.warning("Failed to power Bluetooth adapter: %s", exc)
            time.sleep(0.5)
        if not use_adapter.powered:
            raise RuntimeError("Bluetooth adapter is not powered")

    def _get_characteristic(self, uuid: str):
        for service in getattr(self.peripheral, "services", []):
            for characteristic in getattr(service, "characteristics", []):
                if characteristic.uuid == uuid:
                    return characteristic
        raise RuntimeError(f"Characteristic {uuid} not found")

    def _notify(self, message: str) -> None:
        logging.info("BLE status: %s", message)
        self.tx_characteristic.value = _encode_value(message)
        self.peripheral.notify(1, 2)

    def _on_read(self, *args) -> List[int]:
        offset = 0
        if args:
            candidate = args[0]
            if isinstance(candidate, int):
                offset = candidate
            elif isinstance(candidate, dict) and "offset" in candidate:
                offset = int(candidate["offset"])
        data = _load_config_values(CONFIG_PATH)
        payload = json.dumps(data, ensure_ascii=False)
        encoded = _encode_value(payload)
        if offset <= 0:
            return encoded
        return encoded[offset:]

    def _on_write(self, value: List[int], *_args) -> None:
        try:
            payload = json.loads(_decode_value(value))
        except json.JSONDecodeError as exc:
            self._notify(f"error: invalid json ({exc.msg})")
            return

        if not isinstance(payload, dict):
            self._notify("error: payload must be a JSON object")
            return

        wifi = payload.get("wifi")
        if wifi is not None and not isinstance(wifi, dict):
            self._notify("error: wifi must be an object")
            return

        try:
            updates = _validate_updates(payload)
        except ValueError as exc:
            self._notify(f"error: {exc}")
            return

        if wifi:
            ssid = wifi.get("ssid")
            psk = wifi.get("psk")
            if not ssid or not psk:
                self._notify("error: wifi ssid and psk are required")
                return
            if not isinstance(ssid, str) or not isinstance(psk, str):
                self._notify("error: wifi ssid and psk must be strings")
                return
            ssid_trimmed = ssid.strip()
            if not ssid_trimmed:
                self._notify("error: wifi ssid cannot be empty")
                return
            success, output = _provision_wifi(ssid_trimmed, psk)
            if not success:
                logging.error("WiFi provisioning failed for ssid=%s: %s", ssid_trimmed, output)
                self._notify(f"error: wifi provisioning failed ({output})")
                return

        if updates:
            try:
                _write_config(CONFIG_PATH, updates)
            except OSError as exc:
                self._notify(f"error: failed to update config ({exc})")
                return

        if payload.get("restart") is True:
            success, output = _restart_screen_service()
            if not success:
                self._notify(f"error: restart failed ({output})")
                return

        self._notify("ok")

    def run(self) -> None:
        self.peripheral.publish()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    server = BleConfigServer()
    server.run()


if __name__ == "__main__":
    main()
