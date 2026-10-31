// Explicit loopback-only synthetic data; never a production/model transport.
import fs from 'node:fs'
import http from 'node:http'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
export const data = JSON.parse(fs.readFileSync(fileURLToPath(new URL('../vue/src/pages/admin/pi-console.fixture.json', import.meta.url)), 'utf8'))
export const token='synthetic-pi-console-browser-admin'
export function fixtureServer(receipt) {
 const dist=path.resolve(process.env.MYINK_BROWSER_DIST??fileURLToPath(new URL('../dist-vue/',import.meta.url)))
 const state={phase:'awaiting_approval',operation:null,unavailable:false,forbidden:false,decisions:[]}
 const server=http.createServer(async(req,res)=>{
  const url=new URL(req.url,'http://127.0.0.1')
  const send=(status,body)=>{res.writeHead(status,{'Content-Type':'application/json','Cache-Control':'no-store'});res.end(JSON.stringify(body))}
  if(url.pathname.startsWith('/api/')){
   const key=`${req.method} ${url.pathname}`;receipt.requests.push(key)
   if(!['GET /api/v1/auth/session','GET /api/v1/admin/pi/status','GET /api/v1/admin/pi/runs','GET /api/v1/admin/pi/events','GET /api/v1/admin/pi/daily','POST /api/v1/admin/pi/decisions',`GET /api/v1/admin/pi/operations/${state.operation?.request_id}`].includes(key)){receipt.unknownApi.push(key);send(500,{detail:'unhandled_fixture_endpoint'});return}
   if(req.headers.authorization!==`Bearer ${token}`){send(401,{detail:'UNAUTHORIZED'});return}
   if(url.pathname==='/api/v1/auth/session'){send(200,{token,user_id:'admin',username:'管理员',tier:'vip',role:'admin',expires_in:3600});return}
   if(state.forbidden){send(403,{detail:'FORBIDDEN'});return}
   if(state.unavailable){send(503,{detail:'PI_CONSOLE_UNAVAILABLE'});return}
   if(key==='GET /api/v1/admin/pi/status'){send(200,{...data.status,phase:state.phase,latest_operation:state.operation});return}
   if(key==='GET /api/v1/admin/pi/runs'){send(200,data.runs);return}
   if(key==='GET /api/v1/admin/pi/events'){send(200,data.events);return}
   if(key==='GET /api/v1/admin/pi/daily'){send(200,{...data.daily,day:url.searchParams.get('day')});return}
   if(key==='POST /api/v1/admin/pi/decisions'){
    const chunks=[];for await(const chunk of req)chunks.push(chunk)
    const packet=JSON.parse(Buffer.concat(chunks).toString('utf8'));state.decisions.push(packet)
    state.operation={...data.operation,...packet,status:packet.decision==='defer'?'deferred':'queued'};send(202,state.operation);return
   }
   send(200,state.operation);return
  }
  let file
  try{file=path.resolve(dist,'.'+decodeURIComponent(url.pathname))}catch{res.writeHead(400);res.end();return}
  if(file!==dist&&!file.startsWith(dist+path.sep)){res.writeHead(403);res.end();return}
  if(!fs.existsSync(file)||fs.statSync(file).isDirectory()){
   if(url.pathname.startsWith('/assets/')){res.writeHead(404);res.end();return}
   file=path.join(dist,'index.html')
  }
  res.writeHead(200,{'Content-Type':({'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml'})[path.extname(file)]??'application/octet-stream'});fs.createReadStream(file).pipe(res)
 })
 return {server,state}
}
if(process.argv.includes('--serve')){
 const {server}=fixtureServer({requests:[],unknownApi:[]});server.listen(0,'127.0.0.1',()=>console.log(`http://127.0.0.1:${server.address().port}`))
}
