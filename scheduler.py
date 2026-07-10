from __future__ import annotations

import heapq
import random
from dataclasses import dataclass
from itertools import combinations, permutations


MODE_RANDOM = "random"
MODE_MIXED = "mixed"


class SchedulingError(ValueError):
    """输入条件不合法或当前约束下无法生成赛程。"""


@dataclass(frozen=True)
class Player:
    name: str
    gender: str


@dataclass(frozen=True)
class Match:
    team_a: tuple[int, int]
    team_b: tuple[int, int]

    @property
    def participants(self) -> tuple[int, int, int, int]:
        return self.team_a + self.team_b


@dataclass(frozen=True)
class PlayerStats:
    name: str
    gender: str
    appearances: int
    rests: int
    max_play_streak: int
    max_rest_streak: int


@dataclass(frozen=True)
class ScheduleResult:
    matches: list[Match]
    stats: list[PlayerStats]
    score: float
    appearance_gap: int
    max_partner_times: int
    cycle_length: int
    cycle_count: int


@dataclass
class _State:
    schedule: tuple[Match, ...]
    remaining: tuple[int, ...]
    play_streak: tuple[int, ...]
    rest_streak: tuple[int, ...]
    max_play_streak: tuple[int, ...]
    max_rest_streak: tuple[int, ...]
    partner_counts: dict[tuple[int, int], int]
    opponent_counts: dict[tuple[int, int], int]
    lineup_counts: dict[frozenset[int], int]
    last_lineup: frozenset[int] | None
    score: float
    tie_breaker: float


def fair_cycle_rounds(player_count: int, mode: str) -> int:
    """返回一个完整公平周期所包含的局数。"""
    if mode == MODE_RANDOM:
        # 5 人时每局休息 1 人，5 局后每人正好休息 1 次、上场 4 次。
        return {5: 5, 6: 6, 7: 7, 8: 8}[player_count]

    # 5 人混双要求 2 男 3 女或 3 男 2 女。
    # 3 局后，人数为 2 的性别组每人上场 3 次，人数为 3 的性别组每人上场 2 次，
    # 与 7 人混双一样，保证各性别组内部公平，但全体上场次数会相差 1 次。
    return {5: 3, 6: 6, 7: 6, 8: 8}[player_count]


def recommended_rounds(player_count: int, mode: str) -> int:
    """默认安排两个完整公平周期。"""
    return fair_cycle_rounds(player_count, mode) * 2


def round_options(player_count: int, mode: str) -> tuple[int, int, int]:
    """界面下拉菜单提供 1、2、3 个公平周期。"""
    cycle = fair_cycle_rounds(player_count, mode)
    return cycle, cycle * 2, cycle * 3


def generate_schedule(
    players: list[Player],
    mode: str,
    rounds: int,
    seed: int | None = None,
    exclude_male_vs_female: bool = False,
) -> ScheduleResult:
    """按完整公平周期生成赛程，并将多个周期依次拼接。"""
    _validate_basic_input(players, mode, rounds)

    cycle_length = fair_cycle_rounds(len(players), mode)
    if rounds % cycle_length != 0:
        options_text = "、".join(str(value) for value in round_options(len(players), mode))
        raise SchedulingError(
            f"当前模式每 {cycle_length} 局构成一个完整公平周期。"
            f"比赛局数必须是 {cycle_length} 的整数倍；建议选择 {options_text} 局。"
        )

    cycle_count = rounds // cycle_length
    rng = random.Random(seed)
    matches: list[Match] = []
    total_search_score = 0.0

    for _cycle_index in range(cycle_count):
        cycle_matches, cycle_score = _generate_one_cycle(
            players=players,
            mode=mode,
            rounds=cycle_length,
            rng=rng,
            exclude_male_vs_female=exclude_male_vs_female,
        )

        # 从循环移位和倒序方案中选择与上一周期衔接更自然的一种，
        # 避免周期交界处出现过长的连续上场或连续休息。
        if matches:
            cycle_matches = _choose_best_cycle_orientation(
                players,
                matches,
                cycle_matches,
            )

        matches.extend(cycle_matches)
        total_search_score += cycle_score

    stats = _build_stats(players, matches)
    appearance_values = [item.appearances for item in stats]
    partner_counts = _count_partners(matches)
    max_partner_times = max(partner_counts.values(), default=0)

    return ScheduleResult(
        matches=matches,
        stats=stats,
        score=total_search_score + _continuity_score(players, matches),
        appearance_gap=max(appearance_values) - min(appearance_values),
        max_partner_times=max_partner_times,
        cycle_length=cycle_length,
        cycle_count=cycle_count,
    )


