"""
SimpleMomo 启动脚本 (带Web界面)
使用更简单的方式启动Web服务器
"""
import asyncio
import sys
import os
from pathlib import Path

# 保证包导入正常
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simple_momo.web_server import app, state
from simple_momo.engine_with_web import SimpleMomoEngineWithWeb


async def main():
    print("""
    ╔═══════════════════════════════════════════════════╗
    ║         SimpleMomo 交易系统 (Web版)               ║
    ╠═══════════════════════════════════════════════════╣
    ║  Web界面: http://localhost:8080                   ║
    ║  按 Ctrl+C 停止程序                               ║
    ╚═══════════════════════════════════════════════════╝
    """)

    # 启动Web服务器
    print("✓ 正在启动Web服务器...")
    import uvicorn

    # 创建服务器实例
    server = uvicorn.Server(uvicorn.Config(
        app,
        host="0.0.0.0",
        port=8080,
        log_level="error",  # 只显示错误
    ))

    # 在后台运行Web服务器
    server_task = asyncio.create_task(server.serve())

    # 等待服务器启动
    await asyncio.sleep(2)
    print("✓ Web服务器已启动 -> http://localhost:8080")

    # 启动交易引擎
    print("✓ 正在启动交易引擎...\n")
    state.is_running = True  # 默认启动
    engine = SimpleMomoEngineWithWeb(web_state=state)

    # 运行引擎
    try:
        await engine.run()
    except KeyboardInterrupt:
        print("\n\n已手动停止")
        # 关闭服务器
        await server.shutdown()
    except Exception as e:
        print(f"\n\n异常退出: {e}")
        await server.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n已停止")
    except Exception as e:
        print(f"启动失败: {e}")
        import traceback
        traceback.print_exc()
        input("按回车键关闭...")

