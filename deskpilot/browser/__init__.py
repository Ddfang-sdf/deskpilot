"""REQ-005 浏览器翻译层(P1 空壳:仅模块/函数签名,零逻辑)。

六模块(详设 §2):M1 感知路由器(router)/M4 共管浏览器管理器
(manager)/M5 CDP 通道(cdp)/M6 UIA 通道(uia)/两 MCP 工具面
(snapshot/rect)。装配规则:S-01 两工具注册 L0 直放;S-02 唯读依赖
websocket-client(仅 cdp);S-03 uia 复用 executor 感知面;
S-04 冻结/安全桌面语义由既有 L0 闸门覆盖,本包零分支。
"""
