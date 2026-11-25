# Cader P0 联合修补：新建名称安全观测

2026-11-25。用户已明确授权协同修改本仓库及 Cader；本提交仅修改普通 COMSession 新建后的名称读取和对应故障测试，不混入工作区已有 web/脚本/图片改动。

## 修复

`COMSession.execute(new_document)` 原先在 `connection.new_document()` 后直接访问 `document.Name`。实际冷态回归出现 Documents.Add 已 ACK，而该属性访问报 `<unknown>.Name`；回执没有结果文档 ID，Cader 正确保留 acknowledged_unbound。

现复用既有 `capture.prop`：通过权威 DISPID 读取 Name，对 AttributeError/COM 只读失败有限重试。没有重试 Documents.Add，没有切换文档、重放写入或清除历史屏障；持续读取失败仍返回真实 observation_failed。工具 schema、成功内容、原生 ACK 和身份契约不变。

## 检查

- `python -m pytest -q`（autocad-mcp conda 环境）：**279 passed / 33 skipped**；跳过不计作真实 CAD。
- 执行证据专项 **33 项通过**；新增立即成功、两次读失败后成功、持续失败三例，均断言 Add 仅一次。持续失败保留 ACK、20 次只读尝试和缺失结果绑定。
- `uv tool run ruff check --isolated --select I,F src/autocad_mcp/cad/backends/com_backend.py tests/test_execution_evidence.py`：通过；没有将整个历史仓库声称为格式化通过。
- 早期新测试 fake connection 缺少 disconnect，产生测试线程清理警告；补齐 fake 后全量无该警告。旧输出在 Cader 私有运行目录保留。

## 实机范围

Cader 使用原始“房子、红屋顶蓝墙、大树、儿童绘本”需求及 DWG 输出，真实模型自主选择工具。独立新建 AutoCAD 实例在无活动文档状态开始，**34 次确认写入、0 unknown、自动质量通过**；DWG 21083 字节，SHA-256 `509c0613c78be88fe92a5002aaa0b90b5af70b819bb892c1ab8a790d6f1d6c56`。同哈希副本独立只读重开 **32 实体**与审计/原生快照一致。

该隔离实例通过私有测试选择器返回真实 native IDispatch，生产 server、COMSession 和执行器正常运行；选择器仅解决多个 AutoCAD 的默认 ROT 定位歧义，不模拟 CAD 工具结果，不代表产品新增 PID 选择功能。开始前核对实例 PID 不属于用户已有实例；仅关闭其自动创建、未命名且空的启动文档以得到无文档冷态。初次将 native 代理直接登记 ROT 被系统拒绝，保留失败，改用私有 Python 选择器；用户原实例未关闭或重启。

原始复杂手稿的 Cader 联合回归与其坐标、源证据和人工验收修补同步进行，结果在 Cader 报告另记，不能用本次名称修复或简单几何夹具替代整个手稿验收。所有原图、旧屏障和失败记录保留。