def _generate_one_cycle(
    players: list[Player],
    mode: str,
    rounds: int,
    rng: random.Random,
    exclude_male_vs_female: bool,
) -> tuple[list[Match], float]:
    """生成单个完整公平周期。"""
    targets = _build_targets(players, mode, rounds, rng)
    candidates = _build_candidates(
        players,
        mode,
        exclude_male_vs_female=exclude_male_vs_female,
    )
    if not candidates:
        raise SchedulingError("当前性别构成和排除规则下没有可用对阵。")
    rng.shuffle(candidates)

    player_count = len(players)
    initial_state = _State(
        schedule=(),
        remaining=tuple(targets),
        play_streak=(0,) * player_count,
        rest_streak=(0,) * player_count,
        max_play_streak=(0,) * player_count,
        max_rest_streak=(0,) * player_count,
        partner_counts={},
        opponent_counts={},
        lineup_counts={},
        last_lineup=None,
        score=0.0,
        tie_breaker=rng.random(),
    )

    # 8 人乱斗候选组合最多，适当控制搜索宽度，保证普通电脑上也能较快完成。
    beam_width = 100 if mode == MODE_RANDOM and player_count == 8 else 140
    beam = [initial_state]

    for round_index in range(rounds):
        rounds_left = rounds - round_index - 1
        next_states: list[_State] = []

        for state in beam:
            for match in candidates:
                participants = match.participants

                if any(state.remaining[index] <= 0 for index in participants):
                    continue

                lineup = frozenset(participants)

                # 相邻两局不能由完全相同的四个人上场。
                if state.last_lineup is not None and lineup == state.last_lineup:
                    continue

                remaining = list(state.remaining)
                for index in participants:
                    remaining[index] -= 1

                if sum(remaining) != 4 * rounds_left:
                    continue

                if any(value < 0 or value > rounds_left for value in remaining):
                    continue

                playing = set(participants)
                play_streak: list[int] = []
                rest_streak: list[int] = []
                max_play_streak: list[int] = []
                max_rest_streak: list[int] = []
                extra_score = 0.0

                for index in range(player_count):
                    if index in playing:
                        current_play = state.play_streak[index] + 1
                        current_rest = 0
                        extra_score += 1.2 * max(0, current_play - 1) ** 2
                        if current_play > 2:
                            extra_score += 30 * (current_play - 2) ** 2
                    else:
                        current_play = 0
                        current_rest = state.rest_streak[index] + 1
                        extra_score += 1.2 * max(0, current_rest - 1) ** 2
                        if current_rest > 2:
                            extra_score += 30 * (current_rest - 2) ** 2

                    play_streak.append(current_play)
                    rest_streak.append(current_rest)
                    max_play_streak.append(
                        max(state.max_play_streak[index], current_play)
                    )
                    max_rest_streak.append(
                        max(state.max_rest_streak[index], current_rest)
                    )

                appearances_so_far = [
                    targets[index] - remaining[index]
                    for index in range(player_count)
                ]
                appearance_spread = max(appearances_so_far) - min(appearances_so_far)
                extra_score += 2.5 * appearance_spread**2

                partner_counts = state.partner_counts.copy()
                for team in (match.team_a, match.team_b):
                    key = _pair_key(*team)
                    old_count = partner_counts.get(key, 0)
                    extra_score += 18 * old_count
                    partner_counts[key] = old_count + 1

                opponent_counts = state.opponent_counts.copy()
                for player_a in match.team_a:
                    for player_b in match.team_b:
                        key = _pair_key(player_a, player_b)
                        old_count = opponent_counts.get(key, 0)
                        extra_score += 3 * old_count
                        opponent_counts[key] = old_count + 1

                lineup_counts = state.lineup_counts.copy()
                old_lineup_count = lineup_counts.get(lineup, 0)
                extra_score += 8 * old_lineup_count
                lineup_counts[lineup] = old_lineup_count + 1

                next_states.append(
                    _State(
                        schedule=state.schedule + (match,),
                        remaining=tuple(remaining),
                        play_streak=tuple(play_streak),
                        rest_streak=tuple(rest_streak),
                        max_play_streak=tuple(max_play_streak),
                        max_rest_streak=tuple(max_rest_streak),
                        partner_counts=partner_counts,
                        opponent_counts=opponent_counts,
                        lineup_counts=lineup_counts,
                        last_lineup=lineup,
                        score=state.score + extra_score,
                        tie_breaker=rng.random(),
                    )
                )

        if not next_states:
            raise SchedulingError(
                "当前人数、性别和公平周期下未找到可行方案，请点击“重新随机”再试一次。"
            )

        beam = heapq.nsmallest(
            beam_width,
            next_states,
            key=lambda state: (state.score, state.tie_breaker),
        )

    final_states = [state for state in beam if all(value == 0 for value in state.remaining)]
    if not final_states:
        raise SchedulingError("未能完成公平周期，请点击“重新随机”再试一次。")

    def final_score(state: _State) -> float:
        play_gap = max(state.max_play_streak) - min(state.max_play_streak)
        rest_gap = max(state.max_rest_streak) - min(state.max_rest_streak)
        return state.score + 5 * play_gap + 5 * rest_gap

    final_states.sort(key=final_score)
    best_score = final_score(final_states[0])
    good_states = [
        state
        for state in final_states[:30]
        if final_score(state) <= best_score + 5
    ]
    selected = rng.choice(good_states)
    return list(selected.schedule), final_score(selected)


