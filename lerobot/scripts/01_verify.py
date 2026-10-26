#!/usr/bin/env python
"""Check that the environment is ready. Prints PASS/WARN/FAIL for each check.

Exit code != 0 if anything critical fails. Run it before starting and again on a new machine.
"""

from __future__ import annotations

import importlib
import os
import platform
import shutil
import subprocess
import sys

FAILED = 0


def report(level: str, name: str, detail: str = "") -> None:
    global FAILED
    colors = {"PASS": "\033[32m", "WARN": "\033[33m", "FAIL": "\033[31m"}
    if level == "FAIL":
        FAILED += 1
    print(f"{colors[level]}{level:4}\033[0m {name}" + (f" — {detail}" if detail else ""))


def check_python() -> None:
    v = sys.version_info
    ok = (v.major, v.minor) >= (3, 12)
    report("PASS" if ok else "FAIL", "python >= 3.12", platform.python_version())


def check_platform() -> None:
    mac_arm = platform.system() == "Darwin" and platform.machine() == "arm64"
    report(
        "PASS" if mac_arm else "WARN",
        "macOS arm64 (TorchCodec supported)",
        f"{platform.system()} {platform.machine()}",
    )


def check_torch() -> None:
    try:
        import torch
    except ImportError as exc:
        report("FAIL", "torch importable", str(exc))
        return
    report("PASS", "torch", torch.__version__)
    mps = torch.backends.mps.is_available()
    report("PASS" if mps else "FAIL", "MPS backend available", str(mps))
    if mps:
        x = torch.randn(512, 512, device="mps")
        _ = (x @ x).sum().item()
        report("PASS", "matmul on MPS runs")
    fallback = os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK")
    report(
        "PASS" if fallback == "1" else "WARN",
        "PYTORCH_ENABLE_MPS_FALLBACK=1",
        "without it, an op with no MPS kernel aborts training" if fallback != "1" else "",
    )


def check_lerobot() -> None:
    try:
        import lerobot
    except ImportError as exc:
        report("FAIL", "lerobot importable", str(exc))
        return
    report("PASS", "lerobot", getattr(lerobot, "__version__", "dev"))

    for mod, why in [
        ("lerobot.robots.so_follower", "SO-101 follower"),
        ("lerobot.teleoperators.so_leader", "SO-101 leader"),
        ("lerobot.cameras.opencv", "OpenCV cameras"),
    ]:
        try:
            importlib.import_module(mod)
            report("PASS", why)
        except ImportError as exc:
            report("FAIL", why, str(exc))

    for mod, why in [
        ("scservo_sdk", "Feetech SDK (extra [feetech]) — STS3215 motors"),
        ("rerun", "rerun (extra [viz]) — --display_data=true"),
        ("datasets", "datasets (extra [dataset])"),
        ("wandb", "wandb (extra [training])"),
    ]:
        try:
            importlib.import_module(mod)
            report("PASS", why)
        except ImportError as exc:
            report("FAIL", why, str(exc))


def check_video() -> None:
    ffmpeg = shutil.which("ffmpeg")
    report("PASS" if ffmpeg else "FAIL", "ffmpeg binary", ffmpeg or "missing")
    if ffmpeg:
        out = subprocess.run(
            [ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True, check=False
        ).stdout
        has = "libsvtav1" in out
        report("PASS" if has else "WARN", "encoder libsvtav1", "needed to record AV1 datasets")

    try:
        import torchcodec  # noqa: F401

        report("PASS", "torchcodec importable")
    except Exception as exc:  # ImportError o error al enlazar libavcodec
        report(
            "WARN",
            "torchcodec",
            f"{type(exc).__name__}: {exc} — falling back to pyav",
        )
    try:
        import av  # noqa: F401

        report("PASS", "pyav importable (decoding fallback)")
    except ImportError:
        report("WARN", "pyav missing", "no fallback if torchcodec fails")


def check_serial() -> None:
    try:
        from serial.tools import list_ports
    except ImportError as exc:
        report("FAIL", "pyserial (extra [hardware])", str(exc))
        return
    ports = [p.device for p in list_ports.comports() if "usbmodem" in p.device or "usbserial" in p.device]
    report(
        "PASS" if ports else "WARN",
        "USB serial ports detected",
        ", ".join(ports) if ports else "none (normal if the robot is not connected)",
    )


def check_hf() -> None:
    try:
        from huggingface_hub import whoami

        user = whoami()["name"]
        report("PASS", "Hugging Face session", user)
    except Exception as exc:
        report("FAIL", "Hugging Face session", f"{type(exc).__name__} — run 'hf auth login'")


def check_disk() -> None:
    usage = shutil.disk_usage(os.path.expanduser("~"))
    free_gb = usage.free / 1024**3
    report(
        "PASS" if free_gb > 60 else "WARN",
        "free disk space",
        f"{free_gb:.0f} GB (video datasets and checkpoints fill the disk fast)",
    )


def check_ram() -> None:
    try:
        total = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, check=True).stdout)
    except Exception:
        return
    gb = total / 1024**3
    if gb >= 24:
        report("PASS", "unified RAM", f"{gb:.0f} GB — SmolVLA fine-tune feasible with batch 1-2")
    elif gb >= 16:
        report("WARN", "unified RAM", f"{gb:.0f} GB — stay with ACT, SmolVLA in the cloud")
    else:
        report("WARN", "unified RAM", f"{gb:.0f} GB — train in the cloud")


def main() -> int:
    print("\n\033[1m== LeRobot environment ==\033[0m")
    check_python()
    check_platform()
    check_ram()
    check_disk()
    print("\n\033[1m== torch / MPS ==\033[0m")
    check_torch()
    print("\n\033[1m== lerobot ==\033[0m")
    check_lerobot()
    print("\n\033[1m== video ==\033[0m")
    check_video()
    print("\n\033[1m== hardware / accounts ==\033[0m")
    check_serial()
    check_hf()
    print()
    if FAILED:
        print(f"\033[31m{FAILED} critical check(s) failing\033[0m")
        return 1
    print("\033[32mall green\033[0m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
