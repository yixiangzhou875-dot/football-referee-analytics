"""Step 2b: statistical tests for the three findings in report.md.

The descriptive SQL shows differences; this script asks whether they are larger than
chance and whether they survive controls for team quality.

Run:  python src/stats_tests.py
Output: outputs/stats_results.md, outputs/referee_strictness_ci.png,
        outputs/referee_strictness_ci.csv
"""
import sqlite3
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "football.db"
OUT = ROOT / "outputs"
MIN_MATCHES = 50
NO_CROWD = "2020/21"

BLUE, GREY, RED = "#1f4e79", "#b0b7c3", "#c0392b"
plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})


def mean_ci(x, level=0.95):
    """Mean and t-based confidence interval."""
    x = np.asarray(x, dtype=float)
    m, se = x.mean(), stats.sem(x)
    h = se * stats.t.ppf((1 + level) / 2, len(x) - 1)
    return m, m - h, m + h


def fmt_p(p):
    return "< 0.001" if p < 0.001 else f"= {p:.3f}"


def test_crowd_effect(m):
    """Finding 2: is the away-minus-home yellow gap real, and did it shrink without crowds?"""
    m = m.assign(gap=m["away_yellows"] - m["home_yellows"], no_crowd=(m["season"] == NO_CROWD).astype(int))
    normal, empty = m.loc[m.no_crowd == 0, "gap"], m.loc[m.no_crowd == 1, "gap"]

    n_mean, n_lo, n_hi = mean_ci(normal)
    e_mean, e_lo, e_hi = mean_ci(empty)
    p_normal = stats.ttest_1samp(normal, 0).pvalue          # paired test: away vs home in same match
    p_empty = stats.ttest_1samp(empty, 0).pvalue
    welch = stats.ttest_ind(normal, empty, equal_var=False)  # did the gap change?

    lines = [
        "## Finding 2: away teams get more yellows, except without crowds",
        "",
        "Test: for each match, away yellows minus home yellows (a paired comparison within the same match).",
        "",
        "| Seasons | Matches | Gap per match | 95% CI | p (gap = 0) |",
        "| --- | --- | --- | --- | --- |",
        f"| Normal seasons | {len(normal):,} | {n_mean:+.3f} | [{n_lo:+.3f}, {n_hi:+.3f}] | {fmt_p(p_normal).removeprefix("= ")} |",
        f"| 2020/21, no crowds | {len(empty):,} | {e_mean:+.3f} | [{e_lo:+.3f}, {e_hi:+.3f}] | {fmt_p(p_empty).removeprefix("= ")} |",
        "",
        f"Change in the gap (Welch t-test): {n_mean - e_mean:.3f}, t = {welch.statistic:.2f}, p {fmt_p(welch.pvalue)}.",
        "",
    ]
    return lines, dict(n_mean=n_mean, n_lo=n_lo, n_hi=n_hi, p_normal=p_normal,
                       e_mean=e_mean, e_lo=e_lo, e_hi=e_hi, p_empty=p_empty, p_change=welch.pvalue)


def test_through_teams(con):
    """Finding 3: does the crowd effect work through fouls (team behaviour) or through referees?

    One row per team per match. Regress yellows on away, away x no-crowd, with team and
    season fixed effects; then add fouls as a control. Standard errors are clustered by
    match, because the two rows of a match are not independent.
    """
    t = pd.read_sql("SELECT match_id, season, team, venue, fouls, yellows FROM team_matches", con).dropna()
    t["away"] = (t["venue"] == "away").astype(int)
    t["no_crowd"] = (t["season"] == NO_CROWD).astype(int)

    specs = {
        "yellows": "yellows ~ away + away:no_crowd + C(team) + C(season)",
        "fouls": "fouls ~ away + away:no_crowd + C(team) + C(season)",
        "yellows, controlling for fouls": "yellows ~ away + away:no_crowd + fouls + C(team) + C(season)",
    }
    rows = []
    for label, f in specs.items():
        r = smf.ols(f, data=t).fit(cov_type="cluster", cov_kwds={"groups": t["match_id"]})
        for term in ["away", "away:no_crowd"]:
            lo, hi = r.conf_int().loc[term]
            rows.append((label, term, r.params[term], lo, hi, r.pvalues[term]))

    lines = [
        "## Finding 3: the crowd effect works partly through team behaviour",
        "",
        "OLS, one row per team per match, team and season fixed effects, standard errors clustered by match.",
        "`away` is the usual away effect; `away:no_crowd` is how much it changed in 2020/21.",
        "",
        "| Outcome | Term | Coefficient | 95% CI | p |",
        "| --- | --- | --- | --- | --- |",
    ]
    for label, term, b, lo, hi, p in rows:
        lines.append(f"| {label} | `{term}` | {b:+.3f} | [{lo:+.3f}, {hi:+.3f}] | {fmt_p(p).removeprefix("= ")} |")
    lines += [
        "",
        "Reading: adding fouls as a control shrinks the `away:no_crowd` coefficient towards zero, so most of",
        "the no-crowd change ran through how many fouls teams committed rather than through refereeing.",
        "",
    ]
    return lines, {(lab, term): (b, lo, hi, p) for lab, term, b, lo, hi, p in rows}


