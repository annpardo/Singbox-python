#!/usr/bin/env python3
import base64
import json
import os
import platform
import random
import signal
import string
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
FILE_PATH = BASE_DIR / ".npm"
DATA_PATH = BASE_DIR / "singbox_data"

TUIC_PORT = os.environ.get("TUIC_PORT", "")
HY2_PORT = os.environ.get("HY2_PORT", "")
REALITY_PORT = os.environ.get("REALITY_PORT", "")

singbox_process = None
singbox_path = None
config_path = FILE_PATH / "config.json"

BOLD_GREEN = "\033[1;32m"
BOLD_YELLOW = "\033[1;33m"
BOLD_RED = "\033[1;31m"
RESET = "\033[0m"


def color(text, ansi):
    return f"{ansi}{text}{RESET}"


FALLBACK_PRIVATE_KEY = """-----BEGIN EC PARAMETERS-----
BgqghkjOPQQBw==
-----END EC PARAMETERS-----
-----BEGIN EC PRIVATE KEY-----
MHcCAQEEIM4792SEtPqIt1ywqTd/0bYidBqpYV/+siNnfBYsdUYsAoGCCqGSM49
AwEHoUQDQgAE1kHafPj07rJG+HboH2ekAI4r+e6TL38GWASAnngZreoQDF16ARa
/TsyLyFoPkhTxSbehH/OBEjHtSZGaDhMqQ==
-----END EC PRIVATE KEY-----
"""

FALLBACK_CERT = """-----BEGIN CERTIFICATE-----
MIIBejCCASGgAwIBAgIUFWeQL3556PNJLp/veCFxGNj9crkwCgYIKoZIzj0EAwIw
EzERMA8GA1UEAwwIYmluZy5jb20wHhcNMjUwMTAxMDEwMTAwWhcNMzUwMTAxMDEw
MTAwWjATMREwDwYDVQQDDAhiaW5nLmNvbTBNBgqgGzM9AgEGCCqGSM49AwEHA0IA
BNZB2nz49O6yRvh26B9npACOK/nuky9/BlgEgDZ54Ga3qEAxdeWv07Mi8h
d5IR8Um3oR/zQRIx7UmRmg4TKmjUzBRMB0GA1UdDgQWBQTV1cFID7UISE7PLTBR
BfGbgrkMNzAfBgNVHSMEGDAWgBTV1cFID7UISE7PLTBRBfGbgrkMNzAPBgNVHRMB
Af8EBTADAQH/MAoGCCqGSM49BAMCA0cAMEQCIARDAJvg0vd/ytrQVvEcSm6XTlB+
eQ6OFb9LbLYL9Zi+AiffoMbi4y/0YUQlTtz7as9S8/lciBF5VCUoVIKS+vX2g==
-----END CERTIFICATE-----
"""


def enabled(port):
    return bool(str(port).strip()) and str(port).strip() != "0"


def chmod_600(path):
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def random_name(length=6):
    chars = string.ascii_lowercase + string.digits
    return "".join(random.choice(chars) for _ in range(length))


