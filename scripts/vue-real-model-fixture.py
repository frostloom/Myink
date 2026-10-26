"""Loopback-only OpenAI HTTP/SSE fixture for real Vue/API/queue/worker acceptance.

This is an actual HTTP service, never monkeypatches application providers. The API and
worker use an explicit HTTP proxy for fixture.invalid; all other proxy targets fail.
"""
from __future__ import annotations
import argparse, json, re, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

state = {'extract_card': False, 'stream_delay': 0.04, 'short_revise': False}
lock = threading.Lock()
requests = []

def j(value): return json.dumps(value, ensure_ascii=False)
def number(text, label, default):
    found = re.search(label + r'[^\d]{0,12}(\d+)', text)
    return int(found.group(1)) if found else default

def body(seq=1, revised=False):
    lead = '林砚把账册交给渡客，指尖压住最后一页。' if not revised else '林砚重新核对账册，补上渡客缺失的证词。'
    return lead + '\n\n' + '\n'.join(f'第{i}份证词写清了船只去向。老人展开纸条，指着渡口的编号{i}，解释那一天发生的交接。林砚记下细节，再到船边逐项确认，终于找到了能够相互印证的线索。' for i in range(1, 12)) + '\n他将证据放在众人面前，推开仓门，看见了失踪的木箱。'

def response_for(payload):
    messages = payload.get('messages', [])
    system = '\n'.join(str(m.get('content', '')) for m in messages if m.get('role') == 'system')
    text = '\n'.join(str(m.get('content', '')) for m in messages)
    seq = number(text, r'第', 1)
    if '设定骨架草稿' in system:
        return 'setup', j({'title':'隔离渡口长篇','world_rules':{'规则':'人物调查必须依靠证据'},'hard_constraints':['不可瞬间移动'],'characters':[{'name':'林砚','role':'主角','realm_cap':'金丹','personality':'审慎'}],'forces':[{'name':'渡口商会','stance':'中立'}],'locations':[{'name':'渡口'}]})
    if '整书规划 Agent' in system:
        count = number(text, r'大致章节数】', 50)
        n = number(text, r'建议约', 2)
        volumes=[]; start=1
        for v in range(n):
            end = count*(v+1)//n
            stages=[]; stage_start=start
            while stage_start<=end:
                stage_end=min(end,stage_start+29)
                stages.append({'stage_seq':len(stages)+1,'name':'追查证据','chapter_start':stage_start,'chapter_end':stage_end,'goal':'证词获得独立印证','beats':['林砚在渡口取得账册','渡客在商会对证','众人公开船只去向']});stage_start=stage_end+1
            volumes.append({'volume_seq':v+1,'title':f'第{v+1}卷渡口','theme':'证据与选择','goal':'公开一组完整证据','key_results':['找到账册','证人到场','公开船只去向'],'end_event':'证词公开','chapter_start':start,'chapter_end':end,'stages':stages});start=end+1
        return 'outline',j({'objective':'查清失踪木箱的去向并公开证据','volumes':volumes})
    if '你在和作者一起把一篇短篇聊成形' in system:
        return 'short_creation',j({'reply':'渡口的证据与选择已经清楚，可以确认方案。','card':{'working_title':'隔离渡口短篇','genre':'现实','direction':'渡客寻找木箱','protagonist_pressure':'证词将被销毁','conflict_core':'商会阻止公开','emotional_payoff':'证人获得保护','plot_sketch':'取得账册，保护证人，公开证据','chapter_count':2,'chars_per_chapter':1000}})
    if '短篇方案 Agent' in system:
        count=number(text,r'【章数】',2)
        return 'short_plan',j({'objective':'木箱交还失主并公开证词','volumes':[{'volume_seq':1,'title':'全篇渡口','theme':'守信','goal':'公开证据','chapter_start':1,'chapter_end':count,'chapters':[{'chapter_seq':i,'title':f'渡口证词{i}','goal':f'公开第{i}份证据','key_scene':'林砚在渡口核对账册','character_action':'林砚保护证人','escalation_or_payoff':'商会承认证据','hook':'木箱去向被揭开'} for i in range(1,count+1)]}]})
    if '短篇审纲 Agent' in system: return 'short_plan_review', j({'verdict':'pass','reason':'每章都有明确动作和终局'})
    if any(k in system for k in ['短篇写作 Agent','短篇改稿 Agent','短篇补写 Agent']):
        count=number(text,r'依次输出这',number(text,r'章数',2))
        markers=re.findall(r'=== CHAPTER (\d+) CONTENT ===',text)
        if markers: count=max(map(int,markers))
        revised='短篇改稿 Agent' in system
        return ('short_revise' if revised else 'short_write'), '\n\n'.join(f'=== CHAPTER {i} CONTENT ===\n{body(i,revised)}' for i in range(1,count+1))
    if '短篇审稿 Agent' in system:
        with lock:
            revise=state['short_revise'];state['short_revise']=False
        return 'short_review',j({'verdict':'revise' if revise else 'pass','issues':['补全证据交接'] if revise else [],'suggestions':['写清账册如何交到证人手中'] if revise else []})
    if '出场人物 Agent' in system: return 'cast',j({'cast':['林砚'],'locations':['渡口']})
    if '批次规划 Agent' in system:
        count=number(text,r'接下来',3)
        return 'batch_plan',j({'chapters':[{'goal':f'公开证据{i}','outline_advance':'账册线索推进'} for i in range(count)]})
    if '【规划 Agent】' in system:
        return 'plan',j({'goals':['核对渡口账册'],'scenes':[{'location_id':'渡口','participants':['林砚'],'goal':'取得证据'}],'characters':[{'character_id':'林砚','expected_state':{}}],'hooks_to_plant':[],'hooks_to_resolve':[],'expected_events':['林砚取得账册'],'hard_constraints':[],'transition':{'mode':'opening','anchor_quote':'','pending_action':'','opening_beat':'核对证据','bridge':''}})
    if '记忆抽取' in system:
        with lock:
            card=state['extract_card'];state['extract_card']=False
        candidates=[{'kind':'event','source_chapter':seq,'confidence':0.95,'payload':{'summary':'林砚在渡口取得账册','participants':['林砚'],'source_chapter':seq,'confidence':0.95}}]
        if card:candidates.append({'kind':'character_card','source_chapter':seq,'confidence':0.95,'payload':{'name':'舟客','realm_cap':'金丹','personality':'守信','role':'证人'}})
        return 'extract',j({'candidates':candidates})
    if '修订 Agent' in system: return 'revise','=== CONTENT ===\n'+body(seq,True)+'\n=== RESPONSES ===\n[]'
    if '审核中枢' in system: return 'audit',j({'verdict':'pass','findings':[],'reasons':['符合计划'],'confidence':0.95})
    if '章节摘要' in system: return 'summarize',j({'summary':'林砚核对渡口账册，取得可公开的证据。'})
    if '复盘 Agent' in system:return 'reflexion',j({'lessons':[]})
    if '全局审计 Agent' in system:return 'global_audit',j({'findings':[]})
    if '一致性' in system and payload.get('response_format'):return 'validator',j({'findings':[]})
    if '写作 Agent' in system:return 'write','=== CONTENT ===\n'+body(seq)
    return 'unknown',j({'ok':True})

