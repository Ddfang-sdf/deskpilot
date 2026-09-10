# ISS-0055:【cleancode】Executor 上帝类——core.py 1138 行 59 方法六职族

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0055 |
| 标题 | executor/core.py 一个 Executor 类承担六职族:截图与证据图、键鼠原语与动词、文本输入与读回、UIA 元素树与寻址、桌面图标装配桥、遮挡/激活/边界守卫——1138 行 59 个 def,任何改动都在同一体内编译 |
| 严重级 | 低(可维护性;不阻断功能) |
| 状态 | 建单待排期 |
| 提出 | 2026-09-10(cleancode 审查;度量:wc 1138 行 / grep 59 def,全库最大文件) |

## 现象与证据

- `deskpilot/executor/core.py` 1138 行、59 个方法;职族混居:
  截图族(_save_shot/_screenshot 系列)、鼠标族(_click/_drag/_scroll/
  _mouse_down/up/_hold/看门狗)、文本族(_type_text/_read_edit_value)、
  元素族(get_ui_tree/_find_elements/_resolve_typed_element)、图标族
  (list_desktop_icons 桥)、守卫族(_check_point/_check_occlusion/
  _activate_if_needed/_check_drag_end)。
- 伤害实证:本次 ISS-0044/0045/0047/0048 四个不相关修复全部改同一文件,
  提交无法按职责切开(发布期亲历)。

## 方向(排期后细化)

按职族拆模块(mouse.py/text.py/elements.py/screens.py/guards.py),
Executor 退化为装配与路由;`execute()` 分发表注册制。约束:公开入口签名
不动、测试零改动转绿为验收线。
