## DeskPilot v{{VERSION}} — 安全桌面驾驶舱

**安全桌面驾驶舱：让 AI agent 自主、安全地操作 Windows 电脑。** 任何 MCP 客户端即插即用。

### 下载与校验

`{{ZIP_NAME}}` —— 解压后**保持 `policy.yml` 与 `deskpilot.exe` 同目录**（exe 启动时从同目录加载安全策略）。

SHA256（`{{ZIP_NAME}}`）：

```
{{SHA256}}
```

核对方法（PowerShell）：`(Get-FileHash .\{{ZIP_NAME}} -Algorithm SHA256).Hash.ToLower()` 输出与上面一致即未被篡改。

### 本版内容

{{CHANGES}}

### 快速接入（Claude Code 示例）

```powershell
claude mcp add deskpilot -- "C:\tools\deskpilot\deskpilot.exe"
```

完整安装指导（下载校验 / 四客户端配置 / 常驻 daemon 与开机自启 / policy.yml 定制 / 验证清单 / 升级 / 内网分发 / 常见问题）见仓库 [docs/INSTALL.md](https://github.com/Ddfang-sdf/deskpilot/blob/main/docs/INSTALL.md)；一键安装脚本 [scripts/install.ps1](https://github.com/Ddfang-sdf/deskpilot/blob/main/scripts/install.ps1)。

### 系统要求

Windows 10/11 x64；无需安装 Python。默认白名单：notepad / explorer / mspaint / powerpnt（编辑 exe 同目录的 policy.yml 调整）。
