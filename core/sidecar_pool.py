"""Sidecar ký theo từng proxy.

Vì sao cần lớp này: sidecar ký (tiktok-signature) tạo `ttwid` / `msToken`
từ IP của **trình duyệt sidecar**. Nếu request thật lại thoát qua proxy,
TikTok thấy chữ ký + danh tính thuộc IP máy nhưng request đến từ IP proxy
— và trả HTTP 200 với body rỗng (code 8) hoặc 10221.

Cách chữa: mỗi proxy có một tiến trình sidecar riêng, trình duyệt của nó
cũng thoát qua đúng proxy đó. Python dùng cùng proxy cho request thật.
Không có proxy -> dùng sidecar mặc định (8080) như cũ, vì khi đó cả hai
đều đi bằng IP máy.

Lớp này chỉ *chuẩn bị* sidecar. Việc chọn signer cho account nằm ở
`HttpBackend`.
"""

from __future__ import annotations

import atexit
import hashlib
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .proxy import ProxyProfile, parse_proxy
from .signer import Signer, SignerError


class SidecarPoolError(RuntimeError):
    """Không dựng được sidecar cho proxy (thiếu Node, proxy lỗi, quá nhiều…)."""


# --------------------------------------------------------------------------- #
# RAM còn trống
# --------------------------------------------------------------------------- #
def available_ram_mb() -> int | None:
    """RAM trống hiện tại (MB). None nếu hệ điều hành không cho đọc.

    Mỗi sidecar mở 1 Chrome riêng, rất ngốn RAM. Khi máy gần hết RAM mà
    vẫn nhận thêm sidecar, cả app lẫn Windows sẽ khựng. Đọc trước khi mở.
    """
    try:
        if os.name == "nt":
            import ctypes

            class _MemoryStatusEx(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = _MemoryStatusEx()
            stat.dwLength = ctypes.sizeof(_MemoryStatusEx)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return int(stat.ullAvailPhys // (1024 * 1024))
            return None

        pages = int(os.sysconf("SC_AVPHYS_PAGES"))
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        return int(pages * page_size // (1024 * 1024))
    except (OSError, ValueError, AttributeError):
        return None


# --------------------------------------------------------------------------- #
# Tìm Node.js
# --------------------------------------------------------------------------- #
def find_node_exe() -> str:
    """Đường dẫn node chạy được. Rỗng nếu không tìm thấy."""
    env = (os.environ.get("NODE_EXE") or "").strip()
    if env and Path(env).exists():
        return env

    for name in ("node.exe", "node"):
        p = shutil.which(name)
        if p:
            return p

    roots = []
    for key, fallback in (
        ("ProgramFiles", r"C:\Program Files"),
        ("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        ("LOCALAPPDATA", ""),
    ):
        base = os.environ.get(key) or fallback
        if base:
            roots.append(Path(base))
    for root in roots:
        for rel in ("nodejs/node.exe", "Programs/nodejs/node.exe", "node/node.exe"):
            p = root / rel
            if p.exists():
                return str(p)

    for rel in ("/usr/bin/node", "/usr/local/bin/node", "/opt/homebrew/bin/node"):
        p = Path(rel)
        if p.exists():
            return str(p)
    return ""


# --------------------------------------------------------------------------- #
@dataclass
class SidecarInstance:
    proxy_url: str
    proxy_label: str
    port: int
    signer: Signer
    proc: subprocess.Popen | None = None
    profile_dir: str = ""
    log_path: str = ""
    ready: bool = False
    error: str = ""


def _mask(url: str) -> str:
    """Hiển thị proxy không lộ mật khẩu."""
    p = parse_proxy(url)
    if p is None:
        return (url or "")[:24]
    return f"{p.scheme}://{p.host}:{p.port}"


class SidecarPool:
    """Quản lý nhiều sidecar, mỗi proxy một cái.

    `max_instances` chặn số trình duyệt mở cùng lúc. Với proxy list lớn hơn
    ngưỡng, các account dùng proxy vượt ngưỡng sẽ báo lỗi rõ thay vì âm
    thầm dùng sai signer (kiểu cũ gây body rỗng).
    """

    def __init__(
        self,
        sidecar_dir: str | Path,
        node_exe: str = "",
        default_signer_url: str = "http://127.0.0.1:8080",
        max_instances: int = 12,
        startup_timeout: float = 120.0,
        parallel_starts: int = 2,
        min_free_ram_mb: int = 700,
    ) -> None:
        self.sidecar_dir = Path(sidecar_dir)
        self.node_exe = node_exe or find_node_exe()
        self.max_instances = max(1, int(max_instances))
        self.startup_timeout = max(20.0, float(startup_timeout))
        # Mỗi sidecar = 1 Chrome. Dưới ngưỡng này thì từ chối mở thêm để
        # không kéo sập RAM máy người dùng.
        self.min_free_ram_mb = max(0, int(min_free_ram_mb))
        self._start_gate = threading.BoundedSemaphore(
            max(1, int(parallel_starts))
        )
        self._lock = threading.RLock()
        self._instances: dict[str, SidecarInstance] = {}
        self._signers: dict[str, Signer] = {}
        self._failed: dict[str, str] = {}
        self._default_signer = Signer(default_signer_url)
        self._closed = False
        self._tmp_root = Path(
            tempfile.mkdtemp(prefix="buffreact-sidecars-")
        )
        atexit.register(self.shutdown)

    # ------------------------------------------------------------------ #
    # API chính
    # ------------------------------------------------------------------ #
    def signer_for(self, proxy_url: str) -> Signer:
        """Signer khớp với proxy. Không proxy -> signer mặc định (IP máy)."""
        proxy_url = (proxy_url or "").strip()
        if not proxy_url:
            return self._default_signer
        if self._closed:
            raise SidecarPoolError("SidecarPool đã đóng.")

        with self._lock:
            found = self._signers.get(proxy_url)
            if found is not None:
                return found
            failed = self._failed.get(proxy_url)
            if failed:
                raise SidecarPoolError(
                    f"Sidecar cho {_mask(proxy_url)} đã lỗi trước đó: "
                    f"{failed}"
                )

        profile = parse_proxy(proxy_url)
        if profile is None:
            raise SidecarPoolError(
                f"Không đọc được proxy: {_mask(proxy_url)}"
            )
        if profile.scheme not in ("http", "https"):
            raise SidecarPoolError(
                f"Sidecar chưa hỗ trợ proxy {profile.scheme}; "
                "dùng http:// hoặc https://"
            )

        # Chỉ một luồng dựng sidecar cho cùng proxy; các luồng khác đợi.
        with self._start_gate:
            with self._lock:
                found = self._signers.get(proxy_url)
                if found is not None:
                    return found
                if len(self._instances) >= self.max_instances:
                    raise SidecarPoolError(
                        f"Đã mở tối đa {self.max_instances} sidecar proxy. "
                        "Giảm số proxy hoặc chia lô nhỏ hơn."
                    )
            free_mb = available_ram_mb()
            if free_mb is not None and free_mb < self.min_free_ram_mb:
                raise SidecarPoolError(
                    f"RAM trống chỉ {free_mb} MB (cần ≥ {self.min_free_ram_mb} "
                    "MB cho mỗi Chrome sidecar). Đóng bớt Chrome/tab hoặc "
                    "giảm số proxy rồi thử lại."
                )
            try:
                inst = self._spawn(proxy_url, profile)
            except Exception as e:
                with self._lock:
                    self._failed[proxy_url] = str(e)[:200]
                raise
            with self._lock:
                self._instances[proxy_url] = inst
                self._signers[proxy_url] = inst.signer
            return inst.signer

    def reset(self) -> None:
        """Dừng mọi sidecar proxy (giữ signer mặc định 8080)."""
        with self._lock:
            insts = list(self._instances.values())
            self._instances.clear()
            self._signers.clear()
            self._failed.clear()
        for inst in insts:
            self._stop(inst)

    def shutdown(self) -> None:
        """Dừng toàn bộ và xoá file tạm. Gọi lại nhiều lần vẫn an toàn."""
        with self._lock:
            self._closed = True
        try:
            self.reset()
        except (RuntimeError, OSError):
            # Lúc interpreter đang tắt thì có thể ném (không tạo được
            # thread nữa); bỏ qua, chỉ cần không để lại Chrome chiếm RAM.
            pass
        shutil.rmtree(self._tmp_root, ignore_errors=True)

    def count(self) -> int:
        with self._lock:
            return len(self._instances)

    # ------------------------------------------------------------------ #
    def _spawn(self, proxy_url: str, profile: ProxyProfile) -> SidecarInstance:
        if not self.node_exe:
            raise SidecarPoolError(
                "Không tìm thấy Node.js để mở sidecar theo proxy. "
                "Cài Node LTS hoặc đặt biến NODE_EXE."
            )
        server = self.sidecar_dir / "server.mjs"
        if not server.exists():
            raise SidecarPoolError(
                f"Không thấy {server}. Chạy app từ thư mục dự án."
            )

        port = self._free_port()
        key = hashlib.sha1(proxy_url.encode("utf-8", "ignore")).hexdigest()[:10]
        profile_dir = self._tmp_root / f"chrome-{key}"
        log_path = self._tmp_root / f"sidecar-{key}.log"
        profile_dir.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env.update({
            "PORT": str(port),
            "CHROME_PROFILE_DIR": str(profile_dir),
            "PROXY_ENABLED": "true",
            "PROXY_SCHEME": profile.scheme,
            "PROXY_HOST": f"{profile.host}:{profile.port}",
            "PROXY_USER": profile.username,
            "PROXY_PASS": profile.password,
            "IDENTITY_POOL_SIZE": "1",
        })
        creationflags = (
            subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        )
        proc: subprocess.Popen | None = None
        with open(log_path, "wb") as log:
            proc = subprocess.Popen(
                [self.node_exe, "server.mjs"],
                cwd=str(self.sidecar_dir),
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
            )

        signer = Signer(f"http://127.0.0.1:{port}", timeout=30.0)
        inst = SidecarInstance(
            proxy_url=proxy_url,
            proxy_label=_mask(proxy_url),
            port=port,
            signer=signer,
            proc=proc,
            profile_dir=str(profile_dir),
            log_path=str(log_path),
        )
        try:
            self._wait_ready(inst)
        except Exception:
            self._stop(inst)
            raise
        return inst

    def _wait_ready(self, inst: SidecarInstance) -> None:
        deadline = time.time() + self.startup_timeout
        last_err = ""
        while time.time() < deadline:
            proc = inst.proc
            if proc is not None and proc.poll() is not None:
                last_err = (
                    f"sidecar đã thoát (mã {proc.returncode}). "
                    + self._log_tail(inst)
                )
                break
            try:
                info = inst.signer.health(timeout=2.0)
                if info.get("ready") and int(info.get("readyIdentities") or 0) > 0:
                    inst.ready = True
                    return
            except SignerError as e:
                last_err = str(e)
            time.sleep(0.5)
        if not last_err:
            last_err = (
                f"quá {int(self.startup_timeout)}s chưa sẵn sàng. "
                + self._log_tail(inst)
            )
        inst.error = last_err
        raise SidecarPoolError(
            f"Sidecar cho {inst.proxy_label} không lên được: {last_err[:300]}"
        )

    def _log_tail(self, inst: SidecarInstance, lines: int = 4) -> str:
        try:
            text = Path(inst.log_path).read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
        except OSError:
            return ""
        tail = " | ".join(x.strip() for x in text[-lines:] if x.strip())
        return f"log cuối: {tail}" if tail else ""

    def _free_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return int(s.getsockname()[1])

    @staticmethod
    def _stop(inst: SidecarInstance) -> None:
        proc = inst.proc
        if proc is not None and proc.poll() is None:
            if os.name == "nt":
                try:
                    # KHÔNG dùng capture_output=True: nó tạo thread đọc
                    # stdout/stderr, mà lúc interpreter đang tắt thì không
                    # tạo được thread nữa -> RuntimeError -> quên dọn
                    # Chrome, sidecar sót lại và chiếm RAM.
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        timeout=15,
                    )
                except (OSError, subprocess.SubprocessError, RuntimeError):
                    try:
                        proc.kill()
                    except (OSError, RuntimeError):
                        pass
            else:
                try:
                    proc.terminate()
                    proc.wait(timeout=10)
                except (OSError, subprocess.SubprocessError):
                    try:
                        proc.kill()
                    except OSError:
                        pass
        if inst.profile_dir:
            shutil.rmtree(inst.profile_dir, ignore_errors=True)
        inst.proc = None
        inst.ready = False
