#!/usr/bin/env python3
"""P4 修订规则单元测试（定义测试，非策略收益回测）。

测试对象是修订报告中的正式定义本身（K1 空仓日处理、D4b 基差预算、
强平价、实际划入保证金、强平后模拟平仓、结算时点资金费名义），
全部用合成算例，不用历史策略收益、不产生任何回测结论。
运行：python3 p4-revision-unit-tests.py
"""
import unittest

# ---------- 被测定义（与修订报告逐字对应） ----------

def k1_verdict(total_pnl_usdt, committed_capital, calendar_days=90, holding_days=0):
    """K1：滚动 90 个日历日窗口，月末评估。
    年化率 = (窗口净 P&L / 承诺对子资本) × (365 / 日历天数)。
    空仓日贡献 0（不从时间轴删除）；持有日 = 0 → 未决（不杀）。
    返回 (年化率或 None, verdict)：verdict ∈ {'kill', 'pass', 'undecided'}。
    """
    if holding_days == 0:
        return None, "undecided"
    rate = (total_pnl_usdt / committed_capital) * (365.0 / calendar_days)
    return rate, ("kill" if rate <= 0 else "pass")

def d4b_budget_usdt(mean_rate_per_settlement, settlements_per_day, leg_notional):
    """D4b 基差预算（USDT）= 30 × 日均资金费收入（USDT/天）。
    日均资金费收入 = 365d 均值费率 × 365d 实际日均结算次数 × 腿名义。
    """
    return 30.0 * mean_rate_per_settlement * settlements_per_day * leg_notional

def d4b_basis_move_usdt(basis_entry, basis_now, qty_coins):
    """累计基差变动（USDT）= (现基差 − 入场基差) × 腿数量（币）。
    基差 = 永续价 − 现货价（USDT/币）。触发条件：变动 > 预算。
    """
    return (basis_now - basis_entry) * qty_coins

def liq_price_short(entry_price, leverage, maintenance_rate):
    """逐仓空腿强平价：P_liq = P0 × (1 + 1/L) / (1 + m)。"""
    return entry_price * (1.0 + 1.0 / leverage) / (1.0 + maintenance_rate)

def liq_distance_with_effective_margin(entry_price, qty_coins, effective_margin_usdt,
                                       maintenance_rate):
    """按实际划入仓位的保证金余额计算的强平距离（相对涨幅）。
    解 M_eff + (P0 − P)·Q = m·P·Q。钱包中未划转部分不得计入 M_eff。
    """
    # P = (M_eff + P0·Q) / (Q·(1 + m))；距离 = P/P0 − 1
    p_liq = (effective_margin_usdt + entry_price * qty_coins) / (qty_coins * (1.0 + maintenance_rate))
    return p_liq / entry_price - 1.0

def funding_income_usdt(settlements, qty_coins):
    """资金费收入（USDT）= Σ 每次结算费率 × 结算时点名义（Q × mark 价）。
    settlements: [(rate, mark_price), ...]。不得用初始名义代替结算时点名义。
    """
    return sum(rate * qty_coins * mark for rate, mark in settlements)

def simulate_post_liq_close(qty_coins, spot_price_at_liq, next_executable_spot_price,
                            taker_fee=0.001, slippage=0.0005):
    """强平后模拟平仓：现货腿按下一可执行价格市价卖出。
    返回 (平仓所得 USDT, 裸露 P&L USDT)：裸露 P&L = 所得 − 失效时刻现货价值。
    失效时刻现货价值 = Q × 失效时现货价；所得扣 taker 费与滑点档。
    """
    value_at_liq = qty_coins * spot_price_at_liq
    proceeds = qty_coins * next_executable_spot_price * (1.0 - taker_fee - slippage)
    return proceeds, proceeds - value_at_liq

# ---------- 测试 ----------

class TestK1(unittest.TestCase):
    def test_calendar_not_deleted(self):
        # 持有 60 天净 +$0.12，空仓 30 天，承诺资本 $40。
        rate, v = k1_verdict(0.12, 40.0, 90, 60)
        self.assertAlmostEqual(rate, 0.12 / 40.0 * 365.0 / 90.0, places=6)  # +1.2167%
        self.assertEqual(v, "pass")
        # 删除空仓日的错误算法（分母改持有日）会虚高 50%，必须与正确值不同。
        deleted = 0.12 / 40.0 * 365.0 / 60.0  # +1.825%
        self.assertAlmostEqual(deleted, 0.01825, places=5)
        self.assertGreater(deleted, rate)
        self.assertAlmostEqual(deleted / rate, 1.5, places=6)

    def test_loss_with_flat_days_still_kills(self):
        # 持有 60 天净 −$0.05，空仓 30 天：空仓救不了亏损，仍杀。
        rate, v = k1_verdict(-0.05, 40.0, 90, 60)
        self.assertLess(rate, 0)
        self.assertEqual(v, "kill")

    def test_all_flat_is_undecided_not_kill(self):
        # 整窗空仓（持有日 0）：无策略表现可判 → 未决，不是杀。
        rate, v = k1_verdict(0.0, 40.0, 90, 0)
        self.assertIsNone(rate)
        self.assertEqual(v, "undecided")

    def test_zero_pnl_with_holding_is_kill(self):
        # 有持有日但总 P&L 恰为 0：年化 0% ≤ 0 → 杀（边界）。
        rate, v = k1_verdict(0.0, 40.0, 90, 45)
        self.assertEqual(rate, 0.0)
        self.assertEqual(v, "kill")

    def test_flat_days_do_not_flip_sign(self):
        # 空仓日对分子加 0，不改变总 P&L 符号：正仍正、负仍负。
        _, v_pos = k1_verdict(0.10, 40.0, 90, 30)
        _, v_neg = k1_verdict(-0.10, 40.0, 90, 30)
        self.assertEqual(v_pos, "pass")
        self.assertEqual(v_neg, "kill")

