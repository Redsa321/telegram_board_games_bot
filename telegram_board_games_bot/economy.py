from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, date, datetime
from math import floor
from typing import Any

MULTIPLIERS = tuple(range(2, 21))
MULTIPLIER_WEIGHTS = tuple(1 / (multiplier * multiplier) for multiplier in MULTIPLIERS)
ROBOT_PRIZE_BASES = {
    "easy": 5,
    "normal": 10,
    "hard": 20,
}
PVP_ENTRY_FEE_REASON = "pvp_entry_fee"
STARTER_KYZMA_COINS = 100
STARTER_GAME_COUNT = 10
DAILY_CLAIM_KYZMA_COINS = 10
DAILY_CLAIM_REASON = "daily_claim"
CHESS_PVP_COST_MULTIPLIER = 1.5
CHESS_PRIZE_MULTIPLIER_FACTOR = 2


@dataclass(frozen=True)
class DailyClaimResult:
    claimed: bool
    amount: int
    balance: int
    claim_date: date


def kyzma_value_from_rating(rating: int) -> int:
    # Elo-like exponential value: 1000 rating => 50 value,
    # +400 rating roughly doubles it, -400 roughly halves it.
    return max(10, round(50 * (2 ** ((rating - 1000) / 400))))


def kyzma_game_cost_from_values(left_value: int, right_value: int) -> int:
    return max(1, round(((left_value + right_value) / 2) / 5))


def roll_prize_multiplier(rng: Any | None = None) -> int:
    rng = rng or random
    return rng.choices(MULTIPLIERS, weights=MULTIPLIER_WEIGHTS, k=1)[0]


def multiplied_cost(base: int, multiplier: float) -> int:
    return max(1, floor(base * multiplier + 0.5))


def set_kyzma_prize(state, base: int, rng: Any | None = None, prize_multiplier_factor: int = 1) -> None:
    multiplier = roll_prize_multiplier(rng) * prize_multiplier_factor
    state.kyzma_prize_base = base
    state.kyzma_prize_multiplier = multiplier
    state.kyzma_prize = base * multiplier


async def configure_pvp_prize(
    database,
    chat_id: int,
    black_user_id: int,
    white_user_id: int,
    game_kind: str,
    state,
    cost_multiplier: float = 1.0,
    prize_multiplier_factor: int = 1,
) -> None:
    base = await database.get_kyzma_game_cost(chat_id, black_user_id, white_user_id, game_kind)
    set_kyzma_prize(state, multiplied_cost(base, cost_multiplier), prize_multiplier_factor=prize_multiplier_factor)


async def pvp_players_without_entry_fee(database, chat_id: int, black_user_id: int, white_user_id: int, game_kind: str, state) -> tuple[int, ...]:
    cost = state.kyzma_prize_base
    if cost is None or cost <= 0:
        return ()
    return await database.get_insufficient_kyzma_user_ids(chat_id, (black_user_id, white_user_id), game_kind, cost)


async def charge_pvp_entry_fee_once(database, db_game, state, game_kind: str):
    cost = state.kyzma_prize_base
    if cost is None or cost <= 0:
        return await database.charge_kyzma_coins_once(db_game.id, db_game.chat_id, (), game_kind, 0, PVP_ENTRY_FEE_REASON)
    return await database.charge_kyzma_coins_once(
        db_game.id,
        db_game.chat_id,
        (db_game.black_user_id, db_game.white_user_id),
        game_kind,
        cost,
        PVP_ENTRY_FEE_REASON,
    )


async def claim_daily_kyzma_bonus(database, chat_id: int, user_id: int, game_kind: str, claim_date: date | None = None) -> DailyClaimResult:
    claim_date = claim_date or datetime.now(UTC).date()
    game_id = f"daily:{user_id}:{claim_date.isoformat()}"
    claimed = await database.award_kyzma_coins_once(
        game_id=game_id,
        chat_id=chat_id,
        user_id=user_id,
        game_kind=game_kind,
        amount=DAILY_CLAIM_KYZMA_COINS,
        multiplier=None,
        reason=DAILY_CLAIM_REASON,
    )
    wallet = await database.ensure_global_wallet(user_id)
    return DailyClaimResult(claimed, DAILY_CLAIM_KYZMA_COINS, wallet.kyzma_coin_balance, claim_date)


def configure_robot_prize(state, difficulty: str, prize_multiplier_factor: int = 1) -> None:
    set_kyzma_prize(
        state,
        ROBOT_PRIZE_BASES.get(difficulty, ROBOT_PRIZE_BASES["normal"]),
        prize_multiplier_factor=prize_multiplier_factor,
    )


async def award_finished_game_currency(database, db_game, state, game_kind: str) -> bool:
    if not db_game.rated and state.robot_user_id is None:
        return False
    winner_user_id = state.winner_user_id()
    if winner_user_id is None:
        return False
    if state.robot_user_id is not None and winner_user_id == state.robot_user_id:
        return False
    amount = state.kyzma_prize
    multiplier = state.kyzma_prize_multiplier
    if amount is None or amount <= 0:
        if state.robot_user_id is not None:
            base = ROBOT_PRIZE_BASES.get(state.robot_difficulty or "normal", ROBOT_PRIZE_BASES["normal"])
        else:
            base = await database.get_kyzma_game_cost(db_game.chat_id, db_game.black_user_id, db_game.white_user_id, game_kind)
        multiplier = roll_prize_multiplier()
        amount = base * multiplier
    if amount is None or amount <= 0:
        return False
    reason = f"robot:{state.robot_difficulty}" if state.robot_user_id is not None else "pvp"
    return await database.award_kyzma_coins_once(
        game_id=db_game.id,
        chat_id=db_game.chat_id,
        user_id=winner_user_id,
        game_kind=game_kind,
        amount=amount,
        multiplier=multiplier,
        reason=reason,
    )
