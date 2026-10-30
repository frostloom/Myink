"""Original, versioned quality resources; researched sources: docs/WRITING-QUALITY-SOURCES.md."""

from myink.chapter_craft import CRAFT_LESSON
from myink.additional_style_presets import ADDITIONAL_STYLE_PRESETS

SCENE_RULES = """【场景因果与有效推进】
先遵守作品设定、章节计划、题材承诺、作者文风和人物当前所知；以下是创作建议，不是额外情节或硬性指标。
规划或落笔前，明确人物眼前想办成什么、遇到怎样的阻力、能作哪些选择，以及选择会改变什么。把重要结果接回已经建立的行动、信息或规则，不把事件简单按先后排列。
场景中的动作、环境和心理描写应帮助理解处境、暴露人物或影响选择；细节可以营造氛围和留白，不必件件埋伏笔，也不要靠装饰动作填充篇幅。
对转折交代必要的知识来源、条件和代价。兑现落在具体结果上，不用反复惊叹或旁白宣布人物厉害来代替结果；不能为了制造推进擅改既有事实或凭空发放能力。
允许静场、犹豫、日常和关系变化成为有效进展；不要强迫每段发生冲突。修订只处理本次审稿定位的问题，保留有效情节和人物声音。"""

DIALOGUE_RULES = """【人物对白与潜台词】
对白服从当前人物关系、时代语境、知识边界和作者文风。先想人物此刻要争取、试探、隐瞒、拒绝或请求什么，再写他会怎样说；不必把每个隐藏目的解释给读者。
通过人物选择谈什么、如何称呼对方、怎样回应压力或回避问题区分声音；同一人物可随处境改变语气，不靠给每个人固定口头禅来区分，也不要求句句机锋。
双方已知的信息不借问答重复讲给读者；确需解释时，让问题、误解、利益或行动需要它。允许简短直接的日常对话，不强制每句话同时完成多项任务。
在必要处用人物与现场相关的停顿、行动或感知承接对话，别反复插入端杯、眯眼、挑眉等可任意替换的动作。对白后的关系、认识或下一步行动若有变化，让读者从内容中察觉，不再旁白总结一次。"""

GENRE_PACING = """【按题材组织节奏与兑现】
以本书已经选定的主辅题材、读者承诺和作者节奏要求为准，先判断这一段的叙事用途，再使用相应方法；不把商业连载模板套在所有小说上。
升级、冒险和强情节连载：让目标、限制与回报可理解，能力展示要有已建立的依据；章尾可以落在行动带来的新局面、选择或后果上，不用无关联的突发事件反复吊胃口。
悬疑、推理和规则题材：线索与人物认知须有来源，区分误导和隐瞒叙述；推进信息差时保留公平判断空间，不让人物凭作者知识提前得出答案。
关系、情感和人物题材：关注信任、欲望、边界与关系中的细小位移；保留停顿、心理层次和回味，不强行插入打脸、反转或夸张宣言。
现实、日常和偏文学叙事：具体处境、人物选择与后果本身可以提供张力；允许克制、含混或开放的收束，不强制温暖结局、第一人称、短句或每章悬崖。
以上方向可以交叉，但不得覆盖主题材的硬约束或作者设定。静场与开放收束仍须满足既有章节计划和收尾要求，可由关系、认知或选择变化体现推进；短篇应完成方案承诺的终局，不能把未写完当作留白。篇幅、章数和输出格式继续服从本次任务。"""

REVIEW_POLICY = """
审核只报告原文有证据、确实影响理解或违背本书既定要求的问题，定位句段并给出局部改法。不要把这些建议变成情节配额或一刀切门禁；一般表达与节奏建议保持 minor/hint，不为纯润色触发 replan，不把模型自评分当质量证明。"""


def quality_resources():
    source = 'writing_quality_resources.py; docs/WRITING-QUALITY-SOURCES.md (MIT reference concepts; original adaptation)'
    return [
        dict(id='genre-rule:craft-realism-suspense', name='现实与悬疑·表达落笔方法', kind='genre_rule', source=source,
             body={'genre_ids': ['xianshi', 'xuanyi-naodong'],
                   'roles': {'writer': CRAFT_LESSON, 'audit': CRAFT_LESSON + REVIEW_POLICY}}),
        dict(id='writing-rule:scene-causality', name='场景因果与有效推进', kind='writing_rule', source=source,
             body={'roles': {'planner': SCENE_RULES, 'writer': SCENE_RULES, 'audit': SCENE_RULES + REVIEW_POLICY}}),
        dict(id='expression-rule:dialogue', name='人物对白与潜台词', kind='expression_rule', source=source,
             body={'roles': {'writer': DIALOGUE_RULES, 'audit': DIALOGUE_RULES + REVIEW_POLICY}}),
        dict(id='writing-rule:genre-pacing', name='题材节奏与承诺兑现', kind='writing_rule', source=source,
             body={'roles': {'planner': GENRE_PACING, 'writer': GENRE_PACING, 'audit': GENRE_PACING + REVIEW_POLICY}}),
    ]