def _choose_best_cycle_orientation(
    players: list[Player],
    previous_matches: list[Match],
    cycle_matches: list[Match],
) -> list[Match]:
    """通过循环移位或倒序，使两个公平周期的交界更平滑。"""
    variants: list[list[Match]] = []
    seen: set[tuple[Match, ...]] = set()

    if len(players) == 5:
        # 5 人模式每局只有 1 人休息。一个周期内每位可休息球员恰好轮休一次，
        # 因此周期内比赛可以自由重排。枚举全部顺序（最多 5! = 120 种），
        # 可以更好地压低两个周期交界处的连续上场局数。
        for variant_tuple in permutations(cycle_matches):
            if variant_tuple not in seen:
                seen.add(variant_tuple)
                variants.append(list(variant_tuple))
    else:
        for base in (cycle_matches, list(reversed(cycle_matches))):
            for shift in range(len(base)):
                variant = base[shift:] + base[:shift]
                signature = tuple(variant)
                if signature not in seen:
                    seen.add(signature)
                    variants.append(variant)

    def variant_score(variant: list[Match]) -> tuple[int, int, float]:
        combined = previous_matches + variant
        score = _continuity_score(players, combined)

        # 周期交界处若四名上场者完全相同，给予很高惩罚。
        if frozenset(previous_matches[-1].participants) == frozenset(variant[0].participants):
            score += 10_000

        # 尽量避免新周期与上一个周期完全按同一顺序重复。
        previous_cycle = previous_matches[-len(cycle_matches):]
        if tuple(previous_cycle) == tuple(variant):
            score += 1_000

        stats = _build_stats(players, combined)
        max_play_streak = max(item.max_play_streak for item in stats)
        max_rest_streak = max(item.max_rest_streak for item in stats)

        # 5 人每局仅 1 人休息，周期衔接对连续上场影响特别明显。
        # 先最小化最长连续上场/休息，再比较综合分，避免为了少量搭档变化
        # 而让某位球员连续上场 5～6 局。
        if len(players) == 5:
            return max_play_streak, max_rest_streak, score

        return 0, 0, score

    return min(variants, key=variant_score)


def _continuity_score(players: list[Player], matches: list[Match]) -> float:
    """评价完整赛程的连续上场、休息以及重复搭档情况。"""
    stats = _build_stats(players, matches)
    score = 0.0

    for item in stats:
        score += 20 * item.max_play_streak**2
        score += 20 * item.max_rest_streak**2
        if item.max_play_streak > 2:
            score += 200 * (item.max_play_streak - 2) ** 2
        if item.max_rest_streak > 2:
            score += 200 * (item.max_rest_streak - 2) ** 2

    for previous, current in zip(matches, matches[1:]):
        if frozenset(previous.participants) == frozenset(current.participants):
            score += 10_000

    for count in _count_partners(matches).values():
        score += 4 * max(0, count - 1) ** 2

    return score


def _count_partners(matches: list[Match]) -> dict[tuple[int, int], int]:
    counts: dict[tuple[int, int], int] = {}
    for match in matches:
        for team in (match.team_a, match.team_b):
            key = _pair_key(*team)
            counts[key] = counts.get(key, 0) + 1
    return counts


def _validate_basic_input(players: list[Player], mode: str, rounds: int) -> None:
    player_count = len(players)
    if player_count not in (5, 6, 7, 8):
        raise SchedulingError("参与人数只能是 5、6、7 或 8 人。")

    if mode not in (MODE_RANDOM, MODE_MIXED):
        raise SchedulingError("未知比赛模式。")

    if not isinstance(rounds, int) or rounds <= 0 or rounds > 60:
        raise SchedulingError("比赛局数必须是 1～60 之间的整数。")

    names = [player.name.strip() for player in players]
    if any(not name for name in names):
        raise SchedulingError("每位球员都必须填写姓名。")

    if len(set(names)) != len(names):
        raise SchedulingError("球员姓名不能重复。")

    if any(player.gender not in ("男", "女") for player in players):
        raise SchedulingError("性别只能选择“男”或“女”。")


