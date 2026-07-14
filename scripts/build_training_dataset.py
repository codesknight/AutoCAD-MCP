"""批量扫描真实 DWG 图纸，把每个实体转换成"重建它需要调用哪个 MCP 工具"的记录，
产出 JSONL 训练数据集（不训练任何模型——这一步只是数据管道，后续训练是独立工作）。

用法：
    "C:\\Users\\LiuYanhong\\.conda\\envs\\autocad-mcp\\python.exe" scripts\\build_training_dataset.py ^
        --input-dir "D:\\path\\to\\真实图纸目录" --output dataset.jsonl [--limit 200] [--pattern **/*.dwg]

需要真实打开的 AutoCAD 实例（脚本只读打开每份图纸，Documents.Open 的
ReadOnly=True，不修改、不保存任何源文件）。可以随时 Ctrl+C 中断——输出是逐行
JSONL，已经写过的文件会被跳过，重新跑这个命令就能从断点续跑。

输出每行一个 JSON 对象：
    {"file": "...", "entity_count": 总实体数, "converted_count": 成功转换成工具调用的实体数,
     "tool_calls": [{"tool": "draw_line", "args": {...}}, ...]}
"""
import argparse
import glob
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from autocad_mcp.cad.connection import CADConnection, CADConnectionError  # noqa: E402
from autocad_mcp.cad.reference_library import close_reference_drawing, open_reference_drawing  # noqa: E402
from autocad_mcp.cad.training_export import entity_to_tool_call  # noqa: E402


def _already_processed(output_path: str) -> set[str]:
    if not os.path.exists(output_path):
        return set()
    done = set()
    with open(output_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                done.add(json.loads(line)["file"])
            except Exception:
                continue
    return done


def _process_one(connection: CADConnection, file_path: str) -> dict:
    app = connection.app
    ref_doc = open_reference_drawing(app, file_path)
    try:
        entity_count = 0
        tool_calls = []
        for entity in ref_doc.ModelSpace:
            entity_count += 1
            call = entity_to_tool_call(entity)
            if call is not None:
                tool_calls.append(call)
        return {
            "file": file_path,
            "entity_count": entity_count,
            "converted_count": len(tool_calls),
            "tool_calls": tool_calls,
        }
    finally:
        close_reference_drawing(ref_doc)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True, help="真实图纸所在目录（递归扫描）")
    parser.add_argument("--output", required=True, help="输出 JSONL 文件路径")
    parser.add_argument("--pattern", default="**/*.dwg", help="glob 匹配模式，默认 **/*.dwg")
    parser.add_argument("--limit", type=int, default=None, help="最多处理多少个文件（不填则处理全部匹配到的文件）")
    args = parser.parse_args()

    files = sorted(glob.glob(os.path.join(args.input_dir, args.pattern), recursive=True))
    if args.limit:
        files = files[: args.limit]

    done = _already_processed(args.output)
    todo = [f for f in files if f not in done]
    print(f"匹配到 {len(files)} 个文件，已处理 {len(done)} 个，本次待处理 {len(todo)} 个", file=sys.stderr)

    connection = CADConnection()
    try:
        connection.connect()
    except CADConnectionError as exc:
        print(f"连不上 AutoCAD，退出：{exc}", file=sys.stderr)
        sys.exit(1)

    # 全程保留一个空白 keep-alive 文档，避免中途所有文档都被关掉导致
    # 后续 Documents.Open 行为异常；批处理过程中不关心"当前活动文档"是谁。
    connection.new_document()

    processed, failed = 0, 0
    start_time = time.time()
    with open(args.output, "a", encoding="utf-8") as out:
        for i, file_path in enumerate(todo, 1):
            try:
                record = _process_one(connection, file_path)
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
                out.flush()
                processed += 1
            except Exception as exc:
                failed += 1
                print(f"[{i}/{len(todo)}] 跳过（打开/读取失败）：{file_path} -- {type(exc).__name__}: {exc!r}", file=sys.stderr)
                continue
            if i % 20 == 0:
                elapsed = time.time() - start_time
                print(f"[{i}/{len(todo)}] 已处理 {processed}，失败 {failed}，耗时 {elapsed:.0f}s", file=sys.stderr)

    print(f"完成：成功 {processed}，失败 {failed}，输出写到 {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
