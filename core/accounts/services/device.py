# accounts/services/device.py

import hashlib

def generate_device_hash(ip: str, user_agent: str) -> str:
    raw = f"{ip}:{user_agent}"
    return hashlib.sha256(raw.encode()).hexdigest()
