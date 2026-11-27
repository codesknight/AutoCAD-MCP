# COM 文档快照只读稳定性 / 2026-11-27

协同Cader REQ-052整图复验。真实Open已ACK后，Documents.Count的pywin32旧包装器抛`<unknown>.Count`，文件观测失败；原文件、回执和屏障均保留，未重放该Open。

`cad/connection.py`的document_snapshot复用已有capture原生DISPID prop/method及retry_read读取Count/Item，保持文档集合/目标身份守卫和完整文件协议。重试仅限只读，不增加Open/SaveAs调用，不自动解除屏障。

离线命令：conda环境python -m pytest -q，307 passed /34 skipped；未启用真实AutoCAD测试的跳过不记通过。Ruff --select I,F对三个修改Python文件通过。新增旧包装器Count/Item失效但DISPID有效、Open一次后瞬时Count失败、持久Count失败保留ACK与幂等不重放三个场景；已有native creation fake集合补齐Count/Item原生DISPIDs。初次fake集合不支持DISPID及导入顺序失败保留在Cader私有记录，修复后通过。

真实新Cader/模型/AutoCAD整图回归使用独立实例，结果由客户端2026-11-27-whole-sheet-retest记录；本文件不把离线测试或旧artifact视为新的原图验收。CI按本次最终提交更新。用户已有web、脚本和图纸数据未纳入本次提交。