def _build_targets(
    players: list[Player],
    mode: str,
    rounds: int,
    rng: random.Random,
) -> list[int]:
    player_count = len(players)

    if mode == MODE_RANDOM:
        total_slots = 4 * rounds
        if total_slots % player_count != 0:
            suggestion = fair_cycle_rounds(player_count, mode)
            raise SchedulingError(
                f"{player_count} 人乱斗安排 {rounds} 局时，无法让每个人上场总次数完全相同。"
                f"建议使用 {suggestion} 局的整数倍。"
            )
        return [total_slots // player_count] * player_count

    men = [index for index, player in enumerate(players) if player.gender == "男"]
    women = [index for index, player in enumerate(players) if player.gender == "女"]

    expected_gender_counts = {
        5: {(2, 3), (3, 2)},
        6: {(3, 3)},
        7: {(3, 4), (4, 3)},
        8: {(4, 4)},
    }
    if (len(men), len(women)) not in expected_gender_counts[player_count]:
        if player_count == 5:
            requirement = "2 男 3 女或 3 男 2 女"
        elif player_count == 6:
            requirement = "3 男 3 女"
        elif player_count == 7:
            requirement = "3 男 4 女或 4 男 3 女"
        else:
            requirement = "4 男 4 女"
        raise SchedulingError(f"{player_count} 人混双模式要求 {requirement}。")

    targets = [0] * player_count

    def distribute(indices: list[int]) -> None:
        base_count, extra_count = divmod(2 * rounds, len(indices))
        shuffled = indices.copy()
        rng.shuffle(shuffled)
        for index in shuffled:
            targets[index] = base_count
        for index in shuffled[:extra_count]:
            targets[index] += 1

    distribute(men)
    distribute(women)

    target_gap = max(targets) - min(targets)

    if player_count in (6, 8) and target_gap != 0:
        suggestion = fair_cycle_rounds(player_count, mode)
        raise SchedulingError(
            f"{player_count} 人混双安排 {rounds} 局时，无法让每个人上场总次数完全相同。"
            f"建议使用 {suggestion} 局的整数倍。"
        )

    if player_count in (5, 7) and target_gap > 1:
        suggestion = fair_cycle_rounds(player_count, mode)
        raise SchedulingError(
            f"{player_count} 人混双安排 {rounds} 局时，上场次数差会超过 1。"
            f"建议使用 {suggestion} 局的整数倍。"
        )

    return targets


def _build_candidates(
    players: list[Player],
    mode: str,
    exclude_male_vs_female: bool = False,
) -> list[Match]:
    candidates: list[Match] = []

    if mode == MODE_RANDOM:
        for group in combinations(range(len(players)), 4):
            player_a, player_b, player_c, player_d = group
            group_matches = [
                Match((player_a, player_b), (player_c, player_d)),
                Match((player_a, player_c), (player_b, player_d)),
                Match((player_a, player_d), (player_b, player_c)),
            ]

            for match in group_matches:
                if (
                    exclude_male_vs_female
                    and _is_male_doubles_vs_female_doubles(players, match)
                ):
                    continue
                candidates.append(match)

        return candidates

    men = [index for index, player in enumerate(players) if player.gender == "男"]
    women = [index for index, player in enumerate(players) if player.gender == "女"]

    for man_a, man_b in combinations(men, 2):
        for woman_a, woman_b in combinations(women, 2):
            candidates.extend(
                [
                    Match((man_a, woman_a), (man_b, woman_b)),
                    Match((man_a, woman_b), (man_b, woman_a)),
                ]
            )

    return candidates


def _is_male_doubles_vs_female_doubles(
    players: list[Player],
    match: Match,
) -> bool:
    """判断一局是否为两名男性组成一队、两名女性组成另一队。"""
    team_a_genders = {players[index].gender for index in match.team_a}
    team_b_genders = {players[index].gender for index in match.team_b}

    return (
        team_a_genders == {"男"} and team_b_genders == {"女"}
    ) or (
        team_a_genders == {"女"} and team_b_genders == {"男"}
    )


def _build_stats(players: list[Player], matches: list[Match]) -> list[PlayerStats]:
    stats: list[PlayerStats] = []

    for player_index, player in enumerate(players):
        sequence = [player_index in match.participants for match in matches]
        appearances = sum(sequence)
        rests = len(matches) - appearances

        stats.append(
            PlayerStats(
                name=player.name,
                gender=player.gender,
                appearances=appearances,
                rests=rests,
                max_play_streak=_max_streak(sequence, True),
                max_rest_streak=_max_streak(sequence, False),
            )
        )

    return stats


def _max_streak(sequence: list[bool], target: bool) -> int:
    best = 0
    current = 0
    for value in sequence:
        if value is target:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def _pair_key(player_a: int, player_b: int) -> tuple[int, int]:
    return (player_a, player_b) if player_a < player_b else (player_b, player_a)
