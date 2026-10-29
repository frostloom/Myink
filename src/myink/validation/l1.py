"""L1 确定性校验（§8.4）——无模型、纯规则、可复现。

作用于 extract 出的结构化候选（MutationCandidate）对比台账：
- 境界跳级 / 越界（realm_order + realm_cap，样例 10/1）
- 死而复生（alive 台账 vs 候选，样例 3）
- 战力通胀（per-角色 realm 序列斜率，样例 11，跨章）
- 候选 old_value-vs-台账（extract 误读注入快照，样例 16/20/21 确定性窄脚印）
- 关系台账自洽（重复/矛盾活跃行，§7.8）
- 伏笔烂尾 / 主线停滞（样例 18/19/23/26/27）
- 桥段重复向量近邻（样例 14，阴性 32 对照，§8.6）：事件向量近邻 + 呼应词豁免
- 句式禁令（任何题材）：「不是…」紧跟「是…」（含拆成两句的「不是…。是…」）、连续排比，出现即 critical
- 正文卫生：章节号指称（critical）、作者说教词 / 连续「了」字 / 段落过长（hint）

conflict_key = hash(类型+实体+位置)，跨修订轮稳定（§6.4）。
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from myink.memory import repository as repo
from myink.memory.embedder import get_embedder
from myink.memory.vector_store import PgvectorStore
from myink.models import Character, CharacterState, Event, Fact, Relation
from myink.schemas import Finding, MutationCandidate

logger = logging.getLogger(__name__)

_ITEM_RE = r"[\u4e00-\u9fffA-Za-z0-9]{2,24}"
_DESTROY_RE = re.compile(
    "(" + _ITEM_RE + r")被[\u4e00-\u9fffA-Za-z0-9]{0,16}?(?:劈碎|击碎|摧毁|毁掉)"
)
_DESTROY_ALT_RE = re.compile("(" + _ITEM_RE + r")已毁")
_NEGATION_RE = re.compile(r"未|没|没有|若|如果|倘若|假如|差点|几乎")
# 实际“使用/取出”动作：动作动词 + 可选“了” + 精确物品名，其后只能是子句结尾/标点
# 或已许可的动作补语；不接受更长物品名的前缀命中，也不接受占有式前缀。
_USE_VERB_ALT = "从怀中摸出|怀中摸出|取出|祭出|催动|使用|掏出|拿出|摸出"
# 动作动词本身已足够区分；左侧不再要求非汉字边界（否则「林砚从怀中摸出定水珠」漏检），
# 但仍靠精确物品名 + 右侧边界/许可补语拒绝更长物品名前缀命中。
_USE_EXACT_RE_TPL = (
    r"(?:{v})(?:了)?{item}"
    r"(?=$|[，。；！？、,.!?;:\s])"
)
_REPAIR_RE = re.compile(
    r"^" + _ITEM_RE + r"(?:以[^，。；！？]{1,20})?重铸(?:成功)?$"
)
# 同一物品修复动作：物品名必须直接绑定修复动词，且必须为已完成肯定语义。
_REPAIR_VERB_ALT = (
    r"(?:已经|已)?重铸(?:成功|完成|完毕|而成|归来)?|(?:已经|已)修复(?:成功|完成|完毕|如初|完好)?"
    r"|修复(?:成功|完成|完毕|如初|完好)|重新(?:淬炼|祭炼)(?:完成|完毕|成功)"
)
_REPAIR_ITEM_RE_TPL = (
    r"(?:^|(?<=[^\u4e00-\u9fffA-Za-z0-9])){item}"
    r"(?:以[^，。；！？]{1,20})?(?:" + _REPAIR_VERB_ALT + r")"
    r"(?=$|[，。；！？、,.!?;:\s])"
)
_REPAIR_PENDING_RE = re.compile(
    r"打算|准备|想要|将要|即将|试图|计划|欲|将(?:被|要)|未|没|没有|未能|无法|失败|难以|若|如果|倘若|假如|差点|几乎"
)

# 样例 11 阈值：连续 3 章内每次 chapter 都升境界 → 无铺垫通胀强信号
_INFLATION_WINDOW = 3
_INFLATION_STEPS = 2

# 样例 18/23 阈值：伏笔债务（planted 无回收条件 15 章无触碰 / developing 捡起后 10 章不落地 → 烂尾 hint）
_FS_PLANTED_STALL = 15
_FS_DEVELOPING_STALL = 10
# 样例 19 阈值：主线连续 15 章未推进 → 停滞 hint（支线可长期休眠，样例 27 阴性）
_THREAD_STALL = 15

# 句式禁令：出现「不是…」紧跟「是…」即命中——「不是…而是…」与「不是…，是…」都含在里面，
# 拆成两句的「不是…。是…」同样算：两半之间只允许标点与空白（含换行），后半句须以「是」起头。
# 后一个「是」紧跟连词/副词/语气助词时（只是、但是、于是、就是、还是、可是、更是…）或紧跟另
# 一个「不」时（是不是，不是A不是B），那是词的一部分，不是「先否定、再改口」的对举，跳过。
# 逗号后的空白不设上限：换行与长空白都在同一处，判定不该被排版打断。
_IS_PREFIX = "不只但于就还可总要倒单也便仍更全若虽既光自又且均算本或其实很尤确非即亦竟偏却老硬乃岂"
_NOT_IS = re.compile(rf"(?<!是)不是[^。！？!?\n]{{0,40}}[。！？!?]*\s*(?<![{_IS_PREFIX}])是")
_SENTENCE_END = re.compile(r"[。！？!?]+")

# 正文卫生四则。
# 阈值取参照实现的**实际值**：其注释与代码不符处已逐条标注，以代码为准。
_CHAPTER_REF = re.compile(r"第\s*\d+\s*章|[Cc]hapter\s+\d+")
_SERMON_WORDS = ("显然", "毋庸置疑", "不言而喻", "众所周知", "不难看出")
_CONSECUTIVE_LE_MIN = 6        # 参照实现的注释写「3 句以上」，代码实为 >= 6
_LONG_PARAGRAPH_CHARS = 300    # 参照实现的注释写「50-250 字为宜」，代码实为 > 300
_LONG_PARAGRAPH_MIN = 2        # 需 >= 2 个超长段落才报

# 样例 14/32 阈值：桥段重复（事件向量近邻，§8.6）。跨章最小间隔 10（样例 14 ch5→ch15 恰在边界）；
# cosine distance < 0.3 ⟺ 余弦相似度 > 0.7。宁缺毋滥（§8.8）：先保阴性 0 误报，再抬阳性检出率。
_REPEAT_MIN_GAP = 10
_REPEAT_DIST_THRESHOLD = 0.3
_REPEAT_TOP_K = 10
_REPEAT_QUERY_CAP = 3

# 呼应豁免词表（样例 32 阴性 0 误报关键）：正文/候选摘要含任一标记 → 整章/该候选豁免。
# 词表故意偏宽（宽豁免只损检出率不损误报率）；未覆盖表述靠 L2 抽样兜底（阶段 3 收尾）。
_CALLBACK_MARKERS = (
    "当年", "昔日", "想当年", "忆当年", "与当年",      # 时间回指
    "何其相似", "如出一辙", "似曾相识", "恍如隔世",      # 相似性元叙述
    "故技重施", "旧事重演", "历史重演", "重演",          # 明示重复
    "再现", "这一幕", "此情此景", "同样的一幕",          # 场景回指
    "忆起", "历历在目", "仿佛昨日",                      # 记忆唤起
)

# 样例 2/40 阈值：阵营敌对（§8.4 L1 第 1 类）。活跃 hostile 关系双名共现 + 任一协作标记 → 冲突。
# 词表故意偏窄（宁缺毋滥 §8.8）：只收明确协作语义的标记；且仅当 hostile 关系存在才触发，
# 双名须共现于本章 draft。合法联手须先落临时盟约（relation 带 valid_to）→ 守卫跳过（样例 40）。
_FACTION_COOP_MARKERS = (
    "并肩作战", "并肩而立", "共抗", "携手", "联手",
    "化敌为友", "握手言和", "把酒言和",
)

# 通用台账比对字段：realm/alive 已有 _realm_checks/_alive_checks 消费 old_value，
# 通用检查仅覆盖无专属检查的字段（防同候选双报 + test_flow 样例 1 类别级不回归）。
# 样例 16/20/21 的确定性窄脚印（状态机一致性）——正文-台账语义比对留 L2。
_GENERAL_STATE_FIELDS = ("location", "injury", "power", "item", "knowledge", "goal", "identity")


def _key(conflict_type: str, entity: str, chapter_seq: int) -> str:
    return hashlib.md5(f"{conflict_type}:{entity}:{chapter_seq}".encode()).hexdigest()[:16]


def _is_parallel(chunks: list[str]) -> bool:
    """连续三个分句结构相同：长度接近，且开头两字相同或结尾一字相同。"""
    if any(not (3 <= len(chunk) <= 24) for chunk in chunks):
        return False
    lengths = [len(chunk) for chunk in chunks]
    if max(lengths) - min(lengths) > 4:
        return False
    if len({chunk[:2] for chunk in chunks}) == 1:
        return True
    return len({chunk[-1] for chunk in chunks}) == 1


def _parallel_quotes(text: str) -> list[str]:
    hits: list[str] = []
    sentences = [part.strip() for part in _SENTENCE_END.split(text) if part.strip()]
    for sentence in sentences:
        parts = [part.strip() for part in re.split(r"[，,]", sentence) if part.strip()]
        for index in range(len(parts) - 2):
            window = parts[index:index + 3]
            if _is_parallel(window):
                hits.append("，".join(window))
                break
    for index in range(len(sentences) - 2):
        window = sentences[index:index + 3]
        if _is_parallel(window):
            hits.append("。".join(window))
    return hits


def _prose_ban_quotes(text: str) -> list[str]:
    quotes: list[str] = []
    from myink.writing_resource_runtime import validation_flag
    for match in (_NOT_IS.finditer(text) if validation_flag("not_is") else []):
        # 匹配式只负责判定；证据还需包含「是」之后的内容，供审核/修订定位。
        # 保留原文切片，遇句末或换行停止，避免把后续正文整段带入报告。
        # 句末标点落在匹配内部（「不是…。是…」）时不算收束，越过它把改口那半一并带出；
        # 换行始终收束，证据不跨行。
        end = match.start()
        limit = min(len(text), match.start() + 160)
        while end < limit:
            ch = text[end]
            if ch in "\r\n":
                break
            if ch in "。！？!?" and end >= match.end():
                break
            end += 1
        quotes.append(text[match.start():end])
    if validation_flag("parallel"):
        quotes.extend(_parallel_quotes(text))
    seen: set[str] = set()
    ordered: list[str] = []
    for quote in quotes:
        if quote not in seen:
            seen.add(quote)
            ordered.append(quote)
    return ordered


def _chapter_refs(text: str) -> list[str]:
    """正文里出现的章节号指称，去重保序——角色不知道自己在第几章。"""
    return list(dict.fromkeys(_CHAPTER_REF.findall(text)))


def _sermon_words(text: str) -> list[str]:
    """作者说教词，出现即收。含「显然」这类日常词，故只按 hint 报，不阻塞。"""
    return [word for word in _SERMON_WORDS if word in text]


def _max_consecutive_le(text: str) -> int:
    """最长连续含「了」的句数。句以本案既有的 _SENTENCE_END 切分。"""
    longest = current = 0
    for sentence in _SENTENCE_END.split(text):
        if len(sentence.strip()) > 2 and "了" in sentence:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _long_paragraphs(text: str) -> list[int]:
    """按空行分段后，超过 _LONG_PARAGRAPH_CHARS 的段落长度清单。"""
    parts = (part.strip() for part in re.split(r"\n\s*\n", text))
    return [len(part) for part in parts if len(part) > _LONG_PARAGRAPH_CHARS]


def _has_callback_marker(text: str | None) -> bool:
    """呼应豁免：文本含任一呼应/回指元叙述标记词（样例 32 阴性 0 误报）。"""
    return bool(text) and any(m in text for m in _CALLBACK_MARKERS)


def _names_present(draft: str, ch: object) -> bool:
    """角色名精确子串出现于 draft（样例 2 双名共现判据）。"""
    return ch.name in draft


def _temp_alliance_covers(session: Session, project_id: uuid.UUID,
                          source_id: uuid.UUID, target_id: uuid.UUID, chapter_seq: int) -> bool:
    """守卫（样例 40）：pair 存在非 hostile 关系行覆盖本章 → 合法联手/已非敌对，跳过。

    - 覆盖 = valid_from <= chapter_seq 且 (valid_to IS NULL 或 valid_to >= chapter_seq)；
    - 双向（(a,b) 与 (b,a) 都查）；含带 valid_to 的临时盟约与永久非敌对行——
      后者本会同有 hostile 行 → relation_ledger_check 判矛盾兜底，此处防双报。
    """
    rows = session.execute(
        select(Relation).where(
            Relation.project_id == project_id,
            or_(
                and_(Relation.source_id == source_id, Relation.target_id == target_id),
                and_(Relation.source_id == target_id, Relation.target_id == source_id),
            ),
            Relation.relation_type != "hostile",
            or_(Relation.valid_from.is_(None), Relation.valid_from <= chapter_seq),
            or_(Relation.valid_to.is_(None), Relation.valid_to >= chapter_seq),
        )
    ).scalars().all()
    return bool(rows)


class L1Validator:
    @staticmethod
    def _draft_reuses_item(draft: str, item: str) -> bool:
        return bool(L1Validator._draft_use_quote(draft, item))

    @staticmethod
    def _draft_use_quote(draft: str, item: str, actors: object = None) -> str:
        """返回实际使用该精确物品的子句；仅提及/意图/前缀命中不算使用。"""
        if not item:
            return ""
        try:
            use_re = re.compile(_USE_EXACT_RE_TPL.format(v=_USE_VERB_ALT, item=re.escape(item)))
        except re.error:
            return ""
        actor_names: tuple[str, ...] = tuple(
            sorted({str(n).strip() for n in (actors or ()) if str(n).strip()},
                   key=len, reverse=True)
        )
        for clause in re.split(r"[，。；！？\n]", draft):
            c = clause.strip()
            if not c or item not in c:
                continue
            # 先在原文本 c 上定位真实精确使用匹配；命中后才允许把该匹配自身的物品名
            # 词形（如「不灭珠」「不朽剑」「不败铃」内含「不」）从情绪/否定守卫中排除。
            # 除该精确物品 token 外的全部文本（动词、施动者、其余字句）仍走原全部守卫。
            m = use_re.search(c)
            if m:
                t0 = m.end() - len(item)
                t1 = m.end()
                if t0 < 0 or c[t0:t1] != item:
                    continue
                rest = c[:t0] + c[t1:]
                # 仅在匹配前的整段文本恰好等于一个已注册的完整人名时，才把该
                # 人名身份从否定/条件守卫中排除；未注册或仅部分命中的前缀保持原守卫。
                pre = c[:m.start()].strip()
                if pre and pre in actor_names:
                    rest = c[t1:]
            else:
                rest = c
            # 本子句局部否定/追忆守卫：不改变全局 _NEGATION_RE 语义，仅在本处额外拒绝
            # 「不使用 / 不能取出 / 不再催动」与「曾经使用」。
            if re.search(r"不|曾经", rest):
                continue
            if _NEGATION_RE.search(rest) or _REPAIR_PENDING_RE.search(rest):
                continue
            if item + "的碎片" in c or item + "的残片" in c:
                continue
            if "想起" in rest or "当年" in rest or "回忆" in rest or "想到" in rest:
                continue
            if m:
                # 引文必须含真实使用匹配本身：以匹配位置为中心取窗口，不做前缀截断、不编造。
                start = max(0, m.start() - 20)
                end = min(len(c), m.end() + 20)
                return c[start:end]
        return ""

    @staticmethod
    def _draft_quote(draft: str, item: str) -> str:
        return L1Validator._draft_use_quote(draft, item)

    @staticmethod
    def _item_repair_confirmed(session: Session, *, project_id: uuid.UUID,
                               chapter_seq: int, item: str,
                               destroyed_chapter: int) -> bool:
        facts = session.execute(
            select(Fact).where(and_(Fact.project_id == project_id,
                                   Fact.confirm_status == "confirmed"))
            .order_by(Fact.source_chapter)
        ).scalars()
        try:
            repair_re = re.compile(_REPAIR_ITEM_RE_TPL.replace("{item}", re.escape(item)))
        except re.error:
            return False
        for fact in facts:
            if fact.source_chapter is None:
                continue
            if fact.source_chapter <= destroyed_chapter or fact.source_chapter > chapter_seq:
                continue
            if fact.valid_from is not None and fact.valid_from > chapter_seq:
                continue
            if fact.valid_to is not None and fact.valid_to < chapter_seq:
                continue
            content = getattr(fact, "content", None) or ""
            for clause in re.split(r"[，。；！？\n]", content):
                c = clause.strip()
                if not c or _REPAIR_PENDING_RE.search(c):
                    continue
                if repair_re.search(c):
                    return True
        return False

    @staticmethod
    def _visit_explained(sentences: list[str], actor_name: str) -> bool:
        """同一段内明确绑定同一人物的肯定失忆/重游说明才豁免。"""
        for s in sentences:
            if not s.startswith(actor_name):
                continue
            suffix = s[len(actor_name):]
            if L1Validator._VISIT_AFFIRM_DENY_RE.search(suffix):
                continue
            if L1Validator._VISIT_AFFIRM_EXACT_RE.fullmatch(suffix.strip()):
                return True
        return False

    @staticmethod
    def _visit_stated(sent: str, actor_name: str, place: str, marker: str) -> bool:
        """当前断言句必须人物句首且含精确地点与首次标记，且无否定/假设/回忆。"""
        if not place or not marker:
            return False
        if len(sent) > 512:
            return False
        s = sent.strip()
        form = (r"^" + re.escape(actor_name) + r"\u7b2c\u4e00\u6b21\u6765\u5230"
                + re.escape(place) + r"$")
        if re.fullmatch(form, s):
            return True
        form = (
            r"^" + re.escape(actor_name)
            + r"(?:\u62ac\u7738|\u671b\u7740|\u5fc3\u9053)(?P<prose>[\u4e00-\u9fff\uff0c\u3001\u3002\uff1a\uff1b]{0,120})"
            + r"\u8fd9\u5c31\u662f" + re.escape(place) + r"\uff0c\u7b2c\u4e00\u6b21\u6765$")
        m = re.fullmatch(form, s)
        if not m:
            return False
        prose = m.group("prose")
        lead = (r"^" + re.escape(place) + r"\u7684\u57ce\u5899")
        verb = s[:m.start("prose")][-2:]
        if verb == "\u671b\u7740" and re.match(lead, prose):
            prose = prose[len(place) + 3:]
        return not L1Validator._VISIT_SKIP_RE.search(prose)

    @staticmethod
    def _visit_place_candidates(actor_name: str, sentences: list[str]) -> list[str]:
        """取当前章人物句首或「这就是X，第一次来」相邻的精确地点。"""
        places: list[str] = []
        for s in sentences:
            if s.startswith(actor_name):
                for m in L1Validator._VISIT_PLACE_RE.finditer(
                    L1Validator._FIRST_VISIT_MARK_RE.sub("", s)
                ):
                    tail = s[m.end():m.end() + 1]
                    head = s[:m.start()][-1:]
                    if head and L1Validator._VISIT_PLACE_RE.match(head):
                        continue
                    if tail and L1Validator._VISIT_PLACE_RE.match(tail):
                        continue
                    places.append(m.group(0))
        return places

    def _visit_history(self, session: Session, *, project_id: uuid.UUID,
                       chapter_seq: int, actor_id: uuid.UUID,
                       place: str, actor_name: str) -> object:
        rows = session.execute(
            select(Event).where(and_(Event.project_id == project_id,
                                    Event.source_chapter < chapter_seq))
            .order_by(Event.source_chapter.desc(), Event.id.desc())
        ).scalars()
        pattern = re.compile(
            r"^" + re.escape(actor_name) + r"\u5728" + re.escape(place)
            + r"\u5b8c\u6210\u4ea4\u6613$"
        )
        for ev in rows:
            participants = getattr(ev, "participants", None)
            if participants and str(actor_id) not in participants:
                continue
            for sent in self._split_visit_sentences(ev.summary or ""):
                s = sent.strip()
                if not s:
                    continue
                clauses = re.split(r"[\uff0c\uff1b]", s)
                matched = False
                residue_parts = []
                for clause in clauses:
                    c = clause.strip()
                    if c and pattern.fullmatch(c):
                        matched = True
                        residue_parts.append("\u4ea4\u6613\u5b8c\u6210")
                    else:
                        residue_parts.append(clause)
                if not matched:
                    continue
                residue = "".join(residue_parts)
                if _NEGATION_RE.search(residue) or "\u8ba1\u5212" in residue:
                    continue
                if self._VISIT_SKIP_RE.search(residue):
                    continue
                return ev
        return None

    def first_visit_check(self, session: Session, *, project_id: uuid.UUID,
                          chapter_seq: int, draft: str | None = None) -> list[Finding]:
        """明确首次来访与同一人物在该地点的历史事件矛盾时报 major（同人物肯定失忆/旧地重游豁免）。"""
        if not draft:
            return []
        rows = session.execute(
            select(Character).where(Character.project_id == project_id)
            .order_by(Character.name)
        ).scalars().all()
        findings: list[Finding] = []
        seen: set[tuple[str, str]] = set()
        for actor in rows:
            name = (getattr(actor, "name", None) or "").strip()
            if not name:
                continue
            for para in (draft or "").split("\n"):
                sentences = self._split_visit_sentences(para)
                for sent in sentences:
                    marker = self._FIRST_VISIT_MARK_RE.search(sent)
                    if not marker or not sent.startswith(name):
                        continue
                    place = self._visit_place_of(sent, marker.group(0))
                    if not place:
                        continue
                    if not self._visit_stated(sent, name, place, marker.group(0)):
                        continue
                    tail = sent[len(name):]
                    if any(other.id != actor.id and (other.name or "").strip()
                           and (other.name or "").strip() in tail for other in rows):
                        continue
                    if self._visit_explained(sentences, name):
                        continue
                    ev = self._visit_history(session, project_id=project_id,
                                             chapter_seq=chapter_seq,
                                             actor_id=actor.id, place=place,
                                             actor_name=name)
                    if ev is None:
                        continue
                    pair = (str(actor.id), place)
                    if pair in seen:
                        continue
                    seen.add(pair)
                    quote = sent if len(sent) <= 512 else sent[:512]
                    findings.append(Finding(
                        conflict_key=_key("character",
                                          f"first_visit:{actor.id}:{place}",
                                          chapter_seq),
                        conflict_type="character", severity="major",
                        scope="local", source="L1",
                        evidence=[{"chapter": ev.source_chapter, "quote": ev.summary},
                                  {"chapter": chapter_seq, "quote": quote}],
                        suggestion=f"「{name}」在第{ev.source_chapter}章已于{place}有记录，"
                                   "正文不应断言首次来访；如已失忆或旧地重游请在正文说明",
                    ))
        return findings

    def item_rule_check(self, session: Session, *, project_id: uuid.UUID,
                        chapter_seq: int, draft: str | None = None) -> list[Finding]:
        """历史已毁物品在本章被再次使用时，除非同一物品有已确认修复 Fact，判 critical。"""
        if not draft:
            return []
        destroyed: dict[str, object] = {}
        rows = session.execute(
            select(Event).where(and_(Event.project_id == project_id,
                                    Event.source_chapter < chapter_seq))
            .order_by(Event.source_chapter)
        ).scalars()
        for ev in rows:
            text = ev.summary or ""
            for clause in re.split(r"[，。；！？\n]", text):
                if not clause.strip() or _NEGATION_RE.search(clause):
                    continue
                m = _DESTROY_RE.search(clause) or _DESTROY_ALT_RE.search(clause)
                if m:
                    item = m.group(1)
                    destroyed[item] = ev
        findings: list[Finding] = []
        actor_names = tuple(
            str(n) for n in session.execute(
                select(Character.name).where(Character.project_id == project_id)
            ).scalars() if n
        )
        for item, ev in destroyed.items():
            actual = self._draft_use_quote(draft, item, actor_names)
            if not actual:
                continue
            if self._item_repair_confirmed(session, project_id=project_id,
                                           chapter_seq=chapter_seq, item=item,
                                           destroyed_chapter=ev.source_chapter):
                continue
            findings.append(Finding(
                conflict_key=_key("item_rule", item, chapter_seq),
                conflict_type="item_rule", severity="critical", scope="local", source="L1",
                evidence=[{"chapter": ev.source_chapter, "quote": ev.summary},
                          {"chapter": chapter_seq, "quote": actual}],
                suggestion=f"「{item}」已在第{ev.source_chapter}章销毁，正文不应再次使用；"
                           "若已重铸须写入已确认 Fact",
            ))
        return findings

    _FIRST_VISIT_MARK_RE = re.compile(
        r"第\s*一\s*次\s*(?:来到过|来过|来到|来|到|踏上|抵达)"
    )
    _VISIT_SKIP_RE = re.compile(
        r"不|未|没|回忆|想起|当年|曾经|打算|准备|计划|若|如果|假如"
    )
    _VISIT_PLACE_RE = re.compile("[\\u4e00-\\u9fffA-Za-z0-9]{2,24}")
    _VISIT_SENT_SPLIT_RE = re.compile(r"[\u3002\uff01\uff1f!?]")
    _VISIT_AFFIRM_RE = re.compile(r"(?:已经|先前|曾|此前)?(?:失忆|旧地重游)")
    _VISIT_AFFIRM_DENY_RE = re.compile(r"并未|没有|没|未曾|不曾|也许|或许|假装|装作|打算|并")
    _VISIT_AFFIRM_EXACT_RE = re.compile(
        r"(?:已经|已)?(?:失忆|旧地重游|故地重游|记忆丧失)"
    )

    @staticmethod
    def _split_visit_sentences(text: str) -> list[str]:
        sentences: list[str] = []
        for para in re.split(r"\n", text or ""):
            for part in L1Validator._VISIT_SENT_SPLIT_RE.split(para):
                s = part.strip()
                if s:
                    sentences.append(s)
        return sentences

    @staticmethod
    def _visit_place_of(spoken: str, marker: str) -> str:
        """从「……这就是X，第一次来」中取与「第一次」相邻的地点。"""
        idx = spoken.find(marker)
        if idx < 0:
            return ""
        prefix = spoken[:idx]
        if "\u8fd9\u5c31\u662f" in prefix:
            seg = prefix.rsplit("\u8fd9\u5c31\u662f", 1)[1].strip().strip("\uff0c,\u3002 \t")
        else:
            seg = spoken[idx + len(marker):].strip().strip("\uff0c,\u3002 \t")
        if not seg or not L1Validator._VISIT_PLACE_RE.fullmatch(seg):
            return ""
        return seg

    def __init__(self, realm_order: list[str]):
        self.realm_order = realm_order
        self.realm_pos = {r: i for i, r in enumerate(realm_order)}

    def validate(self, session: Session, *, project_id: uuid.UUID, chapter_seq: int,
                 candidates: list[MutationCandidate]) -> list[Finding]:
        findings: list[Finding] = []
        characters: dict[uuid.UUID, object] = {}

        for cand in candidates:
            if cand.kind == "relation_change":
                findings.extend(self._relation_change_ledger_check(
                    session, project_id, chapter_seq, cand))
                continue
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
            elif field in _GENERAL_STATE_FIELDS:
                findings.extend(self._old_value_ledger_check(session, project_id, chapter_seq,
                                                             str(ch_id), field, old_v, cand))

        # 战力通胀（跨章序列，不依赖候选）
        findings.extend(self.power_inflation_check(session, project_id, chapter_seq))
        # 长线债务（伏笔烂尾 / 主线停滞，不依赖候选；hint 不阻塞，§8.6 线程债务 + §7.9 伏笔治理）
        findings.extend(self.foreshadow_debt_check(session, project_id, chapter_seq))
        findings.extend(self.plot_thread_debt_check(session, project_id, chapter_seq))
        # 关系台账自洽（仅活跃行；重复/矛盾 → major 不阻塞，§7.8 关系写入语义）
        findings.extend(self.relation_ledger_check(session, project_id, chapter_seq))
        return findings

    # ---- 能力规则（样例 8，§8.4 L1 第 1 类；draft 依赖，service 编排）----
    def capability_rule_check(self, session: Session, project_id: uuid.UUID,
                              chapter_seq: int, draft: str | None = None) -> list[Finding]:
        findings: list[Finding] = []
        if not draft:
            return findings
        sent_re = re.compile(r"[^\u3002\uff01\uff1f\n]*[\u3002\uff01\uff1f]|[^\u3002\uff01\uff1f\n]+$")
        sent_spans: list[tuple[int, int]] = []
        for m in sent_re.finditer(draft):
            if m.group(0).strip():
                sent_spans.append((m.start(), m.end()))
        if not sent_spans:
            return findings
        from myink.models import CharacterState
        acts = list(session.scalars(select(Character).where(Character.project_id == project_id)))
        if not acts:
            return findings
        names_rev: dict[uuid.UUID, str] = {}
        names: dict[str, uuid.UUID] = {}
        for a in acts:
            nm = getattr(a, "name", None)
            if nm and str(nm) not in names:
                names[str(nm)] = a.id
                names_rev[a.id] = str(nm)
        known_realms = [r for r in self.realm_pos if r]
        facts = list(session.scalars(select(Fact).where(and_(
            Fact.project_id == project_id,
            Fact.category == "规则",
            Fact.confirm_status == "confirmed",
            Fact.source_chapter <= chapter_seq,
            or_(Fact.valid_from.is_(None), Fact.valid_from <= chapter_seq),
            or_(Fact.valid_to.is_(None), Fact.valid_to >= chapter_seq)))))
        facts.sort(key=lambda f: (f.source_chapter or 0, str(f.id)))
        rules: list[tuple[int, str, str, int, str]] = []
        for f in facts:
            content = str(getattr(f, "content", "") or "").strip()
            if not content or len(content) > 120:
                continue
            head = "期才可动用"
            idx = content.rfind(head)
            if idx <= 0:
                continue
            req = content[:idx]
            if req not in self.realm_pos:
                continue
            ability = ""
            tail = content
            marks = list(re.finditer(r"[\u201c\u201d\"\u300c\u300d']", content))
            if len(marks) >= 2:
                ability = content[marks[-2].end():marks[-1].start()].strip()
            else:
                m_ab = re.search(r"期才可动用(.+)$", content)
                if not m_ab:
                    continue
                ability = m_ab.group(1).strip()
                ability = re.sub(r"[。；，,！？\s]+$", "", ability)
            if not ability or len(ability) > 24:
                continue
            rules.append((self.realm_pos[req], req, ability, int(f.source_chapter or 0), content))
        names_count: dict[str, int] = {}
        for a in acts:
            nm = getattr(a, "name", None)
            if nm:
                names_count[str(nm)] = names_count.get(str(nm), 0) + 1
        names = {k: v for k, v in names.items() if names_count.get(k) == 1}
        if not rules:
            return findings
        # Registered Character.name values are the only valid actor identities;
        # build literal, longest-first alternatives so longer, Latin or
        # punctuation-bearing names are matched exactly instead of guessed.
        actor_alts = "|".join(
            re.escape(nm) for nm in sorted(names, key=lambda s: (-len(s), s)) if nm)
        actor_pat = ("(?:" + actor_alts + ")") if actor_alts else None
        use_re = re.compile(
            r"(?P<actor>" + (r"(?:\u4ed6|" + actor_alts + r")" if actor_alts else r"\u4ed6") + r")(?P<adv>不过|只有|仍是|仍为)"
            r"(?P<realm>" + "|".join(re.escape(r) for r in known_realms) + r")期，"
            r"(?:竟)?(?:施展出|施展)"
            r"(?:(?P<req>" + "|".join(re.escape(r) for r in known_realms) + r")期才可动用的)?"
            r"[\u201c\u300c\"]?(?P<ability>[^\u3002\uff01\uff1f\n\s\u201d\u300d\"，,]{2,24}?)[\u201d\u300d\"]?(?=[，,。！？；\s]|$)")
        cost_re = re.compile(
            r"(?P<actor>" + (actor_pat or r"(?!)") + r")(?:以十年寿元为代价|遭到严重反噬)"
            r"|(?P<pron>\u4ed6)(?:以十年寿元为代价|遭到严重反噬)")
        neg_seg = re.compile(r"(没有|未|不曾|未曾|无需|不用|并非)(?:遭到|遭|付出|消耗)|若|如果|想起当年|当日")
        cache: dict[uuid.UUID, tuple[str | None, int]] = {}
        for ch_id in list(names.values()):
            rows = list(session.scalars(select(CharacterState).where(and_(
                CharacterState.project_id == project_id,
                CharacterState.character_id == ch_id,
                CharacterState.field == "realm",
                CharacterState.chapter_seq <= chapter_seq,
                CharacterState.source_chapter <= chapter_seq))))
            best_seq = None
            vals: set[str] = set()
            srcs: set[int] = set()
            for r in rows:
                if r.chapter_seq is None or r.source_chapter is None:
                    continue
                vf = getattr(r, "valid_from", None)
                vt = getattr(r, "valid_to", None)
                if vf is not None and vf > chapter_seq:
                    continue
                if vt is not None and vt < chapter_seq:
                    continue
                if r.chapter_seq <= chapter_seq:
                    if best_seq is None or r.chapter_seq > best_seq:
                        best_seq = r.chapter_seq
                        vals = set()
                        srcs = set()
                    if r.chapter_seq == best_seq:
                        vals.add(str(getattr(r, "new_value", "") or ""))
                        srcs.add(int(r.source_chapter))
            if best_seq is None or len(vals) != 1:
                continue
            cur = next(iter(vals))
            if cur not in self.realm_pos:
                continue
            # Multiple eligible rows sharing the same latest known realm value do
            # not make the value ambiguous; pick a deterministic actual source.
            best_src = max(srcs)
            cache[ch_id] = (cur, best_src)
        for (req_pos, req, ability, rule_ch, rule_content) in rules:
            for i, (s_start, s_end) in enumerate(sent_spans):
                sent = draft[s_start:s_end]
                m_match = use_re.match(sent.lstrip())
                if not m_match:
                    continue
                lead = len(sent) - len(sent.lstrip())
                for m in (m_match,):
                    actor_raw = m.group("actor") or ""
                    act_id = None
                    if actor_raw in names:
                        act_id = names[actor_raw]
                    elif actor_raw == "\u4ed6" and len(acts) == 1:
                        act_id = acts[0].id
                    else:
                        continue
                    if actor_raw not in names and not actor_raw.endswith("\u4ed6"):
                        pass
                    if m.group("ability") != ability:
                        continue
                    if m.group("req") and m.group("req") != req:
                        continue
                    cur = cache.get(act_id, (None, 0))[0]
                    if cur is None or m.group("realm") != cur:
                        continue
                    cur_pos = self.realm_pos.get(cur)
                    if cur_pos is None or cur_pos >= req_pos:
                        continue
                    exempt = False
                    # Offset of the bound positive use (actor/realm/ability) inside
                    # the original sentence; use_re matched sent.lstrip().
                    use_end = lead + m.end()
                    for cm in sent_re.finditer(sent):
                        s2 = cm.group(0)
                        if s2.find(m.group(0)) < 0:
                            continue
                        core = m.group(0)
                        ability = m.group("ability") or ""
                        ab_lo = use_end - len(ability) if ability else use_end
                        for cost in cost_re.finditer(s2):
                            if cost.start() < use_end:
                                continue
                            if ability and ab_lo <= cost.start() < use_end:
                                continue
                            # The cost subject must start a clause: at position 0
                            # or after whitespace or an explicit clause
                            # delimiter. Otherwise the match is an unanchored
                            # suffix of an unknown longer actor (\u8001\u6797\u781a,
                            # XLinYan, \u5176\u4ed6) and cannot attribute cost.
                            if cost.start() > 0:
                                prev_ch = s2[cost.start() - 1]
                                if not (
                                    prev_ch.isspace()
                                    or prev_ch in "\uff0c,\uff1b;\u3002\uff01\uff1f!?\uff1a:\u3001"
                                ):
                                    continue
                            tail = s2[use_end:cost.start()]
                            if neg_seg.search(tail[-12:] or ""):
                                continue
                            who = cost.group("actor") or cost.group("pron") or ""
                            if who == actor_raw:
                                exempt = True
                            elif who == "\u4ed6":
                                # \u4ed6 is locally unambiguous unless this sentence
                                # itself introduces a different named subject.
                                bound = s2[:use_end]
                                post = s2[use_end:cost.start()]
                                competing = [
                                    nm for nm, nid in names.items()
                                    if nid != act_id and nm
                                    and (nm in post or nm in s2[cost.start():])
                                ]
                                if not competing:
                                    exempt = True
                            elif cost.group("actor") and names.get(cost.group("actor")) == act_id:
                                exempt = True
                    if exempt:
                        continue
                    finding_key = _key("power", f"{act_id}:{ability}", chapter_seq)
                    if any(
                        f.conflict_key == finding_key
                        for f in findings
                        if getattr(f, "conflict_type", None) == "power"
                    ):
                        continue
                    findings.append(Finding(
                        conflict_key=_key("power", f"{act_id}:{ability}", chapter_seq),
                        conflict_type="power", severity="critical", scope="local", source="L1",
                        evidence=[
                            {"chapter": chapter_seq, "quote": sent.strip()},
                            {"chapter": rule_ch, "quote": rule_content},
                            {"chapter": cache.get(act_id, (None, 0))[1] or 0, "quote": f"{names_rev.get(act_id, '')} 台账境界 {cur}"},
                        ],
                        suggestion=f"{ability} 需 {req}期方可动用，当前台账为 {cur}期；需补真实代价或改回合规境界",
                    ))
                    break
        return findings
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

    # ---- 关系台账自洽（样例 17/22 台账侧 + 新增样例，§7.8）----
    def relation_ledger_check(self, session: Session, project_id: uuid.UUID,
                              chapter_seq: int) -> list[Finding]:
        """活跃关系台账自洽（仅 valid_to IS NULL）：

        - 重复活跃：同 (source_id, target_id, relation_type) ≥2 条活跃 → 当前关系不可判定；
        - 矛盾活跃：同 (source_id, target_id) 存在 ≥2 种不同 relation_type 活跃 → 敌/盟并存。
        纯结构不变量（非阈值/语义猜测），合法数据 0 误报：persist 关闭修复保证新写入不产生；
        demo 关系表为空默认不触发。major/structural：报告 + 进 revise 上下文，不阻塞（§6.12）。
        """
        findings: list[Finding] = []
        relations = repo.get_relations(session, project_id)
        if not relations:
            return findings  # 空表廉价跳过
        by_pair: dict[tuple[uuid.UUID, uuid.UUID], list] = {}
        for r in relations:
            by_pair.setdefault((r.source_id, r.target_id), []).append(r)
        for (src, tgt), rows in by_pair.items():
            by_type: dict[str, list] = {}
            for r in rows:
                by_type.setdefault(r.relation_type, []).append(r)
            for rtype, typed in by_type.items():  # 重复活跃
                if len(typed) < 2:
                    continue
                chs = ",".join(str(r.source_chapter) for r in typed)
                findings.append(Finding(
                    conflict_key=_key("relation", f"dup:{src}:{tgt}", chapter_seq),
                    conflict_type="relation", severity="major", scope="structural", source="L1",
                    evidence=[{"chapter": chapter_seq,
                               "quote": f"关系 {src}→{tgt} 存在 {len(typed)} 条活跃 {rtype}（第 {chs} 章写入），当前关系不可判定"}],
                    suggestion="台账重复活跃：合并/关闭至一条（persist 关闭修复已防新增，存量人工收口）",
                ))
            if len(by_type) >= 2:  # 矛盾活跃
                kinds = " + ".join(f"{t}×{len(r)}" for t, r in by_type.items())
                findings.append(Finding(
                    conflict_key=_key("relation", f"con:{src}:{tgt}", chapter_seq),
                    conflict_type="relation", severity="major", scope="structural", source="L1",
                    evidence=[{"chapter": chapter_seq,
                               "quote": f"关系 {src}→{tgt} 同时活跃 {kinds}，敌/盟语义互相矛盾"}],
                    suggestion="台账矛盾活跃：确定当前唯一关系类型并关闭其余行（§7.8）",
                ))
        return findings

    # ---- 桥段重复向量近邻（样例 14，阴性 32 对照，§8.6；draft 依赖故由 service 编排）----
    def bridge_repeat_check(self, session: Session, *, project_id: uuid.UUID,
                            chapter_seq: int, candidates: list[MutationCandidate],
                            draft: str | None = None) -> list[Finding]:
        """当前章事件候选摘要 vs 历史事件向量近邻 → 疑似偷懒重复桥段。

        - 命中判据：cosine distance < _REPEAT_DIST_THRESHOLD 且历史事件章距 >= _REPEAT_MIN_GAP；
        - 呼应豁免（样例 32）：draft 或候选摘要含呼应标记词 → 整章/该候选跳过（宁缺毋滥）；
        - 每章至多 1 条 hint（style/local），append 后即出即止；
        - 加分项：embedder/向量不可用一律静默跳过（try/except 降级，不阻塞生成，§6.12）。
        """
        findings: list[Finding] = []
        try:
            if draft and _has_callback_marker(draft):
                return findings  # 本章含呼应意图 → 整章豁免（样例 32）
            ev_cands = [c for c in candidates
                        if c.kind == "event" and isinstance(c.payload, dict) and c.payload.get("summary")]
            if not ev_cands:
                return findings
            ev_cands = sorted(ev_cands, key=lambda c: c.confidence, reverse=True)[:_REPEAT_QUERY_CAP]
            vecs = get_embedder().encode([c.payload["summary"] for c in ev_cands])  # 一次批量前向
            for cand, emb in zip(ev_cands, vecs):
                summary = cand.payload["summary"]
                if _has_callback_marker(summary):
                    continue  # 候选摘要自带呼应意图
                hits = PgvectorStore().search(session, project_id=project_id, level="event",
                                              embedding=emb, top_k=_REPEAT_TOP_K)
                if not hits:
                    continue  # 无向量数据 → 跳过
                rows = session.execute(
                    select(Event).where(Event.id.in_([sid for sid, _ in hits]))
                ).scalars().all()
                by_id = {e.id: e for e in rows}
                for sid, dist in hits:
                    ev = by_id.get(sid)
                    if ev is None or ev.source_chapter > chapter_seq - _REPEAT_MIN_GAP:
                        continue  # 章距太近：正常情节连续性，非偷懒重复
                    if dist >= _REPEAT_DIST_THRESHOLD:
                        continue
                    findings.append(Finding(
                        conflict_key=_key("style", f"bridge:{str(sid)}", chapter_seq),
                        conflict_type="style", severity="hint", scope="local", source="L1",
                        evidence=[{"chapter": chapter_seq,
                                   "quote": f"本章事件「{summary[:40]}」与第 {ev.source_chapter} 章事件"
                                            f"「{ev.summary[:40]}」高度相似（余弦距离 {dist:.3f}）"}],
                        suggestion="疑似桥段偷懒重复：若为刻意呼应请补意图/差异，否则改写桥段（§8.6）",
                    ))
                    return findings  # 每章至多 1 条，即出即止（宁缺毋滥）
        except Exception as exc:
            logger.warning("桥段重复向量近邻失败，跳过（加分项不阻塞）: %s", exc)
        return findings

    # ---- 句式禁令（任何题材；出现即 critical，不按词频统计）----
    def prose_ban_check(self, session: Session, *, project_id: uuid.UUID,
                        chapter_seq: int, draft: str | None = None) -> list[Finding]:
        """「不是…」紧跟「是…」（含拆成两句的「不是…。是…」）或连续排比出现一次即 style/critical。"""
        del session, project_id
        if not draft:
            return []
        quotes = _prose_ban_quotes(draft)[:3]
        if not quotes:
            return []
        return [Finding(
            conflict_key=_key("style", "prose-ban", chapter_seq),
            conflict_type="style", severity="critical", scope="local", source="L1",
            evidence=[{"chapter": chapter_seq, "quote": quote} for quote in quotes],
            suggestion="删掉「不是…是…」和连续排比，改成直接叙述",
        )]

    def prose_hygiene_check(self, session: Session, *, project_id: uuid.UUID,
                            chapter_seq: int, draft: str | None = None) -> list[Finding]:
        """正文卫生四则。

        章节号指称是正确性缺陷（角色不知道自己在第几章）→ critical，触发修订；
        说教词 / 连续「了」字 / 段落过长是文体提示 → hint，只记录不阻塞。
        """
        del session, project_id
        if not draft:
            return []
        findings: list[Finding] = []

        refs = _chapter_refs(draft)
        if refs:
            findings.append(Finding(
                conflict_key=_key("style", "chapter-ref", chapter_seq),
                conflict_type="style", severity="critical", scope="local", source="L1",
                evidence=[{"chapter": chapter_seq, "quote": "、".join(refs)}],
                suggestion="正文别写章节号，改成自然指代：「那天晚上」「仓库出事那次」",
            ))

        sermons = _sermon_words(draft)
        if sermons:
            findings.append(Finding(
                conflict_key=_key("style", "sermon", chapter_seq),
                conflict_type="style", severity="hint", scope="local", source="L1",
                evidence=[{"chapter": chapter_seq, "quote": "、".join(sermons)}],
                suggestion="删掉说教词，让读者自己从情节里判断",
            ))

        longest = _max_consecutive_le(draft)
        if longest >= _CONSECUTIVE_LE_MIN:
            findings.append(Finding(
                conflict_key=_key("style", "consecutive-le", chapter_seq),
                conflict_type="style", severity="hint", scope="local", source="L1",
                evidence=[{"chapter": chapter_seq, "quote": f"连续 {longest} 句含「了」"}],
                suggestion="保留最有力的一个「了」，其余改成无「了」句式",
            ))

        longs = _long_paragraphs(draft)
        if len(longs) >= _LONG_PARAGRAPH_MIN:
            findings.append(Finding(
                conflict_key=_key("style", "long-paragraph", chapter_seq),
                conflict_type="style", severity="hint", scope="local", source="L1",
                evidence=[{"chapter": chapter_seq,
                           "quote": f"{len(longs)} 段超过 {_LONG_PARAGRAPH_CHARS} 字，最长 {max(longs)} 字"}],
                suggestion="长段落拆成 3-5 行的短段，在动作切换或情绪节点处断开",
            ))

        return findings

    # ---- realm ----
    def _realm_checks(self, session: Session, project_id: uuid.UUID, chapter_seq: int,
                      ch_id: str, old_v: str | None, new_v: str, cand: MutationCandidate) -> list[Finding]:
        findings: list[Finding] = []
        # ch_id 是 extract 归一化后的 canonical id（uuid str），按主键查
        from myink.models import Character
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

    # ---- 候选 old_value-vs-台账（样例 16/20/21 确定性窄脚印）----
    def _old_value_ledger_check(self, session: Session, project_id: uuid.UUID,
                                chapter_seq: int, ch_id: str, field: str, old_v: object,
                                cand: MutationCandidate) -> list[Finding]:
        """extract 候选 old_value vs 台账当前值（至 chapter_seq-1）：非空且不符 → 疑似误读台账。

        只比非空 old_value；台账该字段当前值为空/缺席（repo.get_character_state 至 seq-1）
        → 跳过（首写不变量，fresh 书 0 误报）。正文-台账语义比对（"无过渡推翻"）留 L2。
        """
        findings: list[Finding] = []
        if not old_v:
            return findings
        ledger = repo.get_character_state(session, project_id, uuid.UUID(ch_id), chapter_seq - 1)
        current = (ledger.get(field) or "").strip()
        if not current:
            return findings  # 台账无当前值（首写）即跳过
        if str(old_v).strip() != current:
            findings.append(Finding(
                conflict_key=_key("character_state", f"{ch_id}:{field}", chapter_seq),
                conflict_type="character_state", severity="minor", scope="local", source="L1",
                evidence=[{"chapter": cand.source_chapter,
                           "quote": f"候选 old_value={old_v!r} 与台账当前 {field}={current!r} 不符（抽取疑似误读注入快照）"}],
                suggestion="extract 读到旧台账快照：核对 recall 注入的状态快照，或重新抽取该字段",
            ))
        return findings

    # ---- 候选 relation_change old_value-vs-台账（样例 17/22 确定性窄脚印）----
    def _relation_change_ledger_check(self, session: Session, project_id: uuid.UUID,
                                      chapter_seq: int, cand: MutationCandidate) -> list[Finding]:
        """候选 relation_change old_value vs 台账当前有序对类型：非空且不符 → 疑似误读台账。

        只比非空 old_value；台账该有序对无活跃行 / 有歧义（>1 活跃行，重复/矛盾交
        relation_ledger_check 兜底）→ 跳过（首写/歧义不误报）。old_value == 台账 → 跳过，
        正文-台账语义比对（"无变更却表现相反"）留 L2。
        """
        findings: list[Finding] = []
        p = cand.payload
        old_v = (p.get("old_value") or "").strip()
        if not old_v:
            return findings
        src = p.get("source_id")
        tgt = p.get("target_id")
        if not src or not tgt:
            return findings
        try:
            current = repo.get_relation_current_type(session, project_id,
                                                     uuid.UUID(str(src)), uuid.UUID(str(tgt)))
        except ValueError:
            return findings
        if not current:
            return findings  # 台账无活跃关系或歧义（None）→ 跳过
        if old_v != current:
            findings.append(Finding(
                conflict_key=_key("relation", f"{src}:{tgt}", chapter_seq),
                conflict_type="relation", severity="minor", scope="local", source="L1",
                evidence=[{"chapter": cand.source_chapter,
                           "quote": f"候选 old_value={old_v!r} 与台账当前关系 {current!r} 不符（抽取疑似误读注入快照）"}],
                suggestion="extract 读到旧台账快照：核对 recall 注入的关系快照，或重新抽取该关系变更",
            ))
        return findings

    # ---- 战力通胀（跨章，样例 11）----
    def power_inflation_check(self, session: Session, project_id: uuid.UUID,
                              chapter_seq: int) -> list[Finding]:
        findings: list[Finding] = []
        for char in repo.get_all_characters(session, project_id):
            # 该角色 realm 台账序列（近窗口）
            from myink.models import CharacterState
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
                    evidence=[{"chapter": chapter_seq, "quote": f"{char.name} 连续 {len(seq)} 章每章升境界: {' → '.join(seq)}"}],
                    suggestion="战力通胀强信号：连续数章无铺垫升级；若为奇遇需补代价说明，否则降为待审计",
                ))
        return findings

    # ---- 阵营敌对（样例 2，阴性样例 40 守卫，§8.4 L1 第 1 类）----
    def faction_check(self, session: Session, *, project_id: uuid.UUID,
                      chapter_seq: int, draft: str | None = None) -> list[Finding]:
        """本章 draft 中活跃敌对关系双名共现 + 协作标记 → faction/critical/structural。

        - 命中判据：relation_type=hostile 的活跃关系对；双名（含别名）共现于 draft；任一协作标记在 draft；
        - 守卫（样例 40）：临时盟约覆盖本章（任一带 valid_to 的非 hostile 行 valid_from<=ch<=valid_to，
          或永久有效的非 hostile 行）→ 跳过——合法联手须先落 relation 带 valid_to（spec 误报控制）；
          永久非敌对/同对歧义交 relation_ledger_check 兜底，防双报；
        - 每章至多 1 条（宁缺毋滥 §8.8），即出即止；降级：无 draft/异常一律跳过不阻塞（§6.12）。
        """
        findings: list[Finding] = []
        try:
            if not draft:
                return findings
            chars = {c.id: c for c in repo.get_all_characters(session, project_id)}
            if not chars:
                return findings
            hostile = [r for r in repo.get_relations(session, project_id)
                       if r.relation_type == "hostile"]
            for r in hostile:
                a, b = chars.get(r.source_id), chars.get(r.target_id)
                if a is None or b is None:
                    continue
                if not _names_present(draft, a) or not _names_present(draft, b):
                    continue
                if not any(m in draft for m in _FACTION_COOP_MARKERS):
                    continue
                if _temp_alliance_covers(session, project_id, r.source_id, r.target_id, chapter_seq):
                    continue  # 合法联手已落临时盟约（样例 40）
                findings.append(Finding(
                    conflict_key=_key("faction", f"{r.source_id}:{r.target_id}", chapter_seq),
                    conflict_type="faction", severity="critical", scope="structural", source="L1",
                    evidence=[{"chapter": chapter_seq,
                               "quote": f"敌对关系（{a.name} ↔ {b.name}）本章并肩协作，无临时盟约记录"}],
                    suggestion="阵营敌我矛盾：敌对双方并肩协作须先在 relations 落临时盟约（带 valid_to），否则冲突（§8.4 第 1 类）",
                ))
                return findings  # 每章至多 1 条
        except Exception as exc:
            logger.warning("阵营敌对检查失败，跳过（加分项不阻塞）: %s", exc)
        return findings
