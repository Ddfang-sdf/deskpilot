# ISS-0116:【设计引入】CDP 路由 render_origin 取顶层窗口原点,漏掉浏览器 chrome 高度——y 坐标系统性短约 85px,点击落空

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0116 |
| 标题 | `browser_get_rect` CDP 路由坐标换算:`render_origin()` 用顶层窗口矩形原点,而 CDP `DOM.getBoxModel` 返回的是**页面视口**坐标(原点=网页内容区左上角,在标签条+地址栏之下)——两原点差一个浏览器 chrome 高度,y 系统性短约 85px(dpr=1),x 无偏差(横向无 chrome) |
| 严重级 | **高**(写正确性:REQ-005 核心承诺「browser_get_rect 坐标可直接喂 click」不成立——按报告坐标点击全部落在目标上方 ~85px 处,页面元素点击系统性落空) |
| 状态 | **修复完成待验收**(2026-09-28:sdfang 裁「修复问题」,按推荐改法 A 落地;TC-116-01/02 红→绿,待实盘终验+重发布) |
| 提出 | 2026-09-28 v0.4.4 发布页实盘:点「刷新」两次落空,地址栏重输 URL 才加载成功,起疑后受控测量证实 |

## 1. 实证链(2026-09-28,受控测量)

1. 共管 Edge(dpr=1,窗口矩形 `[1912,-9,3848,1087]`)加载 github.com releases 页;
2. `browser_get_rect("Find a release")` → `[3246, 203, 3405, 223]`;
3. 同刻截图直读:搜索框实际位于虚拟坐标约 `x 3222-3432, y 280-315`;
4. 比对:**x 吻合,y 短 77~92px**;与早前「刷新」按钮(get_rect y 527-567 vs 实际 620-655,差 ~85px)两次测量一致——系统性偏差,非偶发;
5. 旁证:早前两次按报告坐标点「刷新」均无页面响应,地址栏输入(y 58,坐标来自截图直读而非 get_rect)一次命中。

## 2. 根因(机制层)

`deskpilot/browser/rect.py:95-98` 三因子换算:`rect = render_origin + box × dpr`。

- `box` = CDP `DOM.getBoxModel`,**页面视口坐标系**(内容区左上角为 0,0);
- `render_origin()`(`deskpilot/browser/cdp.py:193-196`)= `probe.rect_of(hwnd)` = **顶层窗口** `GetWindowRect` 原点——含标签条/地址栏/收藏夹条等 chrome 区,且最大化时含不可见边框(实测窗口 top=-9);
- 两处原点不在同一坐标系:换算漏加 chrome 高度(实测 ≈85px @ dpr=1),y 因此系统性偏小;x 向无 chrome 偏移故正确。

详设 T2-01 原文「渲染窗物理矩形原点」指的是**渲染区域**原点,实现成了**顶层窗口**原点——一词之差,坐标系错位。

## 3. 为何 REQ-005 验收没抓到(测试缺口)

- 单测三因子全部 mock(probe/客户端桩自洽,原点错不错都过);
- 实盘验证缺「`browser_get_rect` → `click` 命中同一元素」的端到端闭环钉——坐标换算面只有自洽性验证,没有命中性验证。

## 4. 改法方向(待裁定,不自作主张)

- A. **渲染子窗口直测**(推荐):`render_origin` 改取渲染件子窗口矩形原点(Chromium 系类名 `Chrome_RenderWidgetHostHWND`,即「Chrome Legacy Window」)——直接量到内容区原点,零算术假设;CDP 路由只服务共管 Chromium,厂商面可控;
- B. **算术推算**:`oy = 窗口底 - innerHeight × dpr`、`ox = 窗口左 + (outerWidth - innerWidth) × dpr / 2`(`Runtime.evaluate` 现取 inner/outer)——不依赖子窗口类名,但引入「底部无状态栏/左右边框对称」等隐含假设;
- C. A 为主 + B 交叉校验偏差告警(实现成本最高)。

涉及 REQ-005 坐标换算面语义,按上报界线属设计级,请 sdfang 裁定。
补测要求(无论选哪条):补「get_rect→click 命中」端到端实盘钉,纳入验收门禁。

## 5. 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-09-28 | 建单。两组受控测量(「刷新」按钮/「Find a release」搜索框)实证 y 短 ~85px、x 正确;根因=render_origin 坐标系错位(顶层窗口原点 vs 页面视口原点);改法 A~C 待裁定;附测试缺口分析 |
| v0.2 | 2026-09-28 | sdfang 裁「修复问题」→ 按推荐 A 落地:`DesktopProbe.child_rect_by_class`(EnumChildWindows 按类名直查渲染件矩形);`CdpChannel.render_origin` 改取 `Chrome_RenderWidgetHostHWND` 子窗口原点,缺失即 WINDOW_GONE fail-closed(不退回窗口原点)。TC-116-01(渲染件原点+类名直查)/TC-116-02(缺失 fail-closed)红→绿;REQ-005 既有 32 钉全绿 |
