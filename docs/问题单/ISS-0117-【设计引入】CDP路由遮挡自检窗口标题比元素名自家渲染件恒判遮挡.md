# ISS-0117:【设计引入】CDP 路由遮挡自检拿顶层窗口标题比元素名——自家渲染件「Chrome Legacy Window」恒判 occluded=true

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0117 |
| 标题 | `browser_get_rect` T2-03 遮挡自检:坐标点顶层判定返回的是**窗口标题**,却拿来和**元素名**比较——CDP 路由下坐标点的顶层窗口正常就是浏览器自己的渲染件(标题「Chrome Legacy Window」),永远不等于元素名,`occluded` 恒 true,遮挡自检沦为恒真噪声 |
| 严重级 | **中**(感知可信度:坐标照给不阻断,但 occluded 恒 true 会误导 AI 以为元素被遮挡而绕行/报错;遮挡自检名存实亡——真被别的窗口盖住时也淹没在恒真里无法区分) |
| 状态 | **修复完成待验收**(2026-09-28:sdfang 裁「修复问题」,按推荐改法 A 落地;TC-117-01~03 红→绿,待实盘终验+重发布) |
| 提出 | 2026-09-28 ISS-0116 定位过程中顺带实证 |

## 1. 实证链(2026-09-28)

1. 共管 Edge 为前台窗(地址栏输入/回车均生效,窗口确在顶层);
2. `browser_get_rect("Find a release")` → `occluded: true, top_element: "Chrome Legacy Window"`;
3. 「Chrome Legacy Window」= Chromium 渲染件(`Chrome_RenderWidgetHostHWND`)的窗口标题——即**目标浏览器自己的内容区**,元素根本不可能"不被它盖住";
4. 同刻截图直读:搜索框上方无任何外来窗口遮挡——假阳性成立。

## 2. 根因(机制层)

`deskpilot/browser/rect.py:104-112`:

- `_topmost_at` 用 `WindowFromPoint` 取坐标点顶层 hwnd 的**窗口标题**;
- 判定式 `occluded = bool(top) and top != element["name"]` 拿**窗口标题**比**页面元素名**——两个命名空间恒不相等;
- 页面元素在浏览器内,坐标点顶层 hwnd 几乎必然是自家渲染件(标题≠元素名)→ `occluded` 恒 true。

详设 T2-03「遮挡自检=坐标点顶层元素判定」原意是「元素是否被**别的窗口**盖住」,实现比错了对象。

## 3. 改法方向(待裁定,不自作主张)

- A. **归属比较**(推荐):取坐标点顶层 hwnd 的**根窗口**(GA_ROOT),与目标浏览器 hwnd 同根=未遮挡,异根=遮挡并报根窗口标题——判定语义回到「是不是别人家窗口」;
- B. A + 根窗口标题为空时回报进程名,提升 top_element 可读性;
- C. 维持标题比较,仅把「Chrome Legacy Window」等已知自家渲染件标题加白名单——脆弱(厂商/版本漂移),不推荐。

注:UIA 路由同一段判定逻辑(rect.py 共用),需一并核查 UIA 路由是否同样假阳性(窗口标题 vs 控件名同样不同命名空间)。

## 4. 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-09-28 | 建单。共管 Edge 前台状态下 get_rect 恒报 occluded=true/top_element=「Chrome Legacy Window」,截图直证无外来遮挡;根因=窗口标题与元素名跨命名空间比较;改法 A~C 待裁定 |
| v0.2 | 2026-09-28 | sdfang 裁「修复问题」→ 按推荐 A 落地:`_topmost_at` 重构为 `_occluder_at(point, target_hwnd)`——WindowFromPoint 取顶层后 GetAncestor(GA_ROOT) 与目标窗根归属比对,同根=未遮挡、异根=报遮挡根窗口标题、判定失败不判遮挡;`browser_get_rect` 缝 `topmost` 更名 `occluder`(签名 +target_hwnd;target=CDP 注册表实例 hwnd / UIA 窗口句柄)。**闸门登记**:TC-BR-14 适配新缝(断言面不变)。TC-117-01(同根不误报)/02(异根照报+rect 照给)/03(target hwnd 递送)红→绿;REQ-005 既有 32 钉全绿。UIA 路由同段共用逻辑同愈(根归属比对对两路由一致生效) |