# Profiles do not fix a book POV or world facts. These are selectable choices,
# not replacements for a project's existing private profile or selected genre.
GENERAL_STYLE_PRESETS = [
    dict(id='natural-narration', name='自然叙事（通用）', genre='通用', style_profile={
        'narrative_voice': '叙述清楚、自然、有分寸，沿用作品的视角和叙述距离，不刻意卖弄辞藻。',
        'sentence_style': '句子长短跟随信息与情绪；重点说清，必要处留白，不机械拆成短句。',
        'dialogue_style': '台词贴近人物身份和关系，允许回避、停顿与直说，避免人人同一种腔调。',
        'scene_description': '选择人物会注意到、能让处境变具体的细节，不堆砌无关景物。',
        'pacing': '行动、对话与内心感受自然交替，重要选择留出空间，重复解释适度压缩。',
        'emotional_expression': '情绪由人物处境、感受和行为共同承载，保留有效的心理描写，不反复替读者下结论。',
    }),
    dict(id='brisk-narration', name='明快叙事（情节向）', genre='通用', style_profile={
        'narrative_voice': '清晰利落地跟随人物行动，先让读者看懂目标、阻力与选择，保留人物个性。',
        'sentence_style': '关键动作与信息表达直接，复杂因果交代完整；不以删掉必要细节换取快感。',
        'dialogue_style': '交锋、交易和协作围绕具体诉求展开，台词有回应，不用长篇独白反复解说。',
        'transitions': '以行动的结果、人物的决定或明确的时空变化衔接场景。',
        'pacing': '围绕本章计划分配轻重，关键兑现写实，过场适度收紧；需要蓄势和喘息时放慢。',
        'distinctive_habits': '追求可读的推进，不把每段都写成反转，不用围观惊叹代替实际后果。',
    }),
    dict(id='character-narration', name='细腻叙事（人物向）', genre='通用', style_profile={
        'narrative_voice': '贴近人物的感受与判断，细腻但不替人物宣布结论，保留矛盾、犹疑和叙述距离。',
        'dialogue_style': '注意称呼、停顿、话题选择与没有说出口的部分，直白表达也应符合人物处境。',
        'scene_description': '用人物当下可感知的具体细节连接环境与内心，不让景物成为情绪标签。',
        'emotional_expression': '允许有新信息的心理描写，避免把同一情绪换几个比喻重复说明。',
        'pacing': '在关系和选择改变处停留，日常段落也保持清楚的处境；收束留余味而不制造空洞金句。',
        'lexicon_tendency': '措辞准确，修辞服务人物经验与当前场景；不规定抒情密度或强迫华丽表达。',
    }),
]


# Original examples for an optional life-oriented voice, not a global replacement.
_LIFE_NARRATION_EXCERPTS = [
    """“你把收条给我。”
老何翻了翻上衣口袋，又去摸裤兜。阿棠没催，把门边那只椅子拖过来坐着。门外的三轮车已经发动了，突突响。
“明天拿给你行不行？”
“你上回也是这么说的。”
老何往外看了一眼，把手从口袋里抽出来：“那你跟我走一趟。”""",
    """我到的时候，门口只剩一把锁。邻居说人刚走，我说我知道，抬手又敲了两下。她抱着菜篮子没回屋，站在台阶下面看我。我把揣了一路的信塞回去，问她去镇上的末班车还有没有。
“得跑。”
我下了两级台阶，想起什么，又折回来：“她没说什么时候回来？”""",
]

GENERAL_STYLE_PRESETS.append(dict(
    id='life-narration', name='生活叙事（自然对白）', genre='现实与日常',
    style_profile={
        **GENERAL_STYLE_PRESETS[0]['style_profile'],
        'reference_excerpts': list(_LIFE_NARRATION_EXCERPTS),
    },
))


GENERAL_STYLE_PRESETS.extend(ADDITIONAL_STYLE_PRESETS)
