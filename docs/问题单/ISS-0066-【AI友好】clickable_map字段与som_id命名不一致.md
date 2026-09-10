# ISS-0066:【AI友好】get_clickable_map 输出 id 与 click_element 入参 som_id 命名不一致

| 项 | 内容 |
|----|------|
| 问题单号 | ISS-0066 |
| 标题 | get_clickable_map 返回元素字段叫 id,click_element 的入参叫 som_id——同一棵 SoM 树上的编号两个名字,AI 要自行对应;跨会话/跨文档时易误配 |
| 严重级 | 低(命名一致性;AI 一次性认知成本) |
| 状态 | 建单待评审 |
| 提出 | 2026-09-08 手工测试待查⑥;2026-09-10 转正建单 |

## 现象与证据

get_clickable_map entries[*].id ↔ click_element(som_id=)——同物两名。

## 方向(评审二选一)

| # | 方向 |
|---|------|
| ① | 输出字段改名 som_id(与入参一致;破坏已读该字段的存量脚本) |
| ②(倾向) | 双写过渡:输出同时给 id 与 som_id(同值),描述注明 id 废弃日程;下个大版本删 id |

约束:工具描述同步;用例=输出双字段同值(直出)+click_element 正常消费。
