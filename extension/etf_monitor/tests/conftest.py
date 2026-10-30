"""离线测试全局保护。

功能：默认禁止非live测试联网，避免测试触发公开上游采集。
"""
import socket

import pytest


@pytest.fixture(autouse=True)
def forbid_network_for_offline_tests(request, monkeypatch):
    """功能：阻止默认测试网络；输入：测试标记；输出：安全套接字补丁。"""
    if request.node.get_closest_marker("live"):
        return
    original = socket.socket.connect

    def guarded_connect(sock, address):
        """功能：拒绝外部连接；输入：套接字地址；输出：仅本地IPC允许。"""
        if isinstance(address, tuple) and address[0] not in {"127.0.0.1", "localhost", "::1"}:
            raise AssertionError(f"离线测试禁止外部网络：{address[0]}")
        return original(sock, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
