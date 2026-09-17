# ISS-0089:【AI友好】screenshot 内联图超客户端 2000px 限制被整张拒收——源头等比降采样

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0089 |
| 标题 | screenshot 把落盘 PNG **原尺寸 base64 内联**返回,fullscreen(本机虚拟桌面 3840×1081)或大屏单屏(如 27 寸 2560 宽)长边 >2000px 时,客户端(Claude Code)图像处理步骤失败并**整张拒收**——AI 什么都看不到。整改:内联前源头等比降采样到长边 ≤2000px,落盘 PNG 保持全分辨率、`path` 照常返回,`scale_x/scale_y` 同步为缩放比 |
| 严重级 | **中高**(AI 可发现性/可用性:大屏或 fullscreen 下感知通道对 AI 完全失效;非安全缺陷,但直接削弱「AI 是直接用户」的核心能力面) |
| 状态 | **P3 完成待验收**(2026-09-17;方向 A 评审通过后按 SDD P1红→P2核对→P3绿实施;全量回归 777 passed/24 skipped/0 failed;描述压缩与两处修复备案见 §7 v0.2) |
| 提出 | 2026-09-16 sdfang 实测:27 寸曲面屏(分辨率 >本机)screenshot(scope=screen) 报 `Unable to resize image — dimensions exceed the 2000x2000px limit`;本机 24 寸 1920×1080 单屏正常 |

## 1. 现象与证据(三条证据链,均带出处)

**证据①(报错非本服务产出)**:`grep -rn "2000x2000\|dimensions exceed\|Unable to resize\|reduce its pixel" deskpilot/` **全库零命中**——该英文报错由客户端(Claude Code)发出,非 DeskPilot。

**证据②(本机真实分辨率,取自 `enum_monitors()`——MCP screenshot `monitors` 字段同源)**:
- 本机双屏各 1920×1080(24 寸);虚拟桌面外接 = **3840×1081**
- fullscreen → 返回 3840×1081 图(**宽 3840 > 2000**,本机 fullscreen 亦会触发)
- screen=0/1(单屏)→ 1920×1080(**两边 < 2000,本机通过**)——与「本机单屏 ok」吻合
- 另一台 27 寸曲面屏分辨率更大(单屏长边 > 2000)→ screen 单屏即超限失败——与「另一台失败」吻合

**证据③(我方返回路径,`mcp_server.py`)**:screenshot 返回在两处(http backend `:356-361`、local backend `:378-385`)把落盘 PNG **原尺寸读字节 → base64 → `types.ImageContent` 内联**,**无任何降采样**;客户端拿超限大图 → resize 步骤失败 → 抛 `Unable to resize image`。仅 `name == "screenshot"` 走内联图路径(click/drag 证据图仅落盘不内联;get_clickable_map/get_ui_tree 返回坐标/文本不内联图)——**本单范围恰为 screenshot 内联这一条路径**。

## 2. 根因(机制层)

**客户端限制 × 我方无降采样,两者叠加**:

