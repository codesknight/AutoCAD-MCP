"""Render a Chinese audit report from recorded runs; does not access CAD."""
import argparse
import json
import os
from pathlib import Path
from .common import summarize

def load(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

def render(root,output):
    runs=[]
    for folder in sorted(root.iterdir()):
        if folder.is_dir() and (folder/"plan.json").exists():
            raw=folder/"cases.jsonl"
            runs.append(dict(name=folder.name,folder=folder,plan=load(folder/"plan.json"),
                result=load(folder/"qualification.json"),env=load(folder/"environment.json"),
                extra=load(folder/"environment-extra.json"),
                faults=load(folder/"faults.json"),soak=load(folder/"soak.json"),
                restart=load(folder/"restart.json"),
                benchmark=load(folder/"benchmark.json"),
                rows=[json.loads(s) for s in raw.read_text(encoding="utf-8").splitlines()] if raw.exists() else []))
    def link(path):
        try:
            return os.path.relpath(path,output.parent).replace("\\","/")
        except ValueError:
            return path.as_uri()  # Standalone local exports can be on another Windows drive.
    def number(value):
        return "—" if value is None else f"{value:,.2f}"
    def choose(phase):
        matches=[r for r in runs if r.get(phase,{}).get("completed") and r["result"].get("completed")]
        return matches[-1] if matches else None
    lines=["# CAD-09 故障测试与双后端性能报告","",
        f"记录日期：{root.name}（Asia/Shanghai）。COM 继续为默认后端。",
        "","## 范围与方法","",
        "本轮验证现有 Bridge 工具与成功路径的逐条/批量任务，不将其解释为全部工具迁移或默认后端切换验收完成。",
        "使用合成图纸、相同 acadiso 模板、毫米单位和固定几何；每个性能样本在计时外新建图纸并重启 Bridge。"
        "预热 3 次，常规测量 20 次；配对预热超过 5 秒的重任务统一测量 5 次。"
        "样本不足 20 次不计算 P95。具体计划、重任务减样理由和失败样本均保留。",
        "","计时边界为 Python 后端 API，包含派发、序列化、HTTP 轮询和 CAD 执行；不包含 LLM、MCP 传输、图纸准备、校验、显式视图刷新和清理。"
        "HTTP 批量与 COM 逐条仅比较成功任务的几何与耗时，不视为同等原子事务。","",
        "详细复现方法见 [benchmarks/README.md]("+link(Path("benchmarks/README.md").resolve())+")。","",
        "## 运行记录（含失败尝试）","",
        "| 运行 | 阶段 | 完成清理 | 状态/错误 | 原始样本 |",
        "| --- | --- | --- | --- | --- |"]
    for r in runs:
        q=r["result"]
        status=q.get("error_type") or ("完成" if q.get("completed") else "进行中/未完成")
        lines.append(f"| {r['name']} | {r['plan']['mode']} | {q.get('completed',False)} | {status} | [JSONL]({link(r['folder']/'cases.jsonl')}) |")
    envrun=next((r for r in reversed(runs) if r["env"]),None)
    if envrun:
        env=envrun["env"]
        extra=next((r["extra"] for r in runs if r["extra"]),{})
        lines+=["","## 环境","",f"- CAD：{env['cad_version']}；SDK：{env['sdk']}；Python：{env['python_version']}。",
            f"- CPU：{extra.get('cpu','未采集')}；物理内存：{number(extra.get('ram_bytes',0)/1073741824)} GiB。",
            f"- 被测 DLL SHA-256：§{env['bridge_sha256']}§。",
            f"- 代码基线：§{env['git_sha']}§；完整版本及源文件哈希见各运行环境 JSON。",
            "- 既有 Web 工作区改动未纳入本轮提交；没有使用私有 DWG。"]
    fault=choose("faults")
    lines+=["","## 原生故障矩阵",""]
    if fault:
        cases=[dict(c) for c in fault["faults"]["cases"]]
        restart=choose("restart")
        if restart and restart["restart"].get("passed"):
            cases=[dict(case="cad_process_restart",status="passed",
                evidence={"separate_run":restart["name"],"old_client_rejected":True,
                          "explicit_recovery_verified":True,"original_processes_preserved":True})
                if c["case"]=="cad_process_restart" else c for c in cases]
        lines += [f"通过 {sum(c['status']=='passed' for c in cases)} 项，失败 {sum(c['status']=='failed' for c in cases)} 项，未执行 {sum(c['status']=='not_run' for c in cases)} 项。","",
            "| 用例 | 状态 | 证据或限制 |","| --- | --- | --- |"]
        for c in cases:
            detail=c.get("evidence") or c.get("reason") or c.get("detail") or c.get("error_type")
            lines.append(f"| {c['case']} | {c['status']} | {json.dumps(detail,ensure_ascii=False)} |")
        lines+=["","注：断连通过客户端传输故障注入实现，底层写请求真实到达 Bridge；revision 外部修改由 COM 执行，不冒充人工 UI 操作。"]
        if restart:
            lines += ["",f"CAD 进程重启证据另见 [{restart['name']}]({link(restart['folder']/'restart.json')})；原始主矩阵的未执行记录保持不变。"]
    else:
        lines+=["尚无完整且完成清理的故障运行；不得记为验收通过。"]
    soakrun=choose("soak")
    lines+=["","## 连续混合调用",""]
    if soakrun:
        s=soakrun["soak"]
        start,end=s["memory_start"],s["memory_end"]
        lines += [f"- 持续 {s['duration_seconds']/60:.2f} 分钟；成功 {s['successful_calls']} 次，失败 {s['failed_calls']} 次。",
            f"- 混合调用描述性 P50 / P95：{number(s['p50_ms'])} / {number(s['p95_ms'])} ms；不同操作混合，不用于后端速度对比。",
            f"- CAD 私有内存：{start['private_bytes']/1048576:.1f} → {end['private_bytes']/1048576:.1f} MiB。",
            "- 每分钟资源原始值保留在 JSONL 中。单次 30 分钟结果不能证明长期无泄漏。"]
    else:
        lines += ["尚无完整且完成清理的连续测试；不得记为验收通过。"]
    bench=choose("benchmark")
    lines+=["","## 性能对照",""]
    if bench:
        rows=summarize(bench["rows"])
        lines += ["以下单位均为毫秒。失败数不从样本数中隐藏；P95 的空白表示样本量不足。","",
            "| 场景 | 实体数 | 后端 / 模式 | 样本 | 失败 | 中位数 | P95 | 最大值 |",
            "| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |"]
        for r in rows:
            lines.append(f"| {r['scenario']} | {r['size']} | {r['backend']} / {r['mode']} | {r['samples']} | {r['failed']} | {number(r['median_ms'])} | {number(r['p95_ms'])} | {number(r['max_ms'])} |")
        lines += ["","### 抽样依据",""]
        for p in bench["benchmark"]["groups"]:
            lines.append(f"- {p['scenario']} / {p['size']}：{p['samples']} 次；{p['reason']}。")
        lines+=["","冷连接只指 CAD 已启动时的首次后端连接，不是 AutoCAD 冷启动。"
            "逐样本的请求数、响应体大小、Bridge 队列/执行时间及内存数据见原始记录。"
            "归一化的 common_json_bytes 只用于相同字段比较，不是 COM IPC 传输字节数。"]
    else:
        lines+=["尚无完整且完成清理的性能运行；不得填写推测的加速比。"]
    lines+=["","## 清理与结论边界","",
        "各运行 cleanup.json 独立记录测试图纸、监听停止及原活动图纸恢复结果。用户原有 CAD 实例保留；只有显式标为自建且无原有文档的进程才允许退出。",
        "","本轮不切换默认 COM。HTTP 目前的工具覆盖、查询上限、部署矩阵及持久故障恢复仍有限；"
        "未执行项和失败运行均须保留，不能将本报告描述为全部路线图已验收。",""]
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text("\n".join(lines).replace("§",chr(96)),encoding="utf-8")
    return runs

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    render(args.root.resolve(),args.output.resolve())

if __name__=="__main__":
    main()
