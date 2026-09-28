"""M4 共管浏览器管理器(REQ-005 详设 §3.7):拉起(幂等)/注册/回收/探活。

拉起参数:--remote-debugging-port=0 --force-renderer-accessibility
--user-data-dir=%LOCALAPPDATA%\\DeskPilot\\browser-profile;二进制选择序
Edge → Chrome(注册表/常见路径探测,均无则报错含安装指引)。
归属注册表为内存态:拉起写入、回收注销。P1 空壳:仅签名。
"""

from __future__ import annotations


def ensure_instance(*, registry: dict, launch, alive) -> dict:
    """幂等拉起(T4-01):注册表已有存活实例则直接复用,不重复拉起。

    入参:registry=归属注册表(内存态 dict);launch=拉起接缝(可调用,
    返回归属注册表项);alive=实例探活接缝。返回:归属注册表项
    {窗口 hwnd、CDP 端口、profile 路径、拉起时间、浏览器二进制路径}。
    """
    raise NotImplementedError("REQ-005 P1 空壳:ensure_instance 逻辑未实现")


def reclaim(*, registry: dict, kill_by_profile) -> list:
    """回收(T4-03):注册表注销 + 按 profile 路径匹配进程命令行补刀。

    入参:registry=归属注册表;kill_by_profile=按 profile 清理接缝。
    返回:被清理的实例标识清单。
    """
    raise NotImplementedError("REQ-005 P1 空壳:reclaim 逻辑未实现")


def probe(instance: dict, *, port_alive, process_alive) -> bool:
    """探活(T5-02):端口+进程双查,有一失败即判死。

    入参:instance=归属注册表项;port_alive=端口探活接缝;
    process_alive=进程探活接缝。返回:存活判定。
    """
    raise NotImplementedError("REQ-005 P1 空壳:probe 逻辑未实现")
