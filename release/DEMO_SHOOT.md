# 演示 GIF 重录分镜脚本(2026-09-03 拍摄)

目标:替换 `assets/demo.gif`(现版 2026-08-24 录制,无加白/撤回/实拍图)。
一个故事讲全 v0.3 招牌能力:**撤回 → 加白(带实拍图)→ 危险审批(带实拍图)→ 撤销通知**。

## 产物规格

- `assets/demo.gif`:≤5MB,时长 25~35s,宽 960px(超限依次降 800/720px、8→6fps)
- 录制:`.venv/Scripts/python scripts/record_demo.py --out assets/demo.gif --seconds 35 --fps 8 --width 960 --colors 128 --countdown 5`
- 录全屏(主屏),一镜到底;翻车就整条重录,不拼接

## 开拍前检查清单(逐项过)

| # | 检查 | 怎么验 |
|---|---|---|
| 1 | daemon 在线且提权 | `curl http://127.0.0.1:9420/health`;不在则提权启动(见下) |
| 2 | 西柚窗口开着(断连状态即可,大按钮"未启动") | find_window seeyou.exe |
| 3 | seeyou.exe 在白名单(撤回镜头的起点) | dist\policy.yml 含 seeyou.exe |
| 4 | 桌面只留:西柚窗口 + 一个干净终端;隐私窗口全关 | 肉眼 |
| 5 | 勿扰/专注助手开(防系统通知乱入) | 设置→系统→通知 |
| 6 | 鼠标/键盘 35s 内只有分镜动作 | 人自觉 |

daemon 重启(若过夜掉了):管理员 PowerShell →
`Start-Process C:\code\workspace\deskpilot\dist\deskpilot.exe '--daemon' -WorkingDirectory C:\code\workspace\deskpilot\dist -WindowStyle Hidden`

## 分镜表(总时长≈30s)

| 镜 | 时长 | 谁 | 动作 | 画面要点 |
|---|---|---|---|---|
| 0 | 3s | — | 静止 | 西柚窗口居中可见,展示初始状态 |
| 1 | 6s | **人** | 右键托盘 DeskPilot 图标 → 白名单管理 → 西柚行 ⛔(悬停出动效)→ 点击移除 → 关管理窗 | 撤回;悬停红色脉冲要停 1s 让人看清 |
| 2 | 8s | AI 发 / 人点 | AI:`attach seeyou.exe` → **入白三态弹框**(带西柚前置实拍图)→ 人点「永久加入」→ 弹框消失、attach 成功 | 弹框出现后停 2s 再点,实拍图是主角 |
| 3 | 9s | AI 发 / 人点 | AI:`key alt+f4`(绑定窗)→ **L3 审批框**(命令文本+实拍图+倒计时)→ 人点「批准一次」→ 西柚窗口关闭 | 同上停 2s;关闭瞬间别动鼠标 |
| 4 | 4s | — | 静止 | 西柚已关,桌面干净收尾 |

镜头 2/3 的弹框**由人亲手点**——点击即 footage,AI 代点等于演示绕过审批,禁止。

## AI 侧操作(镜头 2/3 触发,人到齐后按序发)

```powershell
# 镜头2:入白(镜头1撤回完成后发)
curl -X POST http://127.0.0.1:9420/call -H "Content-Type: application/json" `
  -d '{"tool":"attach","params":{"process":"seeyou.exe"}}'
# → 返回 token,记下用于镜头3

# 镜头3:危险键(入白成功后发)
curl -X POST http://127.0.0.1:9420/call -H "Content-Type: application/json" `
  -d '{"tool":"key","params":{"key":"alt+f4","token":"<镜头2的token>"}}'
```

## 拍完收尾

1. 自查 gif(帧数/时长/体积/内容)——我先看,人再看
2. README.md / README_EN.md 演示描述行同步更新(加"撤回/加白"字样)
3. `release/RELEASE_NOTES.md` 注释里"重录方法"补一句指向本文件(现注释悬空)
4. 提交 + 请示推送(资产替换不进 Release,无需发版)

## 备选方案(西柚明天起不来时)

记事本:先从 dist\policy.yml 撤 notepad.exe(管理窗操作)→ attach notepad.exe 走入白 → alt+f4 走 L3。其余分镜不变。
