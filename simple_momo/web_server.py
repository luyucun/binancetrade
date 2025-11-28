"""
SimpleMomo Web监控界面
使用FastAPI + WebSocket实现实时监控
"""
import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)

app = FastAPI(title="SimpleMomo 交易监控")

# 添加CORS支持
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# WebSocket连接管理
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        """向所有连接广播消息"""
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass

manager = ConnectionManager()

# 全局状态存储（由引擎更新）
class DashboardState:
    def __init__(self):
        self.positions: Dict = {}
        self.balance: float = 0.0
        self.today_trades: int = 0
        self.today_pnl: float = 0.0
        self.win_count: int = 0
        self.loss_count: int = 0
        self.is_running: bool = False
        self.logs: List[dict] = []
        self.cooldown_symbols: Set[str] = set()
        self.global_cooldown_remaining: int = 0
        self.command_queue: List[dict] = []  # 命令队列，供引擎读取

    def to_dict(self):
        return {
            "positions": self.positions,
            "balance": self.balance,
            "today_trades": self.today_trades,
            "today_pnl": self.today_pnl,
            "win_rate": (self.win_count / (self.win_count + self.loss_count) * 100) if (self.win_count + self.loss_count) > 0 else 0,
            "is_running": self.is_running,
            "logs": self.logs[-50:],  # 只保留最新50条
            "cooldown_symbols": list(self.cooldown_symbols),
            "global_cooldown_remaining": self.global_cooldown_remaining,
        }

state = DashboardState()


def add_log(level: str, message: str):
    """添加日志到状态"""
    log_entry = {
        "time": datetime.now().strftime("%H:%M:%S"),
        "level": level,
        "message": message
    }
    state.logs.append(log_entry)
    if len(state.logs) > 100:
        state.logs = state.logs[-100:]
    # 直接广播，不使用create_task避免事件循环问题
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(manager.broadcast({"type": "log", "data": log_entry}))
    except Exception:
        pass  # 忽略事件循环错误


async def broadcast_state():
    """广播完整状态"""
    await manager.broadcast({"type": "state", "data": state.to_dict()})


# 读取HTML模板
HTML_FILE = Path(__file__).parent / "templates" / "index.html"

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    """返回主页面"""
    if HTML_FILE.exists():
        return HTML_FILE.read_text(encoding="utf-8")
    return """
    <h1>模板文件未找到</h1>
    <p>请确保 templates/index.html 存在</p>
    <p>路径: {}</p>
    """.format(HTML_FILE)

# 也支持直接访问 /index.html
@app.get("/index.html", response_class=HTMLResponse)
async def get_index():
    """返回首页"""
    if HTML_FILE.exists():
        return HTML_FILE.read_text(encoding="utf-8")
    return "<h1>模板文件未找到</h1>"


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket连接端点"""
    await manager.connect(websocket)
    # 发送当前状态
    await websocket.send_json({"type": "state", "data": state.to_dict()})
    try:
        while True:
            # 接收客户端消息（控制命令等）
            data = await websocket.receive_text()
            cmd = json.loads(data)

            if cmd.get("action") == "pause":
                state.is_running = False
                add_log("INFO", "策略已暂停")
            elif cmd.get("action") == "resume":
                state.is_running = True
                add_log("INFO", "策略已恢复运行")
            elif cmd.get("action") == "refresh":
                await websocket.send_json({"type": "state", "data": state.to_dict()})

    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.get("/api/state")
async def get_state():
    """获取当前状态的API"""
    return state.to_dict()


@app.post("/api/command")
async def handle_command(command: dict):
    """处理来自前端的命令"""
    action = command.get("action")

    if action == "pause":
        state.is_running = False
        state.command_queue.append({"action": "pause", "timestamp": time.time()})
        add_log("INFO", "策略已暂停")
        return {"status": "ok", "message": "策略已暂停"}
    elif action == "resume":
        state.is_running = True
        state.command_queue.append({"action": "resume", "timestamp": time.time()})
        add_log("INFO", "策略已恢复运行")
        return {"status": "ok", "message": "策略已恢复运行"}
    else:
        return {"status": "error", "message": "未知命令"}


# 用于引擎调用的函数
def update_positions(positions: dict):
    """更新持仓信息"""
    state.positions = positions
    # 广播状态而不使用create_task
    if manager.active_connections:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(_broadcast_state())
        except Exception:
            pass


def update_balance(balance: float):
    """更新余额"""
    state.balance = balance
    if manager.active_connections:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(_broadcast_state())
        except Exception:
            pass


def update_trade_stats(pnl: float, is_win: bool):
    """更新交易统计"""
    state.today_trades += 1
    state.today_pnl += pnl
    if is_win:
        state.win_count += 1
    else:
        state.loss_count += 1
    if manager.active_connections:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(_broadcast_state())
        except Exception:
            pass


def set_running(running: bool):
    """设置运行状态"""
    state.is_running = running
    if manager.active_connections:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(_broadcast_state())
        except Exception:
            pass


def update_cooldowns(symbols: set, global_remaining: int):
    """更新冷却状态"""
    state.cooldown_symbols = symbols
    state.global_cooldown_remaining = global_remaining
    if manager.active_connections:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(_broadcast_state())
        except Exception:
            pass


async def _broadcast_state():
    """内部广播函数"""
    await manager.broadcast({"type": "state", "data": state.to_dict()})
