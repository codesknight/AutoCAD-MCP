"""扫描一批真实图纸，找出它们的文字样式引用的、AutoCAD 解析不到的字体文件
（fontFile/BigFontFile），从用户提供的"CAD字体大全"字体库里找到对应文件，
复制进 AutoCAD 的 Fonts 目录——只新增缺失的，不覆盖任何已存在的文件。

用法：
    "C:\\Users\\LiuYanhong\\.conda\\envs\\autocad-mcp\\python.exe" scripts\\fill_missing_fonts.py ^
        --input-dir "D:\\path\\to\\真实图纸目录" --limit 40

这一步只影响"打开真实图纸时中文能不能正常显示"这个观感问题，不影响
build_training_dataset.py 抽取出来的实体坐标数据本身（TextString 属性读到的
是图纸里存的真实 Unicode 文字，跟渲染用的字体文件是否存在无关）。

两个容易踩的坑（都已经在这版里处理）：
1. SHX 大字体在 fontFile/BigFontFile 里经常是不带扩展名的裸名字（比如 "HZ"），
   TrueType 字体则一定带扩展名（比如 "SimSun.ttf"）——按这两种情况分别判断，
   不能把两者混为一谈。
2. 不同容器格式的字体文件不能靠"文件名一样"互相冒充——比如 Windows 系统自带的
   simsun.ttc（TrueType Collection，装了 2 个字体）不能改名当成 simsun.ttf
   （单个 TrueType 字体）用，实测过 AutoCAD 打开图纸时报错。真要找 TrueType
   字体，必须扩展名也完全一致才算匹配；同时补一步：TrueType 字体如果已经在
   Windows 系统字体目录（C:\\Windows\\Fonts）里，就不算"缺失"，AutoCAD 本来
   就是通过系统字体解析 TrueType 的，不需要额外复制进它自己的 Fonts 目录。
"""
import argparse
import glob
import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from autocad_mcp.cad.connection import CADConnection, CADConnectionError  # noqa: E402
from autocad_mcp.cad.reference_library import close_reference_drawing, open_reference_drawing  # noqa: E402

AUTOCAD_FONTS_DIR = r"D:\LiuYanhong\Apps\AutoCAD2026\AutoCAD 2026\Fonts"
WINDOWS_FONTS_DIR = r"C:\Windows\Fonts"
FONT_LIBRARY_DIR = r"D:\LiuYanhong\Projects\BISHE\data\CAD字体大全\CAD字体大全\CAD字体大全\Fonts"


def _collect_font_names(connection, files: list[str]) -> set[str]:
    """扫描每份图纸的 TextStyles，收集所有非空的 fontFile/BigFontFile 名字。"""
    app = connection.app
    names = set()
    for i, path in enumerate(files):
        try:
            ref_doc = open_reference_drawing(app, path)
        except Exception as exc:
            print(f"[{i+1}/{len(files)}] 打开失败，跳过：{path} -- {exc!r}", file=sys.stderr)
            continue
        try:
            for style in ref_doc.TextStyles:
                try:
                    if style.fontFile:
                        names.add(style.fontFile)
                    if style.BigFontFile:
                        names.add(style.BigFontFile)
                except Exception:
                    continue
        except Exception as exc:
            print(f"[{i+1}/{len(files)}] 读取字体样式失败：{path} -- {exc!r}", file=sys.stderr)
        finally:
            close_reference_drawing(ref_doc)
    return names


def _split_name_ext(name: str) -> tuple[str, str]:
    base = os.path.basename(name)
    stem, ext = os.path.splitext(base)
    return stem.lower(), ext.lower()


def _is_shx_style_reference(name: str) -> bool:
    _, ext = _split_name_ext(name)
    return ext in ("", ".shx")


def _index_fonts(*dirs: str) -> dict[tuple[str, str], str]:
    """{(不带扩展名的小写文件名, 小写扩展名): 完整路径}，跨目录重名时保留先找到的。"""
    index: dict[tuple[str, str], str] = {}
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for entry in os.listdir(d):
            full = os.path.join(d, entry)
            if not os.path.isfile(full):
                continue
            key = _split_name_ext(entry)
            index.setdefault(key, full)
    return index


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True, help="真实图纸所在目录（递归扫描）")
    parser.add_argument("--pattern", default="**/*.dwg", help="glob 匹配模式，默认 **/*.dwg")
    parser.add_argument("--limit", type=int, default=None, help="最多扫描多少个文件")
    args = parser.parse_args()

    files = sorted(glob.glob(os.path.join(args.input_dir, args.pattern), recursive=True))
    if args.limit:
        files = files[: args.limit]
    print(f"扫描 {len(files)} 个文件收集字体引用...", file=sys.stderr)

    connection = CADConnection()
    try:
        connection.connect()
    except CADConnectionError as exc:
        print(f"连不上 AutoCAD，退出：{exc}", file=sys.stderr)
        sys.exit(1)
    connection.new_document()  # keep-alive 空白文档，全程不碰

    referenced = _collect_font_names(connection, files)
    autocad_index = _index_fonts(AUTOCAD_FONTS_DIR)
    windows_index = _index_fonts(WINDOWS_FONTS_DIR)

    missing = []
    for name in sorted(referenced):
        stem, ext = _split_name_ext(name)
        if _is_shx_style_reference(name):
            if (stem, ".shx") in autocad_index:
                continue
        else:
            # TrueType：AutoCAD 自己目录或 Windows 系统字体目录里，同名同扩展名
            # 都算已解决；不允许跨扩展名冒充（.ttc 不能顶 .ttf）。
            if (stem, ext) in autocad_index or (stem, ext) in windows_index:
                continue
        missing.append(name)

    print(f"\n引用到的字体样式共 {len(referenced)} 种，确认缺失 {len(missing)} 种：{missing}", file=sys.stderr)
    if not missing:
        print("没有缺失的字体，不需要补全。", file=sys.stderr)
        return

    library_index = _index_fonts(FONT_LIBRARY_DIR)
    copied, unresolved = [], []
    for name in missing:
        stem, ext = _split_name_ext(name)
        lookup_ext = ".shx" if _is_shx_style_reference(name) else ext
        src = library_index.get((stem, lookup_ext))
        if src is None:
            unresolved.append(name)
            continue
        dest_name = stem + lookup_ext if ext == "" else os.path.basename(name)
        dest = os.path.join(AUTOCAD_FONTS_DIR, dest_name)
        if os.path.exists(dest):
            continue  # 双重保险，不覆盖已存在的文件
        shutil.copy2(src, dest)
        copied.append((name, src, dest))

    print(f"\n从字体库补全了 {len(copied)} 个:", file=sys.stderr)
    for name, src, dest in copied:
        print(f"  {name}: {src} -> {dest}", file=sys.stderr)

    if unresolved:
        print(f"\n字体库里也没有找到的 {len(unresolved)} 个（可能需要手动处理）: {unresolved}", file=sys.stderr)


if __name__ == "__main__":
    main()
