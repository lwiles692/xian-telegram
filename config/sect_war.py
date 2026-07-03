"""宗门战 / 据点配置（v2 M4）。"""

# 据点战开放窗口：每周六 20:00–21:00（上海时区，固定 UTC+8，无夏令时）。
WAR_TZ_OFFSET_SECONDS = 8 * 3600
WAR_WEEKDAY = 5          # Monday=0 … Saturday=5
WAR_START_HOUR = 20
WAR_END_HOUR = 21        # 左闭右开：[20:00, 21:00)
WAR_STAMINA_COST = 20
WAR_ACTION_DURATION_SECONDS = 10 * 60
WAR_NO_STAMINA_WINDOW_SECONDS = 1

# 据点守卫：成员进攻据点须先击败守卫（复用战斗引擎）才计入宗门积分（spec §8.1）。
# 守卫按元婴/化神前段（realm2 上锚附近）配置——化神圆满成员可稳胜，低境界会落败。
def _guard(name, hp, atk, df, spd, crit, skills=("普攻", "快剑斩")):
    return {"name": name, "hp": hp, "mp": 300, "atk": atk, "df": df,
            "spd": spd, "crit": crit, "skills": list(skills)}


OUTPOSTS = {
    "cave": {"name": "洞府据点", "buff": {"seclusion_pct": 0.08}, "win_score": 10,
             "guard": _guard("洞府守将", 8000, 640, 460, 200, 72)},
    "mine": {"name": "矿脉据点", "buff": {"drop_pct": 0.05}, "win_score": 10,
             "guard": _guard("矿脉守将", 7600, 620, 450, 195, 70)},
    "altar": {"name": "祭坛据点", "buff": {"stat_pct": 0.05}, "win_score": 10,
              "guard": _guard("祭坛守将", 8600, 680, 480, 210, 76)},
}

# 据点战赛季结算：积分最高的宗门夺魁，成员获绑定道行奖励。
WAR_SEASON_DAOHANG_REWARD = 120
