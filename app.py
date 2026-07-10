from __future__ import annotations

import html
import secrets
from dataclasses import dataclass

import streamlit as st

from scheduler import (
    MODE_MIXED,
    MODE_RANDOM,
    Player,
    ScheduleResult,
    SchedulingError,
    fair_cycle_rounds,
    generate_schedule,
    recommended_rounds,
    round_options,
)


APP_TITLE = "羽毛球双打分组工具"
MODE_LABELS = {
    MODE_RANDOM: "随机大乱斗",
    MODE_MIXED: "混双轮转",
}
GENDERS = ("男", "女")
MAX_PLAYERS = 8


@dataclass(frozen=True)
class CurrentInputs:
    players: list[Player]
    player_count: int
    mode: str
    rounds: int
    exclude_male_vs_female: bool

    @property
    def signature(self) -> tuple[object, ...]:
        return (
            self.player_count,
            self.mode,
            self.rounds,
            self.exclude_male_vs_female,
            tuple((player.name, player.gender) for player in self.players),
        )


def initialize_state() -> None:
    st.session_state.setdefault("player_count", 6)
    st.session_state.setdefault("mode", MODE_RANDOM)
    st.session_state.setdefault("rounds_selected", 12)
    st.session_state.setdefault("exclude_male_vs_female", False)
    st.session_state.setdefault("schedule_result", None)
    st.session_state.setdefault("schedule_signature", None)
    st.session_state.setdefault("last_seed", None)

    for index in range(MAX_PLAYERS):
        st.session_state.setdefault(f"player_name_{index}", f"球员{index + 1}")
        st.session_state.setdefault(f"player_gender_{index}", "男")


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
            --court-blue: #2563eb;
            --court-blue-dark: #1d4ed8;
            --court-blue-soft: #eff6ff;
            --court-border: #dbe5f1;
            --court-text: #172033;
            --court-muted: #667085;
        }

        .stApp {
            background:
                radial-gradient(circle at 8% 2%, rgba(37, 99, 235, 0.07), transparent 25rem),
                #f7f9fc;
        }

        .block-container {
            max-width: 1180px;
            padding-top: 1.4rem;
            padding-bottom: 3rem;
        }

        .app-header {
            padding: 0.8rem 0 1.15rem;
            text-align: center;
        }

        .app-title {
            margin: 0;
            color: var(--court-text);
            font-size: clamp(1.85rem, 4.8vw, 2.65rem);
            line-height: 1.18;
            font-weight: 800;
            letter-spacing: 0.01em;
        }

        .app-author {
            margin-top: 0.34rem;
            color: #8a94a3;
            font-size: 0.84rem;
            letter-spacing: 0.04em;
        }

        .section-card {
            margin: 0.2rem 0 0.8rem;
            padding: 1rem 1rem 0.35rem;
            border: 1px solid var(--court-border);
            border-radius: 16px;
            background: rgba(255, 255, 255, 0.93);
            box-shadow: 0 8px 24px rgba(27, 49, 82, 0.055);
        }

        .section-title {
            margin: 0 0 0.22rem;
            color: var(--court-text);
            font-size: 1.08rem;
            font-weight: 750;
        }

        .section-subtitle {
            margin: 0 0 0.7rem;
            color: var(--court-muted);
            font-size: 0.9rem;
            line-height: 1.6;
        }

        .cycle-hint {
            margin: 0.15rem 0 0.55rem;
            padding: 0.65rem 0.8rem;
            color: #30466b;
            border: 1px solid #d9e8ff;
            border-radius: 10px;
            background: var(--court-blue-soft);
            font-size: 0.9rem;
            line-height: 1.55;
        }

        .match-card {
            display: grid;
            grid-template-columns: 84px minmax(0, 1fr) minmax(135px, 0.42fr);
            align-items: center;
            gap: 0.85rem;
            margin: 0 0 0.72rem;
            padding: 0.9rem 1rem;
            border: 1px solid var(--court-border);
            border-radius: 14px;
            background: #ffffff;
            box-shadow: 0 5px 18px rgba(30, 50, 80, 0.045);
        }

        .round-badge {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-height: 38px;
            padding: 0.35rem 0.55rem;
            color: #ffffff;
            border-radius: 10px;
            background: linear-gradient(135deg, var(--court-blue), var(--court-blue-dark));
            font-size: 0.9rem;
            font-weight: 750;
            white-space: nowrap;
        }

        .match-main {
            min-width: 0;
            color: var(--court-text);
            font-size: 1rem;
            font-weight: 720;
            line-height: 1.55;
            text-align: center;
            overflow-wrap: anywhere;
        }

        .versus {
            display: inline-block;
            margin: 0 0.45rem;
            color: var(--court-blue);
            font-size: 0.86rem;
            font-weight: 850;
            text-transform: uppercase;
        }

        .rest-box {
            min-width: 0;
            padding-left: 0.85rem;
            border-left: 1px solid #e6ebf2;
            color: var(--court-muted);
            font-size: 0.88rem;
            line-height: 1.5;
            overflow-wrap: anywhere;
        }

        .rest-label {
            display: block;
            margin-bottom: 0.12rem;
            color: #98a2b3;
            font-size: 0.76rem;
        }

        .cycle-divider {
            display: flex;
            align-items: center;
            gap: 0.8rem;
            margin: 1.2rem 0 0.9rem;
            color: #23528f;
            font-size: 0.92rem;
            font-weight: 750;
            text-align: center;
        }

        .cycle-divider::before,
        .cycle-divider::after {
            content: "";
            flex: 1;
            height: 1px;
            background: #bdd6f6;
        }

        .summary-box {
            margin: 0.6rem 0 1rem;
            padding: 0.85rem 1rem;
            color: #244265;
            border: 1px solid #cfe3fb;
            border-radius: 12px;
            background: #f4f9ff;
            line-height: 1.65;
        }

        .stats-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.75rem;
            margin-top: 0.4rem;
        }

        .stat-card {
            padding: 0.85rem 0.95rem;
            border: 1px solid var(--court-border);
            border-radius: 13px;
            background: #ffffff;
        }

        .stat-name {
            margin-bottom: 0.5rem;
            color: var(--court-text);
            font-size: 1rem;
            font-weight: 780;
        }

        .gender-chip {
            display: inline-block;
            margin-left: 0.35rem;
            padding: 0.08rem 0.42rem;
            color: #596579;
            border-radius: 999px;
            background: #eef2f6;
            font-size: 0.74rem;
            font-weight: 600;
            vertical-align: 0.08rem;
        }

        .stat-values {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.42rem;
        }

        .stat-item {
            color: var(--court-muted);
            font-size: 0.74rem;
            line-height: 1.4;
            text-align: center;
        }

        .stat-item strong {
            display: block;
            margin-bottom: 0.1rem;
            color: var(--court-text);
            font-size: 1.02rem;
        }

        [data-testid="stMetric"] {
            padding: 0.75rem 0.85rem;
            border: 1px solid var(--court-border);
            border-radius: 12px;
            background: #ffffff;
        }

        [data-testid="stForm"] {
            border: 0;
            padding: 0;
        }

        div[data-testid="stButton"] > button {
            min-height: 2.75rem;
            border-radius: 10px;
            font-weight: 720;
        }

        footer {
            visibility: hidden;
        }

        @media (max-width: 760px) {
            .block-container {
                padding: 0.8rem 0.72rem 2.4rem;
            }

            .app-header {
                padding-top: 0.25rem;
            }

            .section-card {
                padding: 0.85rem 0.8rem 0.25rem;
                border-radius: 14px;
            }

            .match-card {
                grid-template-columns: 68px minmax(0, 1fr);
                gap: 0.65rem;
                padding: 0.78rem 0.72rem;
            }

            .round-badge {
                min-height: 34px;
                font-size: 0.8rem;
            }

            .match-main {
                font-size: 0.91rem;
                text-align: left;
            }

            .versus {
                margin: 0 0.3rem;
                font-size: 0.76rem;
            }

            .rest-box {
                grid-column: 1 / -1;
                padding: 0.58rem 0 0;
                border-top: 1px solid #edf0f5;
                border-left: 0;
            }

            .stats-grid {
                grid-template-columns: 1fr;
            }

            .stat-values {
                gap: 0.25rem;
            }

            .stat-item {
                font-size: 0.69rem;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header() -> None:
    st.markdown(
        """
        <div class="app-header">
            <h1 class="app-title">🏸 羽毛球双打分组工具</h1>
            <div class="app-author">Developed by thp</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def ensure_round_selection(player_count: int, mode: str) -> list[int]:
    options = list(round_options(player_count, mode))
    if st.session_state.get("rounds_selected") not in options:
        st.session_state["rounds_selected"] = recommended_rounds(player_count, mode)
    return options


def render_settings() -> tuple[int, str, int, bool]:
    st.markdown(
        """
        <div class="section-card">
            <div class="section-title">比赛设置</div>
            <div class="section-subtitle">选择参与人数、比赛模式和完整公平周期数。</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col_people, col_mode, col_rounds = st.columns([1.05, 1.15, 0.9])

    with col_people:
        player_count = st.radio(
            "参与人数",
            options=[5, 6, 7, 8],
            horizontal=True,
            key="player_count",
            format_func=lambda value: f"{value} 人",
        )

    with col_mode:
        mode = st.radio(
            "比赛模式",
            options=[MODE_RANDOM, MODE_MIXED],
            horizontal=True,
            key="mode",
            format_func=lambda value: MODE_LABELS[value],
        )

    options = ensure_round_selection(player_count, mode)
    with col_rounds:
        rounds = st.selectbox(
            "比赛局数",
            options=options,
            key="rounds_selected",
            format_func=lambda value: f"{value} 局",
        )

    if mode == MODE_MIXED:
        st.session_state["exclude_male_vs_female"] = False

    exclude = st.checkbox(
        "排除男双 vs 女双",
        key="exclude_male_vs_female",
        disabled=(mode == MODE_MIXED),
        help="仅在随机大乱斗中生效。勾选后不会出现两名男性对阵两名女性。",
    )

    cycle = fair_cycle_rounds(player_count, mode)
    cycle_count = rounds // cycle
    st.markdown(
        (
            '<div class="cycle-hint">'
            f"每 <strong>{cycle}</strong> 局为一个完整公平周期；"
            f"当前安排 <strong>{cycle_count}</strong> 个周期，共 <strong>{rounds}</strong> 局。"
            "</div>"
        ),
        unsafe_allow_html=True,
    )

    return player_count, mode, rounds, exclude


def render_player_inputs(player_count: int) -> list[Player]:
    st.markdown(
        """
        <div class="section-card">
            <div class="section-title">球员信息</div>
            <div class="section-subtitle">填写姓名并选择性别；姓名不能留空或重复。</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    players: list[Player] = []
    for index in range(player_count):
        name_col, gender_col = st.columns([3.2, 1.0], vertical_alignment="bottom")

        with name_col:
            name = st.text_input(
                f"球员 {index + 1} 姓名",
                key=f"player_name_{index}",
                placeholder=f"球员{index + 1}",
            )

        with gender_col:
            gender = st.selectbox(
                f"球员 {index + 1} 性别",
                options=GENDERS,
                key=f"player_gender_{index}",
            )

        players.append(Player(name=name.strip(), gender=gender))

    return players


def generate_from_inputs(inputs: CurrentInputs) -> None:
    seed = secrets.randbits(63)

    with st.spinner("正在计算更公平的轮转方案……"):
        result = generate_schedule(
            players=inputs.players,
            mode=inputs.mode,
            rounds=inputs.rounds,
            seed=seed,
            exclude_male_vs_female=inputs.exclude_male_vs_female,
        )

    st.session_state["schedule_result"] = result
    st.session_state["schedule_signature"] = inputs.signature
    st.session_state["last_seed"] = seed


def summary_text(inputs: CurrentInputs, result: ScheduleResult) -> str:
    max_play_streak = max(stat.max_play_streak for stat in result.stats)
    max_rest_streak = max(stat.max_rest_streak for stat in result.stats)

    if result.appearance_gap == 0:
        fairness = "所有人上场次数完全相同"
    else:
        fairness = f"最多与最少上场次数相差 {result.appearance_gap} 次"

    exclusion = (
        "；已排除男双对女双"
        if inputs.mode == MODE_RANDOM and inputs.exclude_male_vs_female
        else ""
    )

    return (
        f"共 {result.cycle_count} 个公平周期（每周期 {result.cycle_length} 局）；"
        f"{fairness}；最长连续上场 {max_play_streak} 局；"
        f"最长连续休息 {max_rest_streak} 局；"
        f"同一搭档最多合作 {result.max_partner_times} 次{exclusion}。"
    )


def match_card(
    round_number: int,
    team_a: str,
    team_b: str,
    resting: str,
) -> str:
    return f"""
    <div class="match-card">
        <div class="round-badge">第 {round_number} 局</div>
        <div class="match-main">
            {html.escape(team_a)}
            <span class="versus">VS</span>
            {html.escape(team_b)}
        </div>
        <div class="rest-box">
            <span class="rest-label">休息人员</span>
            {html.escape(resting)}
        </div>
    </div>
    """


def render_schedule_tab(inputs: CurrentInputs, result: ScheduleResult) -> None:
    for round_index, match in enumerate(result.matches, start=1):
        if round_index > 1 and (round_index - 1) % result.cycle_length == 0:
            cycle_number = (round_index - 1) // result.cycle_length + 1
            st.markdown(
                f'<div class="cycle-divider">以下开始第 {cycle_number} 个公平周期</div>',
                unsafe_allow_html=True,
            )

        team_a = " + ".join(
            inputs.players[player_index].name
            for player_index in match.team_a
        )
        team_b = " + ".join(
            inputs.players[player_index].name
            for player_index in match.team_b
        )
        playing = set(match.participants)
        resting = "、".join(
            player.name
            for player_index, player in enumerate(inputs.players)
            if player_index not in playing
        )

        st.markdown(
            match_card(round_index, team_a, team_b, resting),
            unsafe_allow_html=True,
        )


def render_stats_tab(result: ScheduleResult) -> None:
    cards: list[str] = []

    for stat in result.stats:
        cards.append(
            f"""
            <div class="stat-card">
                <div class="stat-name">
                    {html.escape(stat.name)}
                    <span class="gender-chip">{html.escape(stat.gender)}</span>
                </div>
                <div class="stat-values">
                    <div class="stat-item">
                        <strong>{stat.appearances}</strong>
                        上场次数
                    </div>
                    <div class="stat-item">
                        <strong>{stat.rests}</strong>
                        休息次数
                    </div>
                    <div class="stat-item">
                        <strong>{stat.max_play_streak}</strong>
                        连续上场
                    </div>
                    <div class="stat-item">
                        <strong>{stat.max_rest_streak}</strong>
                        连续休息
                    </div>
                </div>
            </div>
            """
        )

    st.markdown(
        '<div class="stats-grid">' + "".join(cards) + "</div>",
        unsafe_allow_html=True,
    )


def render_result(inputs: CurrentInputs, result: ScheduleResult) -> None:
    st.divider()
    st.subheader("分组结果")

    max_play_streak = max(stat.max_play_streak for stat in result.stats)

    metric_a, metric_b, metric_c, metric_d = st.columns(4)
    metric_a.metric("总局数", len(result.matches))
    metric_b.metric("上场次数差", result.appearance_gap)
    metric_c.metric("最长连续上场", f"{max_play_streak} 局")
    metric_d.metric("同一搭档最多", f"{result.max_partner_times} 次")

    st.markdown(
        f'<div class="summary-box">{html.escape(summary_text(inputs, result))}</div>',
        unsafe_allow_html=True,
    )

    schedule_tab, stats_tab = st.tabs(["对阵安排", "个人统计"])

    with schedule_tab:
        render_schedule_tab(inputs, result)

    with stats_tab:
        render_stats_tab(result)

    st.write("")
    reroll_col, clear_col = st.columns([1, 1])

    with reroll_col:
        if st.button(
            "重新随机",
            type="primary",
            width="stretch",
            key="reroll_schedule",
        ):
            try:
                generate_from_inputs(inputs)
            except SchedulingError as exc:
                st.error(str(exc))
            else:
                st.rerun()

    with clear_col:
        if st.button(
            "清空结果",
            width="stretch",
            key="clear_schedule",
        ):
            st.session_state["schedule_result"] = None
            st.session_state["schedule_signature"] = None
            st.rerun()


def main() -> None:
    st.set_page_config(
        page_title=APP_TITLE,
        page_icon="🏸",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    initialize_state()
    inject_styles()
    render_header()

    player_count, mode, rounds, exclude = render_settings()
    players = render_player_inputs(player_count)

    inputs = CurrentInputs(
        players=players,
        player_count=player_count,
        mode=mode,
        rounds=rounds,
        exclude_male_vs_female=exclude,
    )

    st.write("")
    generate_col, _ = st.columns([1.25, 2.75])

    with generate_col:
        generate_clicked = st.button(
            "生成分组",
            type="primary",
            width="stretch",
            key="generate_schedule",
        )

    if generate_clicked:
        try:
            generate_from_inputs(inputs)
        except SchedulingError as exc:
            st.error(str(exc))
        else:
            st.rerun()

    result = st.session_state.get("schedule_result")
    signature = st.session_state.get("schedule_signature")

    if result is not None:
        if signature == inputs.signature:
            render_result(inputs, result)
        else:
            st.info("球员信息或比赛设置已发生变化，请重新点击“生成分组”。")


if __name__ == "__main__":
    main()
