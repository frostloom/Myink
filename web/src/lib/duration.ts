/** 毫秒 → 人类可读耗时：1 秒内给毫秒，1 分钟内给一位小数的秒，再往上给「N 分 N 秒」。
 *
 * 先取整到秒再拆分秒，否则 round 出来的秒数会顶到 60（119.6 秒会写成「1 分 60 秒」）。
 * 原先有两份实现（工作台时间线 / 管理台），管理台那份没有分钟分支，
 * 任务一旦跑过一分钟就显示成「1323.31 秒」。
 */
export function formatDuration(milliseconds: number): string {
  if (milliseconds < 1000) return `${milliseconds} ms`
  if (milliseconds < 60_000) return `${(milliseconds / 1000).toFixed(1)} 秒`
  const totalSeconds = Math.round(milliseconds / 1000)
  return `${Math.floor(totalSeconds / 60)} 分 ${totalSeconds % 60} 秒`
}