# 受控检查点恢复 v1（协同候选，未完成 Cader 续绘验收）

对应 Cader REQ-053 / BUG125 的 2026-11-28 建议。普通 COM 通过原 `execute_observed_operation` 新增两个 operation，工具总数仍为 47；HTTP 不提供此 COM 恢复协议。COM 默认、旧调用及旧 unknown 证据不变。

## 接口

1. **预先冻结**：保存成功且当前工作图 `Saved=true` 后，外层绑定其 document_id，调用 `operation=get_checkpoint_snapshot, arguments={}`。返回 binding、source（实际路径/SHA-256/字节数）、snapshot 和 snapshot_sha256。完整字段缺失或不支持实体时失败；不是现有 query_entities 的可选摘要。
2. **跨进程恢复**：新 backend 附着一个已经运行、无任何打开文档的专用 AutoCAD 实例。外层 `instance_id` 必须是当前 backend ID，`document_id=null`，持久化唯一 request_id；调用 `operation=fork_checkpoint, arguments={"grant_id":"reviewed-checkpoint-001"}`。不按旧文件名/UUID 接管旧文档，不自动启动或关闭用户文档。
3. **对账**：同一 backend 的 `get_execution_status(instance_id, request_id)` 返回真实原回执及 file_result。重复相同请求不再复制/Open。跨 backend 记录丢失仍 unresolved，不推断可重放。

成功返回 `autocad-checkpoint-fork/1`：新的 instance_id/document_id、managed=true/read_only=false、revision=null/unsupported，source/working 文件指纹、旧实例/文档引用、snapshot_sha256、完整 mapping 和 mapping_sha256、mapping_complete=true。mapping 每项为 handle/old_object_id/new_object_id/type。`quality_accepted=false` 固定，不把几何一致升级为整图质量通过。

## 本地审核授权，不让模型自证没有 unknown

仅传路径/hash、`unknown=false` 或空旧 journal 不能证明恢复权限。服务进程显式配置 `AUTOCAD_MCP_CHECKPOINT_GRANTS`，指向本地审核人员控制的目录；不提供 MCP 创建/编辑授权工具。部署时限制目录写权限，不把该目录暴露为 Agent 可写工作区。同用户可任意修改服务代码/配置的本机进程不在此权限隔离保证内。

审核人员检查原执行证据与恢复范围后，创建 `<grant_id>.json`。此文件是独立本地授权记录；未配置时能力响应 configured=false，调用拒绝。MCP 校验原证据文件摘要是否变化，但**不声称能够从任意 Cader JSONL 自动判定跨进程 unknown 已解决**。`unresolved_requests=[]` 是本地审核方的授权前提，必须包含同图所有相关 writer，不是由 LLM 填一个布尔值跳过旧屏障。

```json
{
  "contract":"autocad-checkpoint-grant/1",
  "authorized_by":"<local reviewer>",
  "execution_evidence_path":"D:\\reviewed\\execution.jsonl",
  "reviewed_execution_evidence_sha256":"<raw file SHA-256>",
  "unresolved_requests":[],
  "writer_pid":12345,
  "cad_pid":12346,
  "old_instance_id":"<previous instance>",
  "old_document_id":"<previous document>",
  "source_root":"D:\\reviewed",
  "source_path":"D:\\reviewed\\checkpoint.dwg",
  "source_sha256":"<DWG SHA-256>",
  "source_byte_size":123456,
  "output_directory":"D:\\new-output",
  "snapshot":{"contract":"autocad-checkpoint-snapshot/1","scope":"model_space","entities":[]},
  "snapshot_sha256":"<canonical snapshot SHA-256>"
}
```

示例 entities 仅展示容器；真实授权必须放入保存时实际导出的全部实体，不能以空数组代替原图。快照摘要算法为 UTF-8 JSON、sort_keys=true、ensure_ascii=false、separators=(',',':')、allow_nan=false 的 SHA-256；原文件/JSONL 摘要则按原始字节计算。源根/输出根必须存在、绝对本地路径，无 `..`/UNC/reparse/link；源必须在允许根内且为实际 DWG。PID 不存在才允许恢复，PID 被复用或无法确认时保守拒绝。

授予权限后仍只复制源文件，原文件在复制/Open/校验期间以 Windows share-read-only 句柄保持禁止写入/删除。输出为独占 checkpoint-UUID/working-UUID.dwg。原生 Open 只执行一次；必须观察到唯一新文档、实际路径/读写状态/活动身份正确。逐 Handle 比对类型及该版本所有几何字段，要求完整一一映射；不按顺序、bbox 或最近位置匹配。二次原生读取及源/副本 hash/Saved 校验后才登记 owned 和工作绑定。

## 快照字段与限制

每项必须精确包含 object_id（十进制字符串）、handle（唯一大写十六进制）、type、fields。支持 Line/Circle/Arc、轻量及二维 Polyline、单行 Text；共同字段 Layer/Color/Linetype/LinetypeScale/Lineweight/Visible。各类所需字段由 `cad/checkpoint.py:FIELDS` 固定：包含完整顶点、Normal/Elevation/Thickness、逐段 Bulges/Widths，文字包含对齐点/对齐方式/旋转/倾斜/样式名等。属性读取错误不可省略；所有浮点须有限且逐字段精确比较，不以公差猜同一实体。

范围为 ModelSpace 内上述实体的该版本 Native 字段，二维多段线仅支持 Type=0 的简单类型，不覆盖拟合多段线、图块、Hatch、MText、标注、纸空间、外部引用、样式定义或任意 DWG 内容等价。出现不支持类型拒绝整次恢复。没有 Handle 或缺字段的旧摘要不自动升级；未来扩展需要版本化字段和真实回归。COM 仍无权威 revision；两次相同读取仅作一致性守卫，不宣称事务级快照。

## 一次性记录及失败

任何复制前，授权目录独占创建 `<grant_id>.claim`，fsync 保存 grant_sha256、新实例及 request_id；该记录不自动删除。恢复创建目录/复制/Open 都进入逐动作回执。即使 Python 重启丢 journal，也不能再次消费同一授权。查无记录时需人工对账，不能删除 claim 后重试来掩盖 unknown。

file_progress 区分 grant_reserving/copy_prepared/copied_unverified/open_dispatched/opened_unverified/mapping_native_fields/verified_working_copy。无 ACK 为 result_unknown，ACK 后校验失败为 observation_failed；复制之前无动作则 not_dispatched。失败保留新旧文件、claim 和回执，未验证文档不获得 owned；不自动 Delete/Close/重放，也不宣称原子回滚。若需重新评估并另行授权，必须先处理前次已产生的副本与未知结果。

## Cader 接入及当前原始样本

Cader 应在保存时持久化新 snapshot/source 指纹及原执行账本，恢复时核对请求、新绑定和全量映射，再建立新任务实例；原 committed 不重派，unknown 先对账，原 quality=false 和过期视觉结论不能升级。最终仍由原始整图/源账本和独立 verifier 验收。

用户提供的 attempt17 原快照含 3014 个实体，但全部缺 Handle，且缺少文字对齐等新契约字段。因此本轮不能据此自动建立完整旧 ObjectID 映射；从文件重新采集得到的新快照也不能冒充原 writer 的历史冻结证据。详见[验证与接入缺口](../validation/2026-11-28-checkpoint-fork.md)。此协议和本地审核授权设计仍需 Cader 对齐，不能宣称 `/quality resume` 已可跨进程续绘。
