// 游客 = 已确认匿名（既没有本地会话，也不是「校验中」或「服务不可达」）。
import { useAuth } from '../context/AuthContext'

export function useGuest(): boolean {
  return useAuth().status === 'anonymous'
}