class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def log_message(self,*args): pass
    def do_CONNECT(self): self.send_error(403,'Only fixture HTTP is allowed')
    def send_json(self,data,status=200):
        raw=j(data).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        p=urlsplit(self.path).path
        if p=='/_receipt':return self.send_json({'requests':requests,'count':len(requests),'state':state})
        if p.endswith('/models'):return self.send_json({'object':'list','data':[{'id':'fixture-local','object':'model','owned_by':'isolated-test'}]})
        self.send_json({'error':'fixture_unknown'},404)
    def do_POST(self):
        target=urlsplit(self.path)
        if target.hostname and target.hostname!='fixture.invalid':return self.send_json({'error':'non_fixture_target_denied'},403)
        raw=self.rfile.read(int(self.headers.get('Content-Length','0')));data=json.loads(raw)
        if target.path=='/_control':
            with lock:
                for key in state:
                    if key in data:state[key]=data[key]
            return self.send_json({'ok':True})
        if not target.path.endswith('/chat/completions'):return self.send_json({'error':'fixture_unknown'},404)
        kind,content=response_for(data)
        record={'kind':kind,'stream':bool(data.get('stream')),'model':data.get('model'),'at':time.time(),'chars':len(content)}
        with lock:requests.append(record);args.log.write_text(j({'requests':requests}))
        identity=f'chatcmpl-fixture-{len(requests)}'
        usage={'prompt_tokens':100,'completion_tokens':200,'total_tokens':300}
        if not data.get('stream'):return self.send_json({'id':identity,'object':'chat.completion','created':int(time.time()),'model':'fixture-local','choices':[{'index':0,'message':{'role':'assistant','content':content},'finish_reason':'stop'}],'usage':usage})
        self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Connection','close');self.end_headers()
        try:
            for index in range(0,len(content),65):
                chunk={'id':identity,'object':'chat.completion.chunk','created':int(time.time()),'model':'fixture-local','choices':[{'index':0,'delta':{'content':content[index:index+65]},'finish_reason':None}]}
                self.wfile.write(('data: '+j(chunk)+'\n\n').encode());self.wfile.flush();time.sleep(float(state['stream_delay']))
            finish={'id':identity,'object':'chat.completion.chunk','created':int(time.time()),'model':'fixture-local','choices':[{'index':0,'delta':{},'finish_reason':'stop'}],'usage':usage}
            self.wfile.write(('data: '+j(finish)+'\n\ndata: [DONE]\n\n').encode());self.wfile.flush()
        except (BrokenPipeError,ConnectionResetError):pass
        self.close_connection=True

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=28120);parser.add_argument('--log',type=Path,default=Path('/tmp/myink-vue-model-fixture-log.json'));args=parser.parse_args()
    print(f'fixture HTTP listening on 127.0.0.1:{args.port}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
