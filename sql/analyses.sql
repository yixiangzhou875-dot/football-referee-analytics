-- Football referee analytics: core SQL analyses.
-- Each query starts with "-- name: <id>" so src/analysis.py can run them one by one.
-- Referees need at least 50 matches to be compared fairly (small samples are noisy).

-- name: referee_strictness
-- Q1. Which referees are strictest? Cards per match, ranked with a window function.
WITH ref_stats AS (
    SELECT referee,
           COUNT(*)                                             AS matches,
           AVG(home_yellows + away_yellows)                     AS yellows_per_match,
           AVG(home_reds + away_reds)                           AS reds_per_match,
           AVG(home_fouls + away_fouls)                         AS fouls_per_match,
           -- cards per foul: how quickly a referee reaches for a card
           1.0 * SUM(home_yellows + away_yellows) / SUM(home_fouls + away_fouls) AS cards_per_foul
    FROM matches
    GROUP BY referee
    HAVING COUNT(*) >= 50
)
SELECT referee, matches,
       ROUND(yellows_per_match, 2) AS yellows_per_match,
       ROUND(reds_per_match, 3)    AS reds_per_match,
       ROUND(fouls_per_match, 1)   AS fouls_per_match,
       ROUND(cards_per_foul, 3)    AS cards_per_foul,
       RANK() OVER (ORDER BY yellows_per_match DESC) AS strictness_rank,
       ROUND(yellows_per_match - AVG(yellows_per_match) OVER (), 2) AS vs_average
FROM ref_stats
ORDER BY strictness_rank;

-- name: referee_strictness_adjusted
-- Q1b. Same ranking, adjusted for era: cards rose league-wide from 2023/24, so referees
-- who only officiated recently look stricter. Compare each match with its season's average.
WITH season_avg AS (
    SELECT season, AVG(home_yellows + away_yellows) AS season_yellows
    FROM matches GROUP BY season
),
adjusted AS (
    SELECT m.referee,
           (m.home_yellows + m.away_yellows) - s.season_yellows AS yellows_above_season
    FROM matches m JOIN season_avg s ON s.season = m.season
)
SELECT referee, COUNT(*) AS matches,
       ROUND(AVG(yellows_above_season), 2) AS yellows_vs_season_avg,
       RANK() OVER (ORDER BY AVG(yellows_above_season) DESC) AS adjusted_rank
FROM adjusted
GROUP BY referee
HAVING COUNT(*) >= 50
ORDER BY adjusted_rank;

-- name: home_away_bias
-- Q2. Do referees book away teams more than home teams? Gap = away yellows - home yellows,
-- and a fouls-adjusted version (away teams may simply commit more fouls).
SELECT referee,
       COUNT(*) AS matches,
       ROUND(AVG(home_yellows), 2) AS home_yellows,
       ROUND(AVG(away_yellows), 2) AS away_yellows,
       ROUND(AVG(away_yellows) - AVG(home_yellows), 2) AS yellow_gap,
       ROUND(1.0 * SUM(away_yellows) / SUM(away_fouls)
           - 1.0 * SUM(home_yellows) / SUM(home_fouls), 3) AS cards_per_foul_gap,
       ROUND(AVG(CASE result WHEN 'H' THEN 1.0 ELSE 0 END), 3) AS home_win_rate
FROM matches
GROUP BY referee
HAVING COUNT(*) >= 50
ORDER BY yellow_gap DESC;

-- name: league_trend
-- Q3. How has refereeing changed season by season? LAG gives the change vs last season.
WITH by_season AS (
    SELECT season,
           AVG(home_yellows + away_yellows) AS yellows_per_match,
           AVG(home_fouls + away_fouls)     AS fouls_per_match,
           AVG(home_reds + away_reds)       AS reds_per_match,
           AVG(away_yellows) - AVG(home_yellows) AS away_minus_home_yellows,
           AVG(CASE result WHEN 'H' THEN 1.0 ELSE 0 END) AS home_win_rate
    FROM matches
    GROUP BY season
)
-- 2020/21 was played almost entirely without crowds: a natural experiment for crowd pressure.
SELECT season,
       ROUND(away_minus_home_yellows, 2) AS away_minus_home_yellows,
       ROUND(yellows_per_match, 2) AS yellows_per_match,
       ROUND(yellows_per_match - LAG(yellows_per_match) OVER (ORDER BY season), 2) AS yellows_change,
       ROUND(fouls_per_match, 1)   AS fouls_per_match,
       ROUND(reds_per_match, 3)    AS reds_per_match,
       ROUND(home_win_rate, 3)     AS home_win_rate
FROM by_season
ORDER BY season;

-- name: team_rolling_form
-- Q4. Rolling 5-match form for every team (points and yellows), using window frames.
SELECT team, season, match_date, venue, opponent, referee, points, yellows,
       SUM(points) OVER w  AS points_last5,
       ROUND(AVG(yellows) OVER w, 2) AS yellows_last5,
       ROW_NUMBER() OVER (PARTITION BY team, season ORDER BY match_date) AS match_no
FROM team_matches
WINDOW w AS (PARTITION BY team, season ORDER BY match_date
             ROWS BETWEEN 4 PRECEDING AND CURRENT ROW)
ORDER BY team, match_date;

-- name: team_referee_record
-- Q5. How do big clubs do under each referee? (min 15 games together)
SELECT team, referee, COUNT(*) AS games,
       ROUND(AVG(points), 2)  AS points_per_game,
       ROUND(AVG(yellows), 2) AS yellows_per_game,
       ROUND(AVG(points) - AVG(AVG(points)) OVER (PARTITION BY team), 2) AS vs_team_average
FROM team_matches
WHERE team IN ('Arsenal', 'Chelsea', 'Liverpool', 'Man City', 'Man United', 'Tottenham')
GROUP BY team, referee
HAVING COUNT(*) >= 15
ORDER BY team, points_per_game DESC;
