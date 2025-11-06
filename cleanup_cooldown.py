"""
冷却状态清理和诊断工具
用于查看、验证和清理cooldown_state.json文件
"""

import json
from pathlib import Path
from datetime import datetime, timedelta

COOLDOWN_FILE = Path(__file__).parent / 'cooldown_state.json'


def diagnose_cooldown_state():
    """诊断冷却状态文件"""
    print("\n" + "="*80)
    print("【冷却状态诊断工具】")
    print("="*80)

    if not COOLDOWN_FILE.exists():
        print("✓ 冷却状态文件不存在（干净状态）")
        return

    try:
        with open(COOLDOWN_FILE, 'r') as f:
            data = json.load(f)

        print(f"✓ 冷却状态文件存在，包含 {len(data)} 个币种")
        print("\n【详细信息】")

        now = datetime.now()
        valid_count = 0
        expired_count = 0
        abnormal_count = 0

        for symbol, state in data.items():
            cooldown_until = datetime.fromisoformat(state['cooldown_until'])
            failure_count = state.get('failure_count', 0)
            last_failure = datetime.fromisoformat(state.get('last_failure', ''))

            status = "有效"
            if now >= cooldown_until:
                status = "已过期"
                expired_count += 1
            else:
                valid_count += 1

            if failure_count > 10:
                status += " [异常]"
                abnormal_count += 1

            remaining = max(0, int((cooldown_until - now).total_seconds()))
            print(
                f"  {symbol}: "
                f"失败×{failure_count}, "
                f"剩余{remaining}秒, "
                f"{status}"
            )

        print("\n【统计】")
        print(f"  有效冷却: {valid_count} 个")
        print(f"  已过期: {expired_count} 个")
        print(f"  异常记录: {abnormal_count} 个")

    except Exception as e:
        print(f"✗ 读取文件失败: {e}")


def cleanup_cooldown_state(force=False):
    """清理过期的冷却状态"""
    print("\n" + "="*80)
    print("【冷却状态清理】")
    print("="*80)

    if not COOLDOWN_FILE.exists():
        print("✓ 文件不存在，无需清理")
        return

    if not force:
        print("⚠️  确认要清理所有过期的冷却状态吗？")
        print("   输入 'yes' 确认，其他输入取消")
        confirm = input(">> ").strip().lower()
        if confirm != 'yes':
            print("已取消")
            return

    try:
        with open(COOLDOWN_FILE, 'r') as f:
            data = json.load(f)

        now = datetime.now()
        cleaned_data = {}
        removed_count = 0

        for symbol, state in data.items():
            cooldown_until = datetime.fromisoformat(state['cooldown_until'])

            # 保留有效的记录
            if now < cooldown_until:
                cleaned_data[symbol] = state
            else:
                removed_count += 1
                print(f"  删除过期: {symbol}")

        with open(COOLDOWN_FILE, 'w') as f:
            json.dump(cleaned_data, f, indent=2)

        print(f"\n✓ 清理完成！删除 {removed_count} 条过期记录，保留 {len(cleaned_data)} 条有效记录")

    except Exception as e:
        print(f"✗ 清理失败: {e}")


def reset_cooldown_state():
    """完全重置冷却状态（删除文件）"""
    print("\n" + "="*80)
    print("【冷却状态重置】")
    print("="*80)

    print("⚠️  确认要完全删除所有冷却状态吗？")
    print("   这会允许所有被冷却的币种立即重新交易")
    print("   输入 'yes' 确认，其他输入取消")
    confirm = input(">> ").strip().lower()

    if confirm != 'yes':
        print("已取消")
        return

    try:
        if COOLDOWN_FILE.exists():
            COOLDOWN_FILE.unlink()
            print("✓ 冷却状态文件已删除！程序重启后将创建干净的状态")
        else:
            print("✓ 文件不存在，已是干净状态")

    except Exception as e:
        print(f"✗ 删除失败: {e}")


if __name__ == "__main__":
    print("""
╔════════════════════════════════════════════════════════════════╗
║             冷却状态管理工具 v1.0                             ║
║          Cooldown State Management Tool                       ║
╚════════════════════════════════════════════════════════════════╝
""")

    while True:
        print("\n【选择操作】")
        print("  1. 诊断冷却状态")
        print("  2. 清理过期记录")
        print("  3. 完全重置（删除所有）")
        print("  0. 退出")

        choice = input("\n输入选项 (0-3): ").strip()

        if choice == '1':
            diagnose_cooldown_state()
        elif choice == '2':
            cleanup_cooldown_state()
        elif choice == '3':
            reset_cooldown_state()
        elif choice == '0':
            print("已退出")
            break
        else:
            print("❌ 无效选项")