- **客户端侧(外部约束)**:据 [Anthropic vision 文档](https://platform.claude.com/docs/en/build-with-claude/vision),图像单边正常上限 8000px,**但一个请求/上下文图片 >20 张时上限降到 2000×2000px**;Claude Code 发送前有客户端 resize 步骤,超 2000px 长边即失败([Claude Code #53170](https://github.com/anthropics/claude-code/issues/53170) open,[#13383](https://github.com/anthropics/claude-code/issues/13383)、[#37418](https://github.com/anthropics/claude-code/issues/37418);同类 [chrome-devtools-mcp #879](https://github.com/ChromeDevTools/chrome-devtools-mcp/issues/879)、[mobile-mcp #140](https://github.com/mobile-next/mobile-mcp/issues/140))。**最新版未解决**(#53170 提议「源头按比例缩到 2000px」尚未合并)。
- **我方侧(可控)**:`mcp_server` 内联返回原尺寸 PNG,从不降采样 → 把超限图直接推给客户端 → 触发其失败。**外部限制改不了,但我方源头降采样能根治**(正是官方与 #53170 建议的 resize-at-source)。

## 3. 整改方向 A(已裁定)

| # | 改动 | 说明 |
|---|------|------|
| A1 | **内联图等比降采样** | screenshot 返回路径内联前:长边 >阈值(`INLINE_MAX_PX=2000`,单源常量,理由=客户端上限)则**等比缩放**到长边 ≤阈值;**等比=整幅内容全保留,非裁剪**;长边 ≤阈值则**原样返回零缩放**(本机单屏不受影响) |
| A2 | **落盘 PNG 保持全分辨率** | `_save_shot` 落盘的原图**不动**;返回的 `path` 仍指全分辨率文件 → `ocr(path)`/`template_match(path)`/detect CV 全读全分辨率,**底层数据与定位精度零丢失** |
| A3 | **scale 元数据同步(坐标契约不漂移)** | 内联图缩放比 `f = 内联长边/原长边 (≤1)`;`scale_x=scale_y=f`。契约修订:原「scale 恒 1.0、图像像素+virtual_rect 偏移=虚拟坐标」(ISS-0021 C)→ 改为「**虚拟坐标 = virtual_rect 原点 + 内联像素 / scale**」;f=1.0 时退化为原语义。`virtual_rect`/`path` 保持全分辨率不变 |

**取舍如实记账**:内联预览图损失像素细节(小字/细线变软),但 ①对比现状(整张拒收=100% 丢失)严格更优;②全分辨率原图在盘、`path` 照返、ocr/detect/坐标全不丢;③需要清晰细节时 AI 用 `path` 回读全分辨率。

**被否方案**:只回 path 不内联(丢「直接看」能力)/切图分块(多图撞 >20 张规则+复杂度)——均不如 A 平衡,见会话记录。

## 4. 验收口径(要点,测试设计见 §6)

- 长边 >2000 的截图:内联图长边 ≤2000 且**等比**(宽高比守恒);`path` 落盘图仍全分辨率;`scale_x=scale_y=f<1`;
- 长边 ≤2000 的截图:内联图**逐像素不变**、`scale=1.0`(零损失回归);
- 坐标契约:内联像素 / scale + virtual_rect 原点 = 虚拟坐标(换算精确);
- ocr(path)/detect 读全分辨率,精度不因内联降采样下降;
- 现有 screenshot 其余键集/语义(coord_space/monitors/coverage/vision_note)不回退。

## 5. 约束

- 只动 screenshot **内联返回**这一条路径(mcp_server);不动 `_save_shot` 落盘、不动 executor 捕获尺寸;
- 阈值 2000 单源常量(客户端上限驱动,非安全参数);是否 policy 可配留作后续(本单先常量,避免扩面);
- 降采样用项目既有依赖(PIL),不引新库;
- scale 语义变更**文档随代码走**:ISS-0021 C 注释、详设坐标契约段同步翻页;
- 实现走 SDD P1→P2→P3。

## 6. 测试设计(P1 前置,五要素)

### 6.1 公开入口(设计定义)

| 入口 | 契约 |
|------|------|
| `mcp_server._downscale_inline(png_bytes: bytes, max_px: int = INLINE_MAX_PX) -> tuple[bytes, float]` | 纯函数:入原 PNG 字节,长边 >max_px 则等比缩到长边 ≤max_px 重编码 PNG,返回 (新字节, f);长边 ≤max_px 返回 (原字节, 1.0) 不重编码 |
| `mcp_server.INLINE_MAX_PX = 2000` | 单源常量 |
| screenshot 返回路径(http `:356` + local `:378`) | 读 `path` 全分辨率字节 → `_downscale_inline` → base64 内联;并 patch `data["scale_x"]=data["scale_y"]=f`(f<1 时);`path`/`virtual_rect` 不改 |

### 6.2 用例(单元层为主 + 一条形态/集成守装配)

| # | 场景 | 前提 | 步骤 | 预期 | 断言(出处=直出) |
|---|------|------|------|------|------|
| TC-DS-01 | 超限等比缩 | 造 3840×1081 PNG 字节 | `_downscale_inline(b, 2000)` | 长边=2000,等比 | `Image.open(BytesIO(out)).size == (2000, round(1081*2000/3840))`;`abs(f - 2000/3840) < 1e-6` |
| TC-DS-02 | 未超限零缩放 | 造 1920×1080 PNG 字节 | `_downscale_inline(b, 2000)` | 原样返回 | `out is b`(同一对象,未重编码);`f == 1.0` |
| TC-DS-03 | 宽高比守恒 | 3840×1081 | 缩放后 | 比例守恒 | `abs(out_w/out_h - 3840/1081) < 0.02` |
| TC-DS-04 | 边界=阈值不缩 | 造 2000×1500 PNG | `_downscale_inline(b,2000)` | 长边恰 2000=阈值,不缩 | `out is b`;`f==1.0`(> 才缩,== 不缩) |
| TC-DS-05 | 装配:内联≤2000 且落盘全分辨率 | 真 executor 截 fullscreen(或 region 造 >2000),走 screenshot 返回路径 | 取 contents 里 ImageContent 的 data 解码 + 读 data["path"] 落盘图 | 内联长边≤2000;落盘=全分辨率;scale=f | 内联 `Image.open(BytesIO(b64decode(data))).size` 长边≤2000;`Image.open(path).size` 长边>2000(全分辨率保住);`data["scale_x"]==f<1` |
| TC-DS-06 | 坐标契约换算 | TC-DS-05 的内联图与 virtual_rect | 内联像素 (i,j) → 虚拟坐标 | 换算精确 | `vx == virtual_rect[0] + i/scale_x`(取内联图某已知点验证,f=1 时退化为 +i) |

### 6.3 守门核对

- **R1 装配**:TC-DS-05 走真实 screenshot 返回路径(http+local 两 backend 各一条或参数化),证内联降采样真接到 mcp_server,非只测纯函数;
- **R5 终效应**:断言打内联 ImageContent 的**解码后像素尺寸**与**落盘文件像素尺寸**(数据层直出),非中间量;
- **R6 双向映射**:验收§4 五条 → TC-01/03(等比+比例)/TC-02/04(零损失回归)/TC-05(落盘全分辨率+scale)/TC-06(坐标契约);ocr/detect 全分辨率由 A2「path 不改」保证,TC-05 断言落盘尺寸>2000 即覆盖;
- **R7 失效原因**:全正向断言零 raises;若实现漏接内联路径 → TC-05 内联尺寸仍>2000 立红;若误缩落盘 → TC-05 落盘尺寸≤2000 立红;不会借道假绿。

## 7. 变更记录

| 版本 | 日期 | 内容 |
|------|------|------|
| v0.1 | 2026-09-16 | 建单。sdfang 实测大屏 screenshot 报 2000px 错;三条证据链坐实(①报错串全库零命中=客户端发②本机 enum_monitors 分辨率:fullscreen 3840 宽>2000、单屏 1920<2000③mcp_server:356/378 原尺寸内联无降采样);权威证据:Anthropic vision >20图降 2000px 上限、Claude Code #53170/#13383/#37418 open 未解决。整改方向 A(源头等比降采样+落盘保真+scale 同步)sdfang 裁定;测试设计 TC-DS-01~06 落档。**评审通过,进入 P1** |
| v0.2 | 2026-09-17 | **P3 完成回填**。①实现落点:mcp_server.py——`INLINE_MAX_PX=2000` 单源常量;`_downscale_inline` 纯函数(PIL `Resampling.LANCZOS` 等比重编码;≤阈值原样直通返回同一对象);新增 `_screenshot_inline_b64` 共用装配(读 path 全分辨率→降采样→b64;f<1 时 patch `data["scale_x"]=data["scale_y"]=f`;OSError→None 不阻断,沿用原容错语义);http/local 两返回路径重接=**先降采样+scale patch 再 dump payload**(原码先 dump 后挂图,patch 不前移则文本载荷不带 scale);screenshot 描述换写(ISS-0090 #5 归属本单:降采样/scale/path 语义入描述)。core.py ISS-0021 C 注释翻页(落盘恒 1.0/内联或 f<1,除法契约)。REQ-003 详设两处「scale 恒 1.0」交叉引用加注 ISS-0089 A3(检测器读落盘全分辨率不受影响)。②SDD 实证:P1 红三条——TC-DS-01 尺寸 (3840,1081)≠(2000,563) 且 f=1.0;TC-DS-05 local/http 内联仍 3840>2000;TC-DS-02/03/04 红期即绿=零损失回归守卫正确就位;P3 绿(6 passed);修复 2 次(预算内):Path/base64 提模块级(原 import 在 build_server 内,helper 提级后 NameError)、描述压缩误丢 ISS-0037 sv06「图像不可见」子串→补回再压至 198 字符;全量回归 **777 passed, 24 skipped, 0 failed**(基线 771/24)。③既有兼容:TC-CT-07(scale_x×width≈rect 宽)走 scope=window 普通窗 <2000px 不触发降采样,断言不受契约修订影响;iss83 描述闸门(screen/屏/region/精读/coverage)+bound04(查看)+desc05(≤200)+sv06(图像不可见)全保。④契约备忘:scale 语义由「乘」(scale×图像宽≈虚拟宽)翻为「除」(虚拟坐标=virtual_rect 原点+内联像素/scale);f=1 时两式等价,历史行为零漂移;仅长边>2000 的内联图出现 f<1;落盘原图/ocr/template_match/detect 全分辨率精度零丢失(A2) |
