"""L1 确定性校验（§8.4）——无模型、纯规则、可复现。

作用于 extract 出的结构化候选（MutationCandidate）对比台账：
- 境界跳级 / 越界（realm_order + realm_cap，样例 10/1）
- 死而复生（alive 台账 vs 候选，样例 3）
- 战力通胀（per-角色 realm 序列斜率，样例 11，跨章）

conflict_key = hash(类型+实体+位置)，跨修订轮稳定（§6.4）。
"""

from __future__ import annotations

import hashlib
import uuid

from sqlalchemy.orm import Session

from aiink.memory import repository as repo
from aiink.schemas import Finding, MutationCandidate

# 样例 11 阈值：连续 3 章内每次 chapter 都升境界 → 无铺垫通胀强信号
_INFLATION_WINDOW = 3
_INFLATION_STEPS = 2

# 样例 18/23 阈值：伏笔债务（planted 无回收条件 15 章无触碰 / developing 捡起后 10 章不落地 → 烂尾 hint）
_FS_PLANTED_STALL = 15
_FS_DEVELOPING_STALL = 10
# 样例 19 阈值：主线连续 15 章未推进 → 停滞 hint（支线可长期休眠，样例 27 阴性）
_THREAD_STALL = 15


def _key(conflict_type: str, entity: str, chapter_seq: int) -> str:
    return hashlib.md5(f"{conflict_type}:{entity}:{chapter_seq}".encode()).hexdigest()[:16]


