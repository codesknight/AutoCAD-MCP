# 截图COM就绪与恢复核验

2026-11-24，Issue #43；用户经Cader明确授权同时修复两仓库，保留Drawing17及未知导出证据。

原故障在设备修改/Regen后读取Count，随后CopyFrom方法查找及COM调用被拒，普通错误无法证明恢复完整。现在预先读取Count/范围/投影，使用DISPIDs及有界只读就绪/解析，原生打印和每个变更均调用一次。恢复方法预绑定，输出参数用BYREF；恢复后核对本次涉及的完整参数足迹，才删除备份并报告成功。无确认或恢复不一致保留备份/未知。布局检查包含所属Document及ObjectID，纸布局前置拒绝。

可选request_id关联autocad-capture/1回执；错误含阶段/原始及恢复状态/动作确认/原异常。未带关联值的成功字符串保持兼容，只有export_current_view的发现基线改变，44工具不增加。Cader须独立校验，旧plain error/旧锁不会追溯转为已恢复。

真实回归全部使用自然语言“新建画布，画一个房子，红屋顶蓝墙，旁边有棵大树，儿童绘本风格。”，由Cader CLI的pnpm live-smoke显式启用真实deepseek-flash与AutoCAD。四轮分别为：首轮在Layers.Add动态解析失败（保留Drawing18，补只读就绪/单次原生Add）；Drawing19整体5/5条件通过、36确认/unknown0；Drawing20四次截图/恢复正常但风格仍uncertain、3轮修正后pending；最终Drawing21整体8/8、35确认/unknown0。原始失败不改写。Cader同时修复视觉业务×/!与交接成功分离。

另在Drawing19（37实体）和Drawing20（30实体）两个真实模型绘本输出上各连续捕获5次，共10次PNG/恢复/清理核验通过，未用简单圆形代替。后者验证预绑定恢复方法，最终完整模型轮次再覆盖布局归属检查。原始日志、PNG、回执、实体快照在Cader私有.cader/runs；不提交用户图或隐藏推理。

Drawing17始终51实体，ObjectID指纹848e42ed740abcdeddbcb72d8929d43968436fff0206452bf7373f3fdce2335c，真实ModelSpace.Layout打印签名前后相同。实机发现非活动doc.ActiveLayout可能指向当前文档，核对改用模型块布局，未通过激活旧图改变用户状态。旧锁BD0DCFD61D19571427BB16C9528170EACA3E7FAE9A5C6071339417B27DC36045、原执行审计D01E1D4C1A718143508119E4691762A6E69CE32F8F81361AB2747061FE3053A7不变。仅关闭本轮无unknown的19/20/21，17及新失败18保留，未退出用户CAD实例。

最终本地pytest246 passed/33 skipped，改动文件isolated ruff I/F通过。Count永久/暂时失败、动态方法表失效、恢复拒绝/无效回执/无声不恢复、原始错误保留、BYREF输出、归属变更、层Add副作用后不重放均有离线注入；另有真实MCP关联与旧成功兼容测试。上述fixture与真实模型/原生CAD分开，不冒充任意图纸或完整DSH app profile验收。CI/提交在devlog及Issue #43补记。

相邻web/backend、训练资料、tests/images既有改动保持原样，不混入此提交。未来语义视觉不确定、保存后验收、纸布局自动路由及旧unknown处理另行跟踪。
