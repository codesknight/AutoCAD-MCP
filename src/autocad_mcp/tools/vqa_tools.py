"""调用本地电力工程图纸 VQA 模型（InternVL3-8B + LoRA，另一个毕设项目的产出）。

模型本体不在本进程里加载——依赖体积大且和本项目（pywin32 + mcp[cli]）没有交集，
在独立进程里用 FastAPI 常驻加载（见 D:\\LiuYanhong\\Projects\\BISHE\\data\\Models\\vqa_api_server.py），
这里只是一个薄薄的 HTTP client 转发层。调用前需要先手动启动那个 API 服务，见该文件顶部注释。
"""
import httpx
from mcp.server.fastmcp import FastMCP

VQA_API_URL = "http://127.0.0.1:8933"
_TIMEOUT = 180.0  # 本机4bit量化单题推理约90~130秒，留足余量


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def ask_drawing_vqa(image_path: str, question: str) -> str:
        """向本地微调的电力工程图纸理解模型提问（针对110kV变电站图纸领域优化，
        擅长回答设备类型/数量、母线接线方式、电压等级等问题）。image_path 需为本机可访问的
        图片文件路径（PNG/JPG）。若需要先把当前 AutoCAD 图纸导出成图片，请先用其他工具导出。
        """
        try:
            resp = httpx.post(
                f"{VQA_API_URL}/vqa",
                json={"image_path": image_path, "question": question},
                timeout=_TIMEOUT,
            )
        except httpx.ConnectError:
            return (
                f"VQA 服务未连接（{VQA_API_URL}）。请先启动本地 API 服务：\n"
                r'"C:\Users\LiuYanhong\.conda\envs\power_vqa\python.exe" -m uvicorn '
                r'vqa_api_server:app --host 127.0.0.1 --port 8933'
                "\n（cwd 需要是 D:\\LiuYanhong\\Projects\\BISHE\\data\\Models）"
            )
        if resp.status_code != 200:
            return f"VQA 服务出错（HTTP {resp.status_code}）：{resp.text}"
        data = resp.json()
        return data["answer"]

    @mcp.tool()
    def vqa_service_status() -> str:
        """检查本地 VQA API 服务是否已启动、模型是否加载完成。"""
        try:
            resp = httpx.get(f"{VQA_API_URL}/health", timeout=5.0)
            return resp.text
        except httpx.ConnectError:
            return f"VQA 服务未连接（{VQA_API_URL}），尚未启动。"
