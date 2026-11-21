# -*- coding: utf-8 -*-
"""提交历史树的泳道布局（纯 Python，无界面依赖，v1 #5 的“算图”部分）。

输入：按时间倒序的 Commit 列表（GitRepo.log 的返回值）；
输出：就地填充每个 Commit 的泳道号与连线信息（UI 只管画，不算图）。

算法（gitk / SourceTree 的简化版）：
- active: 泳道 → 该泳道正在“等待”的父提交 hash
- 一个提交到达时：若某泳道正等着它 → 画在那条泳道上（多个泳道等它 = 合流）；
  否则取一条空泳道或开新泳道（新分支/根提交）
- 第一个父提交延续本泳道；其余父提交各开新泳道（分叉）
"""

from __future__ import annotations

from .git_wrapper import Commit


def assign_lanes(commits: list[Commit]) -> None:
    active: dict[int, str] = {}   # 泳道 -> 等待中的父提交 hash
    free: list[int] = []           # 空泳道（复用，避免越画越宽）
    next_lane = 0

    for c in commits:
        c.merge_edges.clear()
        c.fork_edges.clear()
        c.lanes_above = sorted(active.keys())

        # 有泳道在等这个提交吗？
        waiting = sorted(l for l, h in active.items() if h == c.hash)
        if waiting:
            c.lane = waiting[0]
            for l in waiting[1:]:
                # 多条泳道合流到同一提交 → 记一条合流横线，释放多余泳道
                c.merge_edges.append((l, c.lane))
                del active[l]
                free.append(l)
            free.sort()
        else:
            if free:
                c.lane = free.pop(0)
            else:
                c.lane = next_lane
                next_lane += 1

        # 父提交：第一个延续本泳道，其余开新泳道（分叉）
        if c.parents:
            active[c.lane] = c.parents[0]
            for p in c.parents[1:]:
                if free:
                    l2 = free.pop(0)
                else:
                    l2 = next_lane
                    next_lane += 1
                active[l2] = p
                c.fork_edges.append((c.lane, l2))
        else:
            # 根提交：泳道到此为止
            if c.lane in active:
                del active[c.lane]
            free.append(c.lane)
            free.sort()

        c.lanes_below = sorted(active.keys())