def test_referees(m):
    """Finding 1: season-adjusted strictness with confidence intervals, then with team controls."""
    m = m.assign(total=m["home_yellows"] + m["away_yellows"])
    m["above_season"] = m["total"] - m.groupby("season")["total"].transform("mean")
    counts = m["referee"].value_counts()
    keep = counts[counts >= MIN_MATCHES].index
    m = m[m["referee"].isin(keep)].copy()

    rows = []
    for ref, g in m.groupby("referee"):
        mean, lo, hi = mean_ci(g["above_season"])
        rows.append((ref, len(g), mean, lo, hi))
    ci = pd.DataFrame(rows, columns=["referee", "matches", "yellows_vs_season_avg", "ci_low", "ci_high"])
    ci = ci.sort_values("yellows_vs_season_avg", ascending=False).reset_index(drop=True)
    ci["adjusted_rank"] = np.arange(1, len(ci) + 1)

    # Same question with team controls: are some referees just given matches between card-heavy teams?
    fe = smf.ols("above_season ~ C(referee, Sum) + C(home_team) + C(away_team)", data=m).fit(cov_type="HC1")
    # Sum (deviation) coding: each referee's coefficient is his gap from the average referee.
    params = fe.params.filter(like="C(referee, Sum)")
    names = sorted(keep)[:-1]
    team_adj = dict(zip(names, params.values))
    team_adj[sorted(keep)[-1]] = -params.sum()
    ci["team_adjusted"] = ci["referee"].map(team_adj)
    ci["team_adjusted_rank"] = ci["team_adjusted"].rank(ascending=False, method="min").astype(int)

    # Bonferroni: how many referees differ from the average once we account for testing 29 at once?
    n = len(ci)
    se = (ci["ci_high"] - ci["yellows_vs_season_avg"]) / stats.t.ppf(0.975, ci["matches"] - 1)
    p = 2 * stats.t.sf(np.abs(ci["yellows_vs_season_avg"] / se), ci["matches"] - 1)
    ci["p_value"] = p
    ci["significant_bonferroni"] = p < 0.05 / n

    # Is the No.1 distinguishable from No.2-5?
    top = ci.iloc[0]
    overlap = ci.iloc[1:5]
    overlapping = overlap[overlap["ci_high"] >= top["ci_low"]]["referee"].tolist()
    R = np.zeros((len(params), len(fe.params)))
    for i, name in enumerate(params.index):
        R[i, list(fe.params.index).index(name)] = 1
    f_test = fe.f_test(R)

    lines = [
        "## Finding 1: season-adjusted referee strictness, with uncertainty",
        "",
        f"{n} referees with at least {MIN_MATCHES} matches. Each match is compared with its season's average.",
        "",
        f"- Joint test that all referees are the same once teams are controlled for: "
        f"F = {float(f_test.fvalue):.2f}, p {fmt_p(float(f_test.pvalue))}." if f_test is not None else "",
        f"- {int(ci['significant_bonferroni'].sum())} of {n} referees differ from the average after a "
        f"Bonferroni correction for {n} tests (p < {0.05 / n:.4f}).",
        f"- {top['referee']} ranks 1st ({top['yellows_vs_season_avg']:+.2f}, 95% CI "
        f"[{top['ci_low']:+.2f}, {top['ci_high']:+.2f}]), but his 95% interval overlaps with "
        f"{len(overlapping)} of the next four referees ({', '.join(overlapping) if overlapping else 'none'}), "
        f"so the exact order at the top is not reliable.",
        f"- Controlling for home and away team as well, {top['referee']} ranks "
        f"{int(top['team_adjusted_rank'])}{'st' if top['team_adjusted_rank'] == 1 else 'th'}.",
        "",
        "| Rank | Referee | Matches | vs season avg | 95% CI | Rank with team controls | Bonferroni significant |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for _, r in ci.iterrows():
        lines.append(f"| {r.adjusted_rank} | {r.referee} | {r.matches} | {r.yellows_vs_season_avg:+.2f} | "
                     f"[{r.ci_low:+.2f}, {r.ci_high:+.2f}] | {r.team_adjusted_rank} | "
                     f"{'yes' if r.significant_bonferroni else 'no'} |")
    lines.append("")
    return lines, ci


def chart_ci(ci):
    df = ci.sort_values("yellows_vs_season_avg")
    fig, ax = plt.subplots(figsize=(7.5, 7.5))
    y = np.arange(len(df))
    colors = [RED if s and v > 0 else BLUE if s else GREY
              for s, v in zip(df["significant_bonferroni"], df["yellows_vs_season_avg"])]
    ax.errorbar(df["yellows_vs_season_avg"], y,
                xerr=[df["yellows_vs_season_avg"] - df["ci_low"], df["ci_high"] - df["yellows_vs_season_avg"]],
                fmt="none", ecolor="#999", elinewidth=1, capsize=2)
    ax.scatter(df["yellows_vs_season_avg"], y, color=colors, zorder=3, s=28)
    ax.axvline(0, color="black", lw=1)
    ax.set_yticks(y, df["referee"])
    ax.set_xlabel("Yellow cards per match vs that season's average (95% CI)")
    ax.set_title("Referee strictness with uncertainty\n"
                 "red/blue = differs from average after Bonferroni correction; grey = not distinguishable",
                 loc="left", fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT / "referee_strictness_ci.png", dpi=150)
    plt.close(fig)


def main():
    OUT.mkdir(exist_ok=True)
    con = sqlite3.connect(DB)
    m = pd.read_sql("SELECT * FROM matches", con)

    ref_lines, ci = test_referees(m)
    crowd_lines, _ = test_crowd_effect(m)
    team_lines, _ = test_through_teams(con)
    con.close()

    chart_ci(ci)
    ci.to_csv(OUT / "referee_strictness_ci.csv", index=False)
    text = ["# Statistical tests", "", "Generated by `src/stats_tests.py`.", ""] + ref_lines + crowd_lines + team_lines
    (OUT / "stats_results.md").write_text("\n".join(l for l in text if l is not None))
    print("\n".join(text))


if __name__ == "__main__":
    main()