def download_file(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            dest.write_bytes(response.read())
    except urllib.error.URLError as exc:
        raise RuntimeError(f"下载失败: {url}: {exc}") from exc
    os.chmod(dest, 0o755)
    print(color(f"下载 {dest}", BOLD_GREEN))


def get_base_url():
    arch = platform.machine().lower()
    if arch.startswith("arm") or arch == "aarch64":
        return "https://arm64.ssss.nyc.mn"
    if arch.startswith("amd64") or arch == "x86_64":
        return "https://amd64.ssss.nyc.mn"
    if arch == "s390x":
        return "https://s390x.ssss.nyc.mn"
    raise RuntimeError(f"不支持的架构: {arch}")


def load_or_create_uuid():
    uuid_file = FILE_PATH / "uuid.txt"
    if uuid_file.exists():
        value = uuid_file.read_text(encoding="utf-8").strip()
        print(color(f"[UUID] 复用固定 UUID: {value}", BOLD_YELLOW))
        return value

    value = str(uuid.uuid4())
    uuid_file.write_text(value + "\n", encoding="utf-8")
    chmod_600(uuid_file)
    print(color(f"[UUID] 首次生成并永久保存: {value}", BOLD_GREEN))
    return value


def download_singbox():
    global singbox_path
    base_url = get_base_url()
    singbox_path = FILE_PATH / random_name()
    download_file(f"{base_url}/sb", singbox_path)
    return singbox_path


def load_or_create_reality_keypair(binary):
    key_file = FILE_PATH / "key.txt"
    if key_file.exists():
        text = key_file.read_text(encoding="utf-8", errors="ignore")
        print(color("[密钥] 检测到已有密钥，复用...", BOLD_YELLOW))
    else:
        print(color("[密钥] 首次生成 Reality 密钥对...", BOLD_GREEN))
        result = subprocess.run(
            [str(binary), "generate", "reality-keypair"],
            cwd=BASE_DIR,
            text=True,
            capture_output=True,
            check=True,
        )
        text = result.stdout
        key_file.write_text(text, encoding="utf-8")
        chmod_600(key_file)
        print(color("[密钥] 密钥已保存，重启后保持不变", BOLD_GREEN))

    private_key = ""
    public_key = ""
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[0].rstrip(":") == "PrivateKey":
            private_key = parts[1]
        if len(parts) >= 2 and parts[0].rstrip(":") == "PublicKey":
            public_key = parts[1]

    if not private_key or not public_key:
        raise RuntimeError("解析 Reality 密钥对失败")

    return private_key, public_key


def generate_certificate():
    key_path = FILE_PATH / "private.key"
    cert_path = FILE_PATH / "cert.pem"

    if shutil_which("openssl"):
        subprocess.run(
            ["openssl", "ecparam", "-genkey", "-name", "prime256v1", "-out", str(key_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        subprocess.run(
            [
                "openssl",
                "req",
                "-new",
                "-x509",
                "-days",
                "3650",
                "-key",
                str(key_path),
                "-out",
                str(cert_path),
                "-subj",
                "/CN=bing.com",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
    else:
        key_path.write_text(FALLBACK_PRIVATE_KEY, encoding="utf-8")
        cert_path.write_text(FALLBACK_CERT, encoding="utf-8")

    chmod_600(key_path)
    return cert_path, key_path


def shutil_which(command):
    paths = os.environ.get("PATH", "").split(os.pathsep)
    exts = [""] if os.name != "nt" else os.environ.get("PATHEXT", "").split(os.pathsep)
    for directory in paths:
        for ext in exts:
            candidate = Path(directory) / f"{command}{ext}"
            if candidate.exists() and os.access(candidate, os.X_OK):
                return str(candidate)
    return None


def build_config(user_uuid, private_key, cert_path, key_path):
    inbounds = []

    if enabled(TUIC_PORT):
        inbounds.append(
            {
                "type": "tuic",
                "listen": "::",
                "listen_port": int(TUIC_PORT),
                "users": [{"uuid": user_uuid, "password": "admin"}],
                "congestion_control": "bbr",
                "tls": {
                    "enabled": True,
                    "alpn": ["h3"],
                    "certificate_path": str(cert_path),
                    "key_path": str(key_path),
                },
            }
        )

    if enabled(HY2_PORT):
        inbounds.append(
            {
                "type": "hysteria2",
                "listen": "::",
                "listen_port": int(HY2_PORT),
                "users": [{"password": user_uuid}],
                "masquerade": "https://bing.com",
                "tls": {
                    "enabled": True,
                    "alpn": ["h3"],
                    "certificate_path": str(cert_path),
                    "key_path": str(key_path),
                },
            }
        )

    if enabled(REALITY_PORT):
        inbounds.append(
            {
                "type": "vless",
                "listen": "::",
                "listen_port": int(REALITY_PORT),
                "users": [{"uuid": user_uuid, "flow": "xtls-rprx-vision"}],
                "tls": {
                    "enabled": True,
                    "server_name": "www.nazhumi.com",
                    "reality": {
                        "enabled": True,
                        "handshake": {"server": "www.nazhumi.com", "server_port": 443},
                        "private_key": private_key,
                        "short_id": [""],
                    },
                },
            }
        )

    config = {
        "log": {"disabled": True},
        "inbounds": inbounds,
        "outbounds": [{"type": "direct"}],
    }
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config


def start_singbox():
    global singbox_process
    if not singbox_path:
        raise RuntimeError("sing-box 路径尚未初始化")
    singbox_process = subprocess.Popen([str(singbox_path), "run", "-c", str(config_path)], cwd=BASE_DIR)
    print(color(f"[SING-BOX] 启动完成 PID={singbox_process.pid}", BOLD_GREEN))
    return singbox_process


def stop_singbox():
    global singbox_process
    if singbox_process and singbox_process.poll() is None:
        singbox_process.terminate()
        try:
            singbox_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            singbox_process.kill()
            singbox_process.wait(timeout=5)


def fetch_text(url, timeout=2):
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "*/*",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="ignore").strip()
    except Exception:
        return ""


def get_ip():
    return fetch_text("https://api.ipify.org", 2) or fetch_text("https://ipv4.ip.sb", 2) or "IP_ERROR"


def get_isp():
    providers = [
        (
            "https://api.ip.sb/geoip",
            5,
            lambda data: [
                data.get("country_code", ""),
                data.get("organization", "") or data.get("isp", "") or data.get("asn_organization", ""),
            ],
        ),
        (
            "https://ipapi.co/json/",
            5,
            lambda data: [
                data.get("country_code", ""),
                data.get("org", "") or data.get("asn", ""),
            ],
        ),
        (
            "http://ip-api.com/json",
            5,
            lambda data: [
                data.get("countryCode", ""),
                data.get("isp", "") or data.get("org", "") or data.get("as", ""),
            ],
        ),
    ]

    for url, timeout, pick_parts in providers:
        text = fetch_text(url, timeout)
        if not text:
            continue

        try:
            data = json.loads(text)
        except Exception:
            continue

        parts = [str(part).strip() for part in pick_parts(data) if str(part).strip()]
        isp = "-".join(parts)
        if isp:
            return isp

    return "0.0"


def generate_subscription(user_uuid, public_key):
    ip = get_ip()
    isp = get_isp()
    links = []

    if enabled(TUIC_PORT):
        links.append(
            f"tuic://{user_uuid}:admin@{ip}:{TUIC_PORT}"
            f"?sni=www.bing.com&alpn=h3&congestion_control=bbr&allowInsecure=1#TUIC-{isp}"
        )
    if enabled(HY2_PORT):
        links.append(
            f"hysteria2://{user_uuid}@{ip}:{HY2_PORT}/"
            f"?sni=www.bing.com&insecure=1#Hysteria2-{isp}"
        )
    if enabled(REALITY_PORT):
        links.append(
            f"vless://{user_uuid}@{ip}:{REALITY_PORT}"
            f"?encryption=none&flow=xtls-rprx-vision&security=reality"
            f"&sni=www.nazhumi.com&fp=firefox&pbk={public_key}&type=tcp#Reality-{isp}"
        )

    list_path = FILE_PATH / "list.txt"
    sub_path = FILE_PATH / "sub.txt"
    list_text = "\n".join(links)
    if list_text:
        list_text += "\n"
    list_path.write_text(list_text, encoding="utf-8")
    sub_path.write_text(base64.b64encode(list_path.read_bytes()).decode("ascii"), encoding="utf-8")

    print(list_text, end="")
    print(color(f"{sub_path} 已保存", BOLD_GREEN))


def beijing_day_hour_minute():
    now_ts = int(time.time())
    beijing_ts = now_ts + 28800
    hour = (beijing_ts // 3600) % 24
    minute = (beijing_ts // 60) % 60
    day = beijing_ts // 86400
    return day, hour, minute


def schedule_restart():
    print(color("[定时重启:Sing-box] 已启动（北京时间 00:03）", BOLD_GREEN))
    last_restart_day = -1

    while True:
        day, hour, minute = beijing_day_hour_minute()
        if hour == 0 and minute == 3 and day != last_restart_day:
            print(color("[定时重启:Sing-box] 到达 00:03 -> 重启 sing-box", BOLD_GREEN))
            last_restart_day = day
            stop_singbox()
            time.sleep(3)
            start_singbox()
            print(color(f"[Sing-box重启完成] 新 PID: {singbox_process.pid}", BOLD_GREEN))
        time.sleep(1)


def signal_handler(signum, frame):
    stop_singbox()
    sys.exit(0)


def main():
    os.chdir(BASE_DIR)
    FILE_PATH.mkdir(parents=True, exist_ok=True)
    DATA_PATH.mkdir(parents=True, exist_ok=True)

    user_uuid = load_or_create_uuid()
    binary = download_singbox()
    private_key, public_key = load_or_create_reality_keypair(binary)
    cert_path, key_path = generate_certificate()
    build_config(user_uuid, private_key, cert_path, key_path)
    start_singbox()
    generate_subscription(user_uuid, public_key)
    schedule_restart()


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        main()
    except KeyboardInterrupt:
        signal_handler(signal.SIGINT, None)
    except Exception as exc:
        stop_singbox()
        print(color(f"[错误] {exc}", BOLD_RED), file=sys.stderr)
        sys.exit(1)
