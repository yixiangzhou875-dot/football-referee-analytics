# Football Referee Analytics AI Agent

An end-to-end data project on Premier League refereeing: raw CSVs → cleaned SQLite database → SQL analysis (window functions) → charts and a one-page insight report → an LLM agent that answers plain-English questions by writing and running its own SQL.

**Data:** 4,180 Premier League matches, 11 seasons (2015/16–2025/26), 47 referees. Each match has the referee, goals, shots, fouls, corners, yellow and red cards.

**Key findings** (full write-up in [`report.md`](report.md)):
1. Raw card counts mislabel strict referees, because cards rose league-wide in 2023/24. After adjusting for season, Mike Dean moves from 11th to 1st.
2. Away teams get 0.21 more yellows per match, but in the no-crowd 2020/21 season this gap fell to 0.02.
3. That drop came mostly from away teams committing fewer fouls, not from referees judging fouls differently.

Each finding is tested statistically in [`src/stats_tests.py`](src/stats_tests.py): confidence intervals, a Welch t-test, a Bonferroni correction across referees, and fixed-effects regressions with clustered standard errors. Results are in [`outputs/stats_results.md`](outputs/stats_results.md).

## Project structure

```
data/raw/            11 season CSVs (source data)
data/football.db     SQLite database built by src/build_db.py
sql/analyses.sql     the SQL analyses (CTEs, RANK, LAG, rolling windows)
src/build_db.py      step 1: clean and load the data
src/analysis.py      step 2: run the SQL, make charts, export Power BI tables
src/stats_tests.py   step 2b: significance tests and regressions for each finding
src/agent.py         step 3: the LLM agent (tool calling)
outputs/             charts and query results
powerbi/             clean fact and dimension tables for a Power BI dashboard
report.md            one-page insight report
```

## How to run

```bash
pip install -r requirements.txt
python src/build_db.py        # build the database
python src/analysis.py        # run analyses, save charts
python src/stats_tests.py     # statistical tests and regressions
```

To use the agent you need an Anthropic API key:

```bash
export ANTHROPIC_API_KEY=your_key        # Windows: set ANTHROPIC_API_KEY=your_key
python src/agent.py "Which referee gives away teams the most extra yellow cards?"
python src/agent.py                      # interactive mode
```

## How the agent works

The agent runs a loop: the model reads the question, picks a tool, Python runs the tool and returns the result, and the model continues until it can answer.

| Tool | What it does |
| --- | --- |
| `get_schema` | Lists the tables and columns, so the model writes valid SQL |
| `run_sql` | Runs one read-only `SELECT` and returns up to 50 rows |
| `make_chart` | Runs a query and saves a bar or line chart |

Safety and reliability choices:
- The database is opened **read-only**, and only single `SELECT`/`WITH` statements are accepted.
- SQL errors are returned to the model so it can fix its own query.
- The system prompt requires every reported number to come from a query, a minimum sample of 50 matches, and season adjustment across eras.
- A step limit stops runaway loops.

## SQL techniques used

- **CTEs** to build intermediate tables (`WITH ref_stats AS ...`)
- **RANK()** to rank referees by strictness
- **AVG() OVER ()** to compare each referee with the overall average
- **LAG()** for season-on-season change
- **Rolling windows** (`ROWS BETWEEN 4 PRECEDING AND CURRENT ROW`) for 5-match form
- **JOIN** to adjust each match by its season average
- A **view** (`team_matches`) that reshapes one-row-per-match into one-row-per-team-per-match

## Statistical methods

- **95% confidence intervals** for each referee's season-adjusted strictness
- **Bonferroni correction** when comparing 29 referees at once, to avoid false positives
- **Joint F-test** that all referees are the same, controlling for home and away team
- **Paired comparison and Welch t-test** for the home/away gap and its change without crowds
- **OLS with team and season fixed effects**, standard errors clustered by match, with and without a fouls control to separate team behaviour from refereeing

## Data source

Match data from [football-data.co.uk](https://www.football-data.co.uk/), via the open [datasets/football-datasets](https://github.com/datasets/football-datasets) repository.