class TestD4b(unittest.TestCase):
    def test_budget_usdt(self):
        # ETH：365d 均值 0.00231%/次 × 3.0 次/天 × 20U × 30 天 = $0.0416。
        b = d4b_budget_usdt(0.0000231, 3.0, 20.0)
        self.assertAlmostEqual(b, 0.04158, places=4)

    def test_trigger_cases(self):
        # 入场 S0=$2250, P0=$2251（基差 +$1），Q = 20/2250 币，预算 $0.0416。
        q = 20.0 / 2250.0
        budget = 0.04158
        move_a = d4b_basis_move_usdt(1.0, 5.0, q)   # 基差 +$5：变动 $0.0356 < 预算
        move_b = d4b_basis_move_usdt(1.0, 6.0, q)   # 基差 +$6：变动 $0.0444 > 预算
        self.assertAlmostEqual(move_a, 0.03556, places=4)
        self.assertAlmostEqual(move_b, 0.04444, places=4)
        self.assertLess(move_a, budget)
        self.assertGreater(move_b, budget)

    def test_bps_display_consistent_with_usdt(self):
        # bps 展示分母固定为入场名义：USDT 比较与 bps 比较结论一致。
        q = 20.0 / 2250.0
        budget_usdt = 0.04158
        budget_bps = budget_usdt / 20.0 * 10000  # 20.79 bps ≈ 登记 20.8 bps
        move_bps = d4b_basis_move_usdt(1.0, 6.0, q) / 20.0 * 10000  # 22.22 bps
        self.assertAlmostEqual(budget_bps, 20.79, places=1)
        self.assertAlmostEqual(move_bps, 22.22, places=1)
        self.assertGreater(move_bps, budget_bps)

class TestMargin(unittest.TestCase):
    def test_liq_price_1x(self):
        # 1x，m=0.3%：距离 +99.4%（登记上界 +100% 的修正值）。
        d = liq_price_short(2250.0, 1.0, 0.003) / 2250.0 - 1.0
        self.assertAlmostEqual(d, 0.99401, places=4)

    def test_liq_price_833x(self):
        # 8.33x（BTC 56U 勉强装下），m=0.3%：距离约 +11.66%。
        d = liq_price_short(80000.0, 8.33, 0.003) / 80000.0 - 1.0
        self.assertAlmostEqual(d, 0.1166, places=3)

    def test_staged_buffer_does_not_count(self):
        # 钱包里 16U 未划转：强平距离仍按初始保证金 20U 算（+99.4%），不是 36U。
        q = 20.0 / 2250.0
        d_staged = liq_distance_with_effective_margin(2250.0, q, 20.0, 0.003)
        self.assertAlmostEqual(d_staged, 0.99401, places=4)

    def test_transferred_buffer_counts(self):
        # 实际划入 16U 后保证金 36U：距离约 +179.16%。
        q = 20.0 / 2250.0
        d = liq_distance_with_effective_margin(2250.0, q, 36.0, 0.003)
        self.assertAlmostEqual(d, 1.7916, places=3)

class TestPostLiq(unittest.TestCase):
    def test_simulated_close_records_naked_pnl(self):
        # 失效时现货价 $4500（ETH 翻倍），下一可执行价 $4455（−1%）：
        # 现货价值 $40.00，所得约 $39.54，裸露 P&L 约 −$0.46（未被强平抹掉）。
        q = 20.0 / 2250.0
        proceeds, naked = simulate_post_liq_close(q, 4500.0, 4455.0)
        self.assertAlmostEqual(q * 4500.0, 40.0, places=2)
        self.assertAlmostEqual(proceeds, 39.54, places=1)
        self.assertLess(naked, 0)
        self.assertAlmostEqual(naked, -0.46, places=1)

class TestFunding(unittest.TestCase):
    def test_settlement_notional_not_initial(self):
        # 价格上涨时，结算时点名义法收入 > 初始名义法；价格平坦时两者相等。
        q = 20.0 / 2250.0
        rising = funding_income_usdt([(0.00003, 2250.0), (0.00003, 2300.0), (0.00003, 2350.0)], q)
        flat = funding_income_usdt([(0.00003, 2250.0)] * 3, q)
        initial = 0.00003 * 20.0 * 3
        self.assertAlmostEqual(rising, 0.00184, places=4)
        self.assertAlmostEqual(flat, initial, places=6)
        self.assertGreater(rising, initial)

if __name__ == "__main__":
    unittest.main(verbosity=2)
