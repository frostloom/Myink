import { useMemoryFormGuard } from './useMemoryFormGuard'
import { reactive, watch, toValue, onScopeDispose, type MaybeRefOrGetter } from 'vue'
import { api, ApiError } from '../../../src/lib/api'
import { liveDrafts, readChapterDraft } from '../../../src/lib/chapterDraft'
import type { Router } from 'vue-router'
import type { ChapterDetail } from '../../../src/types'
import type { ChapterDraft } from '../../../src/lib/chapterDraft'
export interface ChapterDraftOptions { key:MaybeRefOrGetter<string>;projectId:MaybeRefOrGetter<string>;chapterId:MaybeRefOrGetter<string>;refreshTick?:MaybeRefOrGetter<number>;onNotFound:()=>void;onSaved:()=>void;router?:Router }
export function useChapterDraft(options:ChapterDraftOptions){
  const state=reactive({detail:null as ChapterDetail|null,draft:null as ChapterDraft|null,dirty:false,saving:false,error:null as string|null,backupError:false,conflict:false,edit,save,acceptRemote})
  let alive=true,identity=0,readId=0,lastKey=''
  const key=()=>toValue(options.key)
  function put(next:ChapterDraft,changed:boolean){
    state.draft={...next};state.dirty=changed
    if(changed)liveDrafts.set(key(),{...next});else liveDrafts.delete(key())
    try{if(changed)sessionStorage.setItem(key(),JSON.stringify(next));else sessionStorage.removeItem(key());state.backupError=false}catch{state.backupError=true}
  }
  async function load(){
    const read=++readId,version=identity,currentKey=key()
    state.error=null
    try{
      const remote=await api.getChapter(toValue(options.projectId),toValue(options.chapterId))
      if(!alive||read!==readId||version!==identity||currentKey!==key())return
      state.detail=remote
      let local=state.dirty?state.draft:null
      if(!state.draft){try{local=readChapterDraft(currentKey)}catch{state.backupError=true}}
      if(local&&local.content!==(remote.content??'')){put(local,true);state.conflict=local.baseVersion!==remote.version}
      else{put({content:remote.content??'',baseVersion:remote.version},false);state.conflict=false}
    }catch(err){
      if(!alive||read!==readId||version!==identity)return
      if(err instanceof ApiError&&err.status===404)options.onNotFound()
      else state.error='正文加载失败，请稍后重新打开。已有草稿仍保留在本标签页。'
    }
  }
  function edit(content:string){if(state.draft)put({...state.draft,content},true)}
  async function save(expectedVersion?:number){
    if(!state.draft||state.saving)return
    const submitted={...state.draft},version=identity,currentKey=key(),projectId=toValue(options.projectId),chapterId=toValue(options.chapterId)
    state.saving=true;state.error=null
    try{
      const response=await api.updateContent(projectId,chapterId,submitted.content,expectedVersion??submitted.baseVersion)
      if(!alive||version!==identity||currentKey!==key())return
      ++readId
      const latest=state.draft??submitted
      put({content:latest.content,baseVersion:response.version},latest.content!==submitted.content)
      if(state.detail)state.detail={...state.detail,content:submitted.content,version:response.version}
      state.conflict=false;options.onSaved()
    }catch(err){
      if(!alive||version!==identity||currentKey!==key())return
      if(err instanceof ApiError&&err.status===409){
        state.conflict=true;state.error='服务器正文已更新，草稿未覆盖。请查看最新正文后选择如何处理。'
        try{const remote=await api.getChapter(projectId,chapterId);if(alive&&version===identity)state.detail=remote}catch{/* keep old baseVersion */}
      }else state.error='保存失败，草稿已保留，请重试。'
    }finally{if(alive&&version===identity)state.saving=false}
  }
  function acceptRemote(){if(!state.detail||state.saving||!window.confirm('放弃当前未提交的草稿，载入服务器正文？'))return;put({content:state.detail.content??'',baseVersion:state.detail.version},false);state.conflict=false;state.error=null}
  useMemoryFormGuard(() => state.dirty && state.backupError, { router: options.router, unloadDirty: () => state.dirty })
  watch(()=>[key(),toValue(options.projectId),toValue(options.chapterId),options.refreshTick===undefined?0:toValue(options.refreshTick)],()=>{
    if(lastKey!==key()){identity++;lastKey=key();state.detail=null;state.draft=null;state.dirty=false;state.saving=false;state.backupError=false;state.conflict=false}
    void load()
  },{immediate:true})
  onScopeDispose(()=>{alive=false;identity++;readId++;})
  return state
}
