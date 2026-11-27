# 2026-11-28 Cader source-worklist native geometry

协同Cader REQ-053 / Issue20，复用现有COM执行回执、控制器和查询模块；不增加自然语言解析或另一个执行循环。

- `draw_polyline`新增可选非负`width`（原生ConstantWidth）；AddPolyline经过既有native ACK边界。默认0保持原调用。
- `draw_text`新增可选`width_factor`及本次新建文字的`fit_box=[xmin,ymin,xmax,ymax]`。fit仅支持90度整数倍旋转，非法范围/旋转在创建前拒绝。原生bbox读允许有界重试，Height/ScaleFactor/Move不重试；创建后拟合失败不删除、不重放已ACK实体。
- 查询新增polyline顶点、stride、闭合、OCS normal/elevation、constant_width和bulges；文字增加原生height/scale/rotation/insertion。bbox不能替代顶点或曲率证明。
- 支持矩阵及COM affected.created增加draw_polyline，服务仍独立。旧stdio契约fixture保留；新增两个工具的可选字段完整fixture，另验证所有旧字段及required集合不变。

实际验证：315 pytest通过，34项需要显式`--cad-integration`未启用而跳过。新负例覆盖非法参数先于Add、ACK后拟合失败不重放/删除、OCS/bulge保留及默认MCP调用兼容。Cader在已验证独立DispatchEx实例中，用原始大图的2路径与2文字完成真实原生顶点/宽度/bbox读回（4实体、0差异）并保存新的私有DWG；这是组件证据，不是完整Agent任务。第一次组件脚本因UTF-8读取失败，在新建空图后停止；核查同实例空图后继续，无CAD未知写入。

完整原始图真实模型＋Cader＋MCP联合结果另行追加；旧图和历史unknown屏障不改写。原始记录保留在Cader私有`.cader/runs/source-worklist-20261127/`。用户已有web、脚本、设计和图纸数据未纳入本次提交。

## 只读查询性能补修

真实151实体查询约20秒，协同增加原生集合Count/Item遍历、只读Invoke/InvokeTypes及单对象生命周期的DISPID缓存；绑定canonical IUnknown并在文档身份变更时清空，不缓存属性值，不跨对象沿用类型图。同ObjectID/同名文档负例及写方法拒绝有测试。相同owned图对照旧版17.430秒、首次3.496秒、后续1.689秒，所有字段0差异，0CAD写入。316测试通过/34真实CAD未启用跳过。Microsoft保证仅是对象生命周期内DISPID稳定；AutoCAD的ITypeInfo.GetIDsOfNames实测未实现，未采用跨类型缓存。原始证据由Cader私有运行目录保留。

联合Cader attempt05继续确认原生链路：221确认/0未知，214实体与停止后账本一致，待验稿另存保全。未修改原始图或旧屏障；完整图质量仍待Cader处理源细节和分层验收，不以原生ACK或部分保存宣称整图通过。MCP当前代码316通过/34未启用真实CAD跳过与151实体0差异性能证据不变。


## 原图联合回归暴露的图层读取（BUG117 / Cader #20）

Cader373e2bb＋MCP edfeef5真实attempt12中，创建两个源图层均获ACK，但首次绘图依赖预检读到不含该层的列表，拒绝于native派发前；0未知写入，随后同一任务自行恢复并推进。此现象已证实；动态Layers枚举/类型缓存是待进一步定位的原因，不能仅凭该日志断言单一根因。list_layers改为原生Count/Item及每对象权威DISPID读取Name，不沿用动态枚举器或属性值；未改变工具schema/44工具、传输或写协议。触及文件同时规范格式，其余web/脚本用户修改未纳入。

确定性夹具拒绝使用缓存迭代器，覆盖Add后新增Name及同对象Name变更。真实owned实例的新空文档先输出名称/0实体，再创建两个独占测试层，新路径连续10次均读到新增层；0模型调用、0图形实体、组件DWG另存新路径。这次同一组件内旧迭代器也读对，未重现原日志间歇失败；保留legacy_stale_observed=false，不伪称旧路已复现。317 Python通过/34真实CAD未启用跳过；Ruff isolated E4/E7/E9/F及触及文件format通过。首轮继承宿主额外lint设置报告旧兼容代码S110/BLE001，未将其说成已全面修复。真实原始整图联合回归结果后补，不以此组件或空图替代。原始数据位于Cader私有source-worklist运行目录。
