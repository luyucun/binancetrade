#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
信号诊断脚本 - 找出为什么没有生成交易信号
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import logging
from binance_client_v2 import BinanceClientV2
from coin_selector import CoinSelector
from indicators import IndicatorCalculator
from trend_analyzer import TrendAnalyzer
from signal_generator import SignalGenerator
from config_v2 import API_CONFIG, SELECTION_CONFIG, SCORING_SYSTEM

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def diagnose():
    """诊断为什么没有信号"""

    print("=" * 80)
    print("🔍 信号诊断工具")
    print("=" * 80)

    # 1. 初始化客户端
    print("\n[1/5] 初始化Binance客户端...")
    client = BinanceClientV2(
        api_key=API_CONFIG['binance_key'],
        api_secret=API_CONFIG['binance_secret'],
        testnet=False
    )

    coin_selector = CoinSelector()
    trend_analyzer = TrendAnalyzer()
    signal_generator = SignalGenerator()
    indicator_calc = IndicatorCalculator()

    # 2. 获取币种
    print("\n[2/5] 获取候选币种...")
    coins_data = client.get_top_coins_by_volume(SELECTION_CONFIG['top_n_by_volume'])
    print(f"✓ 获取到 {len(coins_data)} 个币种")

    from coin_selector import CoinInfo
    all_coins = []
    for coin_data in coins_data:
        all_coins.append(CoinInfo(
            symbol=coin_data['symbol'],
            current_price=coin_data['price'],
            change_24h=coin_data['change_24h'],
            volume_24h=coin_data['volume_24h'],
            current_volume=coin_data['volume'],
            is_usdt_pair=True
        ))

    # 筛选币种
    selected_coins = coin_selector.select_coins(all_coins)
    print(f"✓ 筛选后剩余 {len(selected_coins)} 个币种")

    # 3. 逐个分析币种
    print(f"\n[3/5] 分析前10个币种的信号条件...")
    print("-" * 80)

    stats = {
        'total': 0,
        'insufficient_klines': 0,
        'low_confidence': 0,
        'low_score': 0,
        'passed': 0
    }

    min_score = SCORING_SYSTEM['thresholds']['minimum_score']

    for i, coin in enumerate(selected_coins[:10]):  # 只分析前10个
        print(f"\n📊 [{i+1}/10] {coin.symbol}")
        print(f"   价格: {coin.current_price:.4f}, 24h涨跌: {coin.change_24h:+.2f}%")

        stats['total'] += 1

        try:
            # 获取K线数据 - 所有时间框架都请求50根
            klines_3m = client.get_klines(coin.symbol, '3m', 50)
            klines_5m = client.get_klines(coin.symbol, '5m', 50)
            klines_15m = client.get_klines(coin.symbol, '15m', 50)

            if not all([klines_3m, klines_5m, klines_15m]):
                print(f"   ❌ K线数据不足: 3m={len(klines_3m or [])}, 5m={len(klines_5m or [])}, 15m={len(klines_15m or [])}")
                stats['insufficient_klines'] += 1
                continue

            if len(klines_3m) < 20 or len(klines_5m) < 20 or len(klines_15m) < 20:
                print(f"   ❌ K线数量不够: 3m={len(klines_3m)}/20, 5m={len(klines_5m)}/20, 15m={len(klines_15m)}/20")
                stats['insufficient_klines'] += 1
                continue

            # 计算指标
            def calc_indicators(klines):
                closes = [float(k['close']) for k in klines]
                highs = [float(k['high']) for k in klines]
                lows = [float(k['low']) for k in klines]
                volumes = [float(k['volume']) for k in klines]
                return indicator_calc.calculate_all_indicators(closes, highs, lows, volumes)

            indicators_3m = calc_indicators(klines_3m)
            indicators_5m = calc_indicators(klines_5m)
            indicators_15m = calc_indicators(klines_15m)

            if not all([indicators_3m, indicators_5m, indicators_15m]):
                print(f"   ❌ 指标计算失败: 3m={indicators_3m is not None}, 5m={indicators_5m is not None}, 15m={indicators_15m is not None}")
                stats['insufficient_klines'] += 1
                continue

            # 趋势分析
            trend_analysis = trend_analyzer.analyze_trend(
                indicators_3m, indicators_5m, indicators_15m, coin.current_price
            )

            print(f"   趋势: {trend_analysis.direction.value}, 信心度: {trend_analysis.confidence:.0%}")
            print(f"   评分: 3m={trend_analysis.primary_tf_score}/3, 5m={trend_analysis.confirmation_tf_score}/3, 15m={trend_analysis.trend_tf_score}/1")

            if trend_analysis.confidence < 0.5:
                print(f"   ❌ 信心度不足 ({trend_analysis.confidence:.0%} < 50%)")
                print(f"   原因:")
                for reason in trend_analysis.reasons[:3]:  # 只显示前3个
                    print(f"      {reason}")
                stats['low_confidence'] += 1
                continue

            # 生成信号
            signal = signal_generator.generate_signal(
                symbol=coin.symbol,
                klines_3m=klines_3m,
                klines_5m=klines_5m,
                klines_15m=klines_15m,
                current_price=coin.current_price,
                position_size_usdt=100.0
            )

            if not signal:
                print(f"   ❌ 评分不足 (< {min_score}分)")
                # 手动计算评分看看差多少
                from signal_generator import SignalScorer
                scorer = SignalScorer()
                atr = indicators_3m.atr
                stop_loss_price = coin.current_price - (atr * 1.2) if trend_analysis.direction.value == "BULLISH" else coin.current_price + (atr * 1.2)

                score = scorer.generate_score(
                    trend_analysis, indicators_3m, indicators_5m,
                    atr, coin.current_price, coin.current_price, stop_loss_price
                )

                print(f"   实际评分: {score.total_score}/12 (趋势{score.trend_score}+动量{score.momentum_score}+风险{score.risk_reward_score})")
                print(f"   需要: {min_score}分, 差距: {min_score - score.total_score}分")
                stats['low_score'] += 1
                continue

            print(f"   ✅ 通过! 评分: {signal.score.total_score}/12, 信心: {signal.confidence:.0%}")
            stats['passed'] += 1

        except Exception as e:
            print(f"   ⚠️  错误: {e}")
            continue

    # 4. 统计摘要
    print("\n" + "=" * 80)
    print("📈 诊断统计")
    print("=" * 80)
    print(f"总分析: {stats['total']} 个币种")
    print(f"K线数据不足: {stats['insufficient_klines']} 个 ({stats['insufficient_klines']/max(stats['total'],1)*100:.1f}%)")
    print(f"趋势信心度低: {stats['low_confidence']} 个 ({stats['low_confidence']/max(stats['total'],1)*100:.1f}%)")
    print(f"评分不足: {stats['low_score']} 个 ({stats['low_score']/max(stats['total'],1)*100:.1f}%)")
    print(f"✅ 通过筛选: {stats['passed']} 个 ({stats['passed']/max(stats['total'],1)*100:.1f}%)")

    # 5. 建议
    print("\n" + "=" * 80)
    print("💡 优化建议")
    print("=" * 80)

    if stats['insufficient_klines'] > 5:
        print("⚠️  很多币种K线数据不足，这是正常的（新上线的币）")

    if stats['low_confidence'] > 5:
        print("⚠️  多数币种趋势信心度低 (<50%)")
        print("   建议: 降低信心度要求或减少趋势条件数量")
        print(f"   当前: 需要满足7个条件中的至少4个 (57%)")
        print(f"   修改: trend_analyzer.py 中的逻辑，或接受更低的信心度")

    if stats['low_score'] > 5:
        print(f"⚠️  多数币种评分不足 (当前最低要求: {min_score}分)")
        print(f"   建议1: 降低最低评分要求")
        print(f"   修改: config_v2.py 第179行 'minimum_score': {min_score} → 改为 3 或 4")
        print(f"   ")
        print(f"   建议2: 调整评分权重，让更多信号能达到门槛")
        print(f"   修改: config_v2.py 第159-183行的评分配置")

    if stats['passed'] == 0:
        print("\n🚨 关键问题: 没有任何币种通过筛选!")
        print("   建议立即调整参数:")
        print(f"   1. 降低最低评分: {min_score} → 3")
        print(f"   2. 降低趋势要求: 接受信心度 ≥ 40% (而非50%)")
        print(f"   3. 增加监控币种数量: {SELECTION_CONFIG['top_n_by_volume']} → 100")

    print("\n" + "=" * 80)


if __name__ == "__main__":
    diagnose()
