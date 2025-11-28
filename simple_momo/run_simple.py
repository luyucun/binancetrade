import asyncio
import sys
from pathlib import Path
import traceback

# 保证包导入正常
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simple_momo.simple_engine import SimpleMomoEngine


async def main():
    engine = SimpleMomoEngine()
    await engine.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("已手动停止")
    except Exception:
        traceback.print_exc()
        input("程序异常退出，按回车键关闭窗口...")