class L1Validator:
    def __init__(self, realm_order: list[str]):
        self.realm_order = realm_order
        self.realm_pos = {r: i for i, r in enumerate(realm_order)}

    def validate(self, session: Session, *, project_id: uuid.UUID, chapter_seq: int,
                 candidates: list[MutationCandidate]) -> list[Finding]:
        findings: list[Finding] = []
        characters: dict[uuid.UUID, object] = {}

        for cand in candidates:
            if cand.kind != "character_state":
                continue
            payload = cand.payload
            ch_id = payload.get("character_id")
            if ch_id is None:
                continue
            characters.setdefault(uuid.UUID(str(ch_id)), None)

            field = payload.get("field")
            old_v = payload.get("old_value")
            new_v = payload.get("new_value")

            if field == "realm" and new_v:
                findings.extend(self._realm_checks(session, project_id, chapter_seq,
                                                   str(ch_id), old_v, str(new_v), cand))
            elif field == "alive":
                findings.extend(self._alive_checks(session, project_id, chapter_seq,
                                                   str(ch_id), old_v, new_v, cand))

        # 战力通胀（跨章序列，不依赖候选）
        findings.extend(self.power_inflation_check(session, project_id, chapter_seq))
        # 长线债务（伏笔烂尾 / 主线停滞，不依赖候选；hint 不阻塞，§8.6 线程债务 + §7.9 伏笔治理）
        findings.extend(self.foreshadow_debt_check(session, project_id, chapter_seq))
        findings.extend(self.plot_thread_debt_check(session, project_id, chapter_seq))
        return findings

    # ---- 伏笔烂尾（样例 18/23，阴性 26 对照，§7.9）----
    def foreshadow_debt_check(self, session: Session, project_id: uuid.UUID,
                              chapter_seq: int) -> list[Finding]:
        findings: list[Finding] = []
        for f in repo.get_open_foreshadows(session, project_id):  # planted / developing
            last = f.last_touched or f.planted_chapter
            if not last:
                continue
            if f.status == "developing":
                # 样例 23：作者已捡起（developing）却长期不落地 → 烂尾（不依赖 trigger 成熟度，
                # 以状态作"已承诺"的确定性代理；成熟度语义判断属 L2/阶段 3 主体）
                if last > chapter_seq - _FS_DEVELOPING_STALL:
                    continue
            else:
                # 样例 18：planted 且无回收条件（trigger 空）却长期无触碰 → 烂尾
                if f.trigger:
                    continue  # 有回收条件 = 刻意长沉（样例 26 阴性，0 误报）
                if last > chapter_seq - _FS_PLANTED_STALL:
                    continue
            findings.append(Finding(
                conflict_key=_key("foreshadow", str(f.id), chapter_seq),
                conflict_type="foreshadow", severity="hint", scope="local", source="L1",
                evidence=[{"chapter": chapter_seq,
                           "quote": f"伏笔「{f.description[:40]}」自第 {last} 章起 {chapter_seq - last} 章无触碰"}],
                suggestion="伏笔疑似烂尾：作者决策收/弃（标 resolved/dropped）或补剧情触碰（§7.9）",
            ))
        return findings

    # ---- 剧情线停滞（样例 19，阴性 27 对照，§8.6 P1 线程债务）----
    def plot_thread_debt_check(self, session: Session, project_id: uuid.UUID,
                               chapter_seq: int) -> list[Finding]:
        findings: list[Finding] = []
        for t in repo.get_plot_threads(session, project_id):  # status=active
            if t.kind != "main":
                continue  # 支线可长期休眠（样例 27 阴性）
            if not t.last_progress_chapter or t.last_progress_chapter > chapter_seq - _THREAD_STALL:
                continue
            findings.append(Finding(
                conflict_key=_key("plotline", str(t.id), chapter_seq),
                conflict_type="plotline", severity="hint", scope="local", source="L1",
                evidence=[{"chapter": chapter_seq,
                           "quote": f"主线「{t.name[:40]}」自第 {t.last_progress_chapter} 章起 "
                                    f"{chapter_seq - t.last_progress_chapter} 章未推进"}],
                suggestion="主线长期停滞：推进该线，或作者决策收线/降级（§8.6 P1）",
            ))
        return findings

    # ---- realm ----
    def _realm_checks(self, session: Session, project_id: uuid.UUID, chapter_seq: int,
                      ch_id: str, old_v: str | None, new_v: str, cand: MutationCandidate) -> list[Finding]:
        findings: list[Finding] = []
        # ch_id 是 extract 归一化后的 canonical id（uuid str），按主键查
        from aiink.models import Character
        char = session.get(Character, uuid.UUID(ch_id))
        if char is None:
            return findings

        old_pos = self.realm_pos.get(old_v or "")
        new_pos = self.realm_pos.get(new_v)
        if new_pos is None:
            return findings  # 未知境界，规则不覆盖（未定义领域不阻塞，§7.11）

        cap_pos = self.realm_pos.get(char.realm_cap)
        evidence = [{"chapter": cand.source_chapter, "quote": f"{char.name} 境界 {old_v or '?'} → {new_v}"}]

        # 越界：超过境界上限（样例 1）
        if cap_pos is not None and new_pos > cap_pos:
            findings.append(Finding(
                conflict_key=_key("power", str(ch_id), chapter_seq),
                conflict_type="power", severity="critical", scope="structural", source="L1",
                evidence=evidence,
                suggestion=f"{char.name} 境界上限是 {char.realm_cap}，不能超过",
            ))
        # 跳级：跳过中间境界（样例 10）
        elif old_pos is not None and new_pos - old_pos > 1:
            findings.append(Finding(
                conflict_key=_key("power", str(ch_id), chapter_seq),
                conflict_type="power", severity="critical", scope="structural", source="L1",
                evidence=evidence,
                suggestion="境界需逐境晋升，不能跳级；需补突破契机说明",
            ))
        return findings

    # ---- alive ----
    def _alive_checks(self, session: Session, project_id: uuid.UUID, chapter_seq: int,
                      ch_id: str, old_v: str | None, new_v: object, cand: MutationCandidate) -> list[Finding]:
        findings: list[Finding] = []
        if new_v not in (True, "true", "alive", "生"):
            return findings  # 只拦"复活"方向

        # 台账该角色最近 alive 状态
        state = repo.get_character_state(session, project_id, uuid.UUID(ch_id), chapter_seq - 1)
        last = state.get("alive", "true").lower()
        if last in ("false", "dead", "死", "已死", "no"):
            findings.append(Finding(
                conflict_key=_key("character", str(ch_id), chapter_seq),
                conflict_type="character", severity="critical", scope="structural", source="L1",
                evidence=[{"chapter": cand.source_chapter, "quote": f"{ch_id} 台账已死却被写为存活"}],
                suggestion="死而复生需先落复活机制规则（facts），否则冲突",
            ))
        return findings

    # ---- 战力通胀（跨章，样例 11）----
    def power_inflation_check(self, session: Session, project_id: uuid.UUID,
                              chapter_seq: int) -> list[Finding]:
        findings: list[Finding] = []
        for char in repo.get_all_characters(session, project_id):
            # 该角色 realm 台账序列（近窗口）
            from aiink.models import CharacterState
            rows = session.query(CharacterState).filter(
                CharacterState.project_id == project_id,
                CharacterState.character_id == char.id,
                CharacterState.field == "realm",
                CharacterState.chapter_seq <= chapter_seq,
            ).order_by(CharacterState.chapter_seq.desc()).limit(_INFLATION_WINDOW).all()

            if len(rows) < _INFLATION_WINDOW:
                continue
            # 逆序 → 从早到晚
            seq = list(reversed([r.new_value or "" for r in rows]))
            positions = [self.realm_pos.get(r) for r in seq]
            if any(p is None for p in positions):
                continue
            diffs = [positions[i + 1] - positions[i] for i in range(len(positions) - 1)]
            # 连续窗口内每次跳级（样例 11：无铺垫连续通胀）
            if len(diffs) >= _INFLATION_STEPS and all(d >= 1 for d in diffs):
                findings.append(Finding(
                    conflict_key=_key("power", str(char.id), chapter_seq),
                    conflict_type="power", severity="major", scope="structural", source="L1",
                    evidence=[{"chapter": r.chapter_seq, "quote": f"{char.name} 连续 {len(seq)} 章每章升境界: {' → '.join(seq)}"}],
                    suggestion="战力通胀强信号：连续数章无铺垫升级；若为奇遇需补代价说明，否则降为待审计",
                ))
        return findings
