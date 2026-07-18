---
title: 指令速查
date: 2026-01-01 07:30:00
categories: 卷五 · 附录
---

本卷收录当前版本全部 24 个指令：先是一张总表，后是带子命令的指令用法。

> 在任意聊天中发送 `/help`，机器人也会列出当前指令清单与一句话说明。

## 指令总表

「场景」一栏标注指令的使用场合：**私聊**限定在机器人私聊中使用，**群聊**需在群内进行，**两用**则私聊群聊皆可。除 `/master` 外，在群里发送私聊限定指令，机器人会提示你回到私聊。

| 指令 | 作用 | 场景 | 手册章节 |
| --- | --- | --- | --- |
| `/start` | 创建角色、测灵根 | 私聊 | [快速开始](/manual/00-quick-start/) |
| `/me` | 查看角色面板 | 私聊 | [核心资源总览](/manual/02-resources/) |
| `/cultivate` | 闭关 / 出关收功 | 私聊 | [闭关与突破](/manual/10-cultivation/) |
| `/explore` | 历练刷图 | 私聊 | [历练与奇遇](/manual/30-explore/) |
| `/dungeon` | 秘境副本 | 私聊 | [秘境副本](/manual/31-dungeon/) |
| `/craft` | 炼丹炼器 | 私聊 | [炼丹与炼器](/manual/32-craft/) |
| `/skills` | 法宝 / 功法 / 本命养成 | 私聊 | [法宝·功法·本命法宝](/manual/33-skills/) |
| `/bag` | 储物袋 | 私聊 | [物品图鉴](/manual/50-items/) |
| `/shop` | NPC 商店、回收、购买精力 | 私聊 | [商店与经济](/manual/34-shop/) |
| `/daily` | 每日签到 | 私聊 | [签到与悬赏任务](/manual/35-quest/) |
| `/quest` | 悬赏任务 | 私聊 | [签到与悬赏任务](/manual/35-quest/) |
| `/master` | 师徒传承 | 两用 | [师徒与道侣](/manual/38-bonds/) |
| `/partner` | 道侣结契与共修 | 两用 | [师徒与道侣](/manual/38-bonds/) |
| `/path` | 道途 / 转修 | 私聊 | [道途与转修](/manual/39-dao-path/) |
| `/ascension` | 飞升试炼与飞升被动 | 私聊 | [飞升](/manual/40-ascension/) |
| `/weekly` | 周活动副本 | 私聊 | [周活动副本](/manual/41-weekly/) |
| `/market` | 玩家坊市（一口价） | 私聊 | [坊市与拍卖行](/manual/42-market-auction/) |
| `/auction` | 拍卖行（竞价） | 私聊 | [坊市与拍卖行](/manual/42-market-auction/) |
| `/sect` | 宗门 | 两用 | [宗门](/manual/36-sect/) |
| `/sectwar` | 宗门战据点 | 私聊 | [宗门战据点](/manual/37-sectwar/) |
| `/pvp` | 群内切磋 | 群聊 | [切磋·天梯·世界Boss](/manual/43-pvp/) |
| `/rank` | 天梯排行 | 群聊 | [切磋·天梯·世界Boss](/manual/43-pvp/) |
| `/boss` | 群内世界 Boss | 群聊 | [切磋·天梯·世界Boss](/manual/43-pvp/) |
| `/help` | 查看简要指南 | 两用 | [快速开始](/manual/00-quick-start/) |

## 带子命令的指令

### `/sect` 宗门

```text
/sect                  查看宗门面板
/sect create 宗门名    创建宗门（需筑基，消耗灵石）
/sect join 宗门名      加入宗门
/sect task             宗门任务
/sect donate 数量      捐输灵石换贡献（每日有上限）
/sect leave            退出宗门
/sect upgrade          升级宗门（宗主操作）
/sect buy 物品名       宗门商店兑换
```

`/sect` 在私聊与群聊中均可使用；创建、加入、任务、捐输、商店与升级都通过指令或按钮完成。详见[宗门](/manual/36-sect/)。

### `/master` 师徒

```text
/master                查看师徒面板
/master 拜师 对方ID    拜对方为师
/master 收徒 对方ID    收对方为徒
```

- 师父需元婴期及以上，徒弟需筑基圆满及以下；任一方发起，另一方确认后生效。
- 在群聊中回复对方消息后发送 `/master 拜师` 或 `/master 收徒`，可省略对方 ID，确认页会发到发起人的私聊。

详见[师徒与道侣](/manual/38-bonds/)。

### `/partner` 道侣

```text
/partner               查看道侣面板（私聊）
/partner 结契 对方ID   发起结契
```

- 双方需金丹期及以上；另一方确认后生效，确认时消耗 1 枚绑定同心结。
- 在群聊中回复对方消息后发送 `/partner 结契`，可省略对方 ID，确认页会发到发起人的私聊。

详见[师徒与道侣](/manual/38-bonds/)。

### `/pvp` 切磋

```text
/pvp                   在群内发起切磋
/pvp @道号             指定对手
/pvp #排名             按天梯排名指定对手
```

也可以回复某位玩家的消息发送 `/pvp`，直接向对方发起切磋。发送后系统会生成一条切磋确认，点击「确认切磋」后自动结算。详见[切磋·天梯·世界Boss](/manual/43-pvp/)。

## 使用提示

- 养成操作以私聊为主，群聊主要用于切磋、排行、世界 Boss 与宗门社交；分流思路详见[私聊与群聊](/manual/01-interface/)。
- 结算、突破、认主等状态变更操作都会给出一次性确认按钮，点击即生效，请看清再点。
- 忘了指令就发 `/help`；不懂名词就查[名词解释](/manual/51-glossary/)；遇事不决可看[常见问题](/manual/52-faq/)。

## 相关章节

- [私聊与群聊](/manual/01-interface/)
- [快速开始](/manual/00-quick-start/)
- [名词解释](/manual/51-glossary/)
- [常见问题](/manual/52-faq/)
