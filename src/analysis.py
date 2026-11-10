"""Step 2: run the SQL analyses, save charts and export clean tables for Power BI.

Run:  python src/analysis.py
Output: outputs/*.png, outputs/*.csv, powerbi/*.csv
"""
import re
import sqlite3
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "football.db"
OUT = ROOT / "outputs"
PBI = ROOT / "powerbi"

BLUE, GREY, RED = "#1f4e79", "#b0b7c3", "#c0392b"
plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})


def load_queries() -> dict:
    text = (ROOT / "sql" / "analyses.sql").read_text()
    blocks = re.split(r"^-- name: (\w+)\s*$", text, flags=re.M)[1:]
    return {name: sql.strip() for name, sql in zip(blocks[::2], blocks[1::2])}


def chart_strictness(raw, adjusted):
    """Season-adjusted strictness, with each referee's raw rank for comparison."""
    df = adjusted.merge(raw[["referee", "strictness_rank"]], on="referee").sort_values("yellows_vs_season_avg")
    fig, ax = plt.subplots(figsize=(7.5, 7.5))
    colors = [RED if v > 0 else BLUE for v in df["yellows_vs_season_avg"]]
    ax.barh(df["referee"], df["yellows_vs_season_avg"], color=colors)
    ax.axvline(0, color="black", lw=1)
    for y, (v, r) in enumerate(zip(df["yellows_vs_season_avg"], df["strictness_rank"])):
        ax.text(v + (0.02 if v >= 0 else -0.02), y, f"raw #{r}", va="center",
                ha="left" if v >= 0 else "right", fontsize=7.5, color="#555")
    ax.set_xlim(df["yellows_vs_season_avg"].min() - 0.25, df["yellows_vs_season_avg"].max() + 0.25)
    ax.set_xlabel("Yellow cards per match vs that season's league average")
    ax.set_title("Referee strictness, adjusted for season\n(2015/16–2025/26, min 50 matches; 'raw #' = unadjusted rank)",
                 loc="left")
    fig.tight_layout()
    fig.savefig(OUT / "referee_strictness.png", dpi=150)
    plt.close(fig)


def chart_crowd_effect(df):
    """Away-minus-home yellow gap by season: the no-crowd season stands out."""
    fig, ax = plt.subplots(figsize=(8.5, 4.2))
    colors = [RED if s == "2020/21" else BLUE for s in df["season"]]
    ax.bar(df["season"], df["away_minus_home_yellows"], color=colors)
    others = df.loc[df["season"] != "2020/21", "away_minus_home_yellows"].mean()
    ax.axhline(others, color="black", lw=1, ls="--")
    ax.text(-0.45, others + 0.008, f"other seasons avg {others:.2f}", ha="left", fontsize=9)
    i = list(df["season"]).index("2020/21")
    ax.annotate("2020/21: no crowds\ngap almost disappears", (i, df["away_minus_home_yellows"].iloc[i]),
                xytext=(i + 0.6, 0.33), fontsize=9, arrowprops={"arrowstyle": "->"})
    ax.set_ylabel("Extra yellows for away team, per match")
    ax.set_title("Away teams get more yellow cards, except when the stadiums were empty", loc="left")
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    fig.savefig(OUT / "crowd_effect.png", dpi=150)
    plt.close(fig)


def chart_home_away(df):
    df = df.sort_values("yellow_gap")
    fig, ax = plt.subplots(figsize=(7, 7))
    ax.barh(df["referee"], df["yellow_gap"], color=[RED if g > 0 else BLUE for g in df["yellow_gap"]])
    ax.axvline(0, color="black", lw=1)
    ax.set_xlabel("Away yellows minus home yellows, per match")
    ax.set_title("Which referees book away teams more?\n(positive = more cards for the away side)", loc="left")
    fig.tight_layout()
    fig.savefig(OUT / "home_away_gap.png", dpi=150)
    plt.close(fig)


def main():
    OUT.mkdir(exist_ok=True)
    PBI.mkdir(exist_ok=True)
    con = sqlite3.connect(DB)
    results = {name: pd.read_sql(sql, con) for name, sql in load_queries().items()}
    for name, df in results.items():
        df.to_csv(OUT / f"{name}.csv", index=False)
        print(f"{name}: {len(df)} rows")
    chart_strictness(results["referee_strictness"], results["referee_strictness_adjusted"])
    chart_crowd_effect(results["league_trend"])
    chart_home_away(results["home_away_bias"])

    # Power BI: one fact table (one row per team per match) + dimension tables.
    pd.read_sql("SELECT * FROM team_matches", con).to_csv(PBI / "fact_team_matches.csv", index=False)
    pd.read_sql("SELECT * FROM matches", con).to_csv(PBI / "fact_matches.csv", index=False)
    pd.read_sql("SELECT * FROM referees", con).to_csv(PBI / "dim_referees.csv", index=False)
    pd.read_sql("SELECT * FROM teams", con).to_csv(PBI / "dim_teams.csv", index=False)
    con.close()
    print(f"Charts in {OUT}, Power BI tables in {PBI}")


if __name__ == "__main__":
    main()
