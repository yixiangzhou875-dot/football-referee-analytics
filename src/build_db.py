"""Step 1: clean the raw season CSVs and load them into a SQLite database.

Run:  python src/build_db.py
Output: data/football.db  (tables: matches, referees, teams; view: team_matches)
"""
import re
import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
DB = ROOT / "data" / "football.db"

COLUMNS = {  # raw column -> clean column
    "Date": "match_date", "HomeTeam": "home_team", "AwayTeam": "away_team",
    "FTHG": "home_goals", "FTAG": "away_goals", "FTR": "result",
    "HTHG": "ht_home_goals", "HTAG": "ht_away_goals", "Referee": "referee",
    "HS": "home_shots", "AS": "away_shots", "HST": "home_shots_on_target",
    "AST": "away_shots_on_target", "HF": "home_fouls", "AF": "away_fouls",
    "HC": "home_corners", "AC": "away_corners", "HY": "home_yellows",
    "AY": "away_yellows", "HR": "home_reds", "AR": "away_reds",
}


def clean_referee(name: str) -> str:
    """Standardise referee names, e.g. ' Oliver, M.' / 'M. Oliver ' -> 'M Oliver'."""
    if not isinstance(name, str) or not name.strip():
        return None
    name = name.replace("\xa0", " ").strip()
    if "," in name:  # 'Surname, A. B.' -> 'A Surname'
        surname, initials = [p.strip() for p in name.split(",", 1)]
        name = f"{initials[:1]} {surname}"
    name = re.sub(r"\.", " ", name)
    parts = name.split()
    if len(parts) >= 2 and len(parts[0]) > 1 and parts[0][1:].islower() and len(parts) == 2:
        parts[0] = parts[0][0]  # 'Mike Dean' -> 'M Dean'
    if len(parts) > 2:  # 'A G Wiley' -> 'A Wiley'
        parts = [parts[0], parts[-1]]
    name = " ".join(p[0].upper() + p[1:] for p in parts)
    return TYPO_FIXES.get(name, name)


# One-off typos in the source data (each appears once, next to a regular referee).
TYPO_FIXES = {"K Kavanagh": "C Kavanagh", "O Oliver": "M Oliver"}


def season_label(file_stem: str) -> str:
    code = file_stem.split("-")[1]          # '1516'
    return f"20{code[:2]}/{code[2:]}"       # '2015/16'


def load() -> pd.DataFrame:
    frames = []
    for f in sorted(RAW.glob("season-*.csv")):
        df = pd.read_csv(f)[list(COLUMNS)].rename(columns=COLUMNS)
        df["season"] = season_label(f.stem)
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    df["match_date"] = pd.to_datetime(df["match_date"]).dt.strftime("%Y-%m-%d")
    df["referee"] = df["referee"].map(clean_referee)
    for col in ("home_team", "away_team"):
        df[col] = df[col].str.strip()
    before = len(df)
    df = df.drop_duplicates(subset=["match_date", "home_team", "away_team"])
    print(f"Loaded {before} rows, {before - len(df)} duplicates removed, "
          f"{df['referee'].isna().sum()} matches without a referee")
    df.insert(0, "match_id", range(1, len(df) + 1))
    return df


def build(df: pd.DataFrame) -> None:
    DB.unlink(missing_ok=True)
    con = sqlite3.connect(DB)
    df.to_sql("matches", con, index=False)
    con.executescript(
        """
        CREATE TABLE referees AS
            SELECT referee, COUNT(*) AS matches, MIN(match_date) AS first_match,
                   MAX(match_date) AS last_match
            FROM matches WHERE referee IS NOT NULL GROUP BY referee;
        CREATE TABLE teams AS
            SELECT team, COUNT(DISTINCT season) AS seasons FROM (
                SELECT home_team AS team, season FROM matches
                UNION ALL SELECT away_team, season FROM matches)
            GROUP BY team;

        -- One row per team per match: makes team-level questions easy.
        CREATE VIEW team_matches AS
            SELECT match_id, season, match_date, referee, home_team AS team,
                   away_team AS opponent, 'home' AS venue,
                   home_goals AS goals_for, away_goals AS goals_against,
                   home_fouls AS fouls, home_yellows AS yellows, home_reds AS reds,
                   CASE result WHEN 'H' THEN 3 WHEN 'D' THEN 1 ELSE 0 END AS points
            FROM matches
            UNION ALL
            SELECT match_id, season, match_date, referee, away_team, home_team, 'away',
                   away_goals, home_goals, away_fouls, away_yellows, away_reds,
                   CASE result WHEN 'A' THEN 3 WHEN 'D' THEN 1 ELSE 0 END
            FROM matches;

        CREATE INDEX idx_matches_referee ON matches(referee);
        CREATE INDEX idx_matches_season ON matches(season);
        """
    )
    con.commit()
    n = con.execute("SELECT COUNT(*), COUNT(DISTINCT season), COUNT(DISTINCT referee) FROM matches").fetchone()
    print(f"Database built: {n[0]} matches, {n[1]} seasons, {n[2]} referees -> {DB}")
    con.close()


if __name__ == "__main__":
    build(load())
