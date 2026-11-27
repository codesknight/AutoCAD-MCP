# COM原生局部窗口与PNG介质回执

日期：2026-11-27（Asia/Shanghai）。配合Cader REQ-052 / [Cader #20](https://github.com/codesknight/Cader/issues/20)，复用既有capture恢复事务，未重建后端。

## 接口

export_current_view新增可选world_window=[xmin,ymin,xmax,ymax]（WCS XY平面）和min_long_edge（0沿用默认；512..4096选取真实PNG介质）。局部窗口只接受俯视且无视图扭转；模型布局限制、目标文件不覆盖、单次原生派发、恢复读回和未知结果不重试均保持。

客户端提供request_id时返回autocad-capture/1回执，新增字段仅在请求窗口/分辨率时出现：requested_view与view_evidence，包含世界/DCS窗口、实际选择的介质及预期像素、configuration_verified。打印前须独立读回真实窗口/PlotType/旋转/缩放/居中/介质设置，setter静默无效不得宣称局部截图；失败进入原恢复路径。无新参数的旧返回字段不变。相邻Cader适配核对请求窗口、原生动作、PNG实际尺寸和恢复证据。

没有权威pixel_to_world映射；窗口与fit设置不冒充精确像素变换，编辑仍通过原生实体ID。未支持的介质不插值放大，打印不发起；已更改设置则恢复并给出安全证明，不能把unknown改成未执行。

## 实际验证

- Python组件测试覆盖窗口、真实介质选择、无合格介质、非法输入和静默窗口setter的拒绝及状态恢复；实际stdio tools/list更新export_current_view一项基线。
- 全量pytest **304 passed / 34 skipped**（未显式启用的CAD测试跳过），最终CI结果在PR记录；旧基线发现新schema不一致的一次失败保留，修复仅同步该工具实际schema，未降低测试要求。
- 真实AutoCAD 2026原生probe使用已隔离PID180452、本轮原始大图Agent产生的owned文档中的实际文字实体，没有创建/打开/保存/激活/关闭图纸或修改几何。按实体实际bbox选择窗口，调用生产CADController/capture，真实介质QHD 2560×1440，文件18061 bytes，SHA256 cc1d92777506a8c09c7ad145df5682fcdc8505a746e8912887e0bbd9397e2da9；文字清晰，原DWG文件hash和实体数量不变，布局及打印状态恢复。
- 该probe只证明原生窗口截图组件；不是完整原始大图重建验收。Cader真实模型的工具选择/续跑/视觉和DWG全流程在Cader docs/validation/2026-11-27-local-visual-scope.md分开记录。打印前配置读回加强后的最终probe另保留，不能混称旧run已加载新代码。

本轮仅修改capture/controller/document_tools、必要测试/契约基线及本文档。已有web/backend、未跟踪脚本、图纸数据完全保留；旧unknown屏障不清除。

## 最终打印前读回实测

加强配置读回后的独立原生probe仍通过：QHD 2560×1440，configuration_verified/restoration_verified/cleanup_verified均true，PNG14108 bytes，SHA256 8efed9fdf77cdb3639521330954d54259c4b3f87dbeb3fa948004b5117f84a91。该次目标为第二轮原图任务的实际线实体；前次文字近景与本次配置读回分别记录，不能合并成未执行的整图验收。原文件hash和实体数保持不变，无文档激活或几何修改。

命令：`python -m pytest -q`；`python scripts/export_mcp_contract.py --output <私有工具快照>`。前者最终304通过/34跳过，后者实际stdio发现成功。Cader的actual-stdio测试另验证窗口参数进入原请求日志、窗口/像素/配置证明不符时拒绝、旧服务原生前拒绝以及未知结果不绕过；客户端不是仅增加参数声明。
