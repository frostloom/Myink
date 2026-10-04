import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ProjectRail } from '../components/ProjectRail'
import { useAuth } from '../context/AuthContext'
import { useGuest } from '../hooks/useGuest'
import { api } from '../lib/api'
import { formatApiError } from '../lib/apiError'
import { roleLabel, tierLabel } from '../lib/labels'
import { isValidNewPassword, NEW_PASSWORD_VALIDATION_MESSAGE } from '../lib/passwordPolicy'
import type { Project } from '../types'
import shell from './SettingsPage.module.css'
import styles from './AccountPage.module.css'

export default function AccountPage() {
  const { session, status, changePassword, logout, endSession } = useAuth()
  const guest = useGuest()
  const navigate = useNavigate()
  const [projects, setProjects] = useState<Project[]>([])
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // 第二因子（§2.8）只对管理员开放——/admin 是全站唯一能跨用户读数据的地方。
  const isAdmin = status === 'authenticated'
    && session?.role === 'admin'
    && session.roleVerified === true
  const [mfaEnabled, setMfaEnabled] = useState<boolean | null>(null)
  const [enrolling, setEnrolling] = useState(false)
  const [mfaSecret, setMfaSecret] = useState('')
  const [mfaUri, setMfaUri] = useState('')
  const [mfaPassword, setMfaPassword] = useState('')
  const [mfaCode, setMfaCode] = useState('')
  const [mfaError, setMfaError] = useState<string | null>(null)
  const [mfaBusy, setMfaBusy] = useState(false)

  useEffect(() => {
    if (!isAdmin || !session) {
      setMfaEnabled(null)
      return
    }
    let alive = true
    api.mfaStatus(session.token)
      .then((resp) => { if (alive) setMfaEnabled(resp.enabled) })
      .catch(() => { if (alive) setMfaEnabled(null) })
    return () => { alive = false }
  }, [isAdmin, session])

  useEffect(() => {
    if (guest) return
    let alive = true
    api.listProjects()
      .then((items) => { if (alive) setProjects(items) })
      .catch(() => { if (alive) setProjects([]) })
    return () => { alive = false }
  }, [guest])

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!isValidNewPassword(newPassword)) {
      setError(`新${NEW_PASSWORD_VALIDATION_MESSAGE}`)
      return
    }
    if (newPassword !== confirmPassword) {
      setError('两次输入的新密码不一致')
      return
    }
    if (!currentPassword) {
      setError('请输入当前密码')
      return
    }

    setBusy(true)
    setError(null)
    try {
      await changePassword(currentPassword, newPassword)
      // 后端已使该账号全部 token 失效，AuthContext 会清除本机会话并回到登录页。
    } catch (err) {
      setError(formatApiError(err, '密码修改失败'))
    } finally {
      setBusy(false)
    }
  }

  /** 开启/关闭成功都会让服务端踢掉全部会话（防滑动续期绕过第二因子），本机跟着退到登录页。
   *
   * 要显式跳到 /login：`endSession` 只是把状态置空，而本页在 GuestShell 下照常渲染，
   * 那句提示（`notice`）又只有登录页会读——不跳过去，人就只看到自己被登出、没有任何解释。
   */
  function revoked(notice: string) {
    endSession(notice)
    navigate('/login', { replace: true })
  }

  async function startEnroll(event: FormEvent) {
    event.preventDefault()
    if (!session) return
    if (!mfaPassword) {
      setMfaError('请输入当前密码')
      return
    }
    setMfaBusy(true)
    setMfaError(null)
    try {
      const resp = await api.mfaEnroll(mfaPassword, session.token)
      setMfaSecret(resp.secret)
      setMfaUri(resp.otpauth_uri)
      setMfaPassword('')
      setMfaCode('')
      setEnrolling(true)
    } catch (err) {
      setMfaError(formatApiError(err, '开启两步验证失败'))
    } finally {
      setMfaBusy(false)
    }
  }

  async function confirmEnroll(event: FormEvent) {
    event.preventDefault()
    if (!session) return
    const trimmed = mfaCode.trim()
    if (!/^\d{6}$/.test(trimmed)) {
      setMfaError('请输入 6 位验证码')
      return
    }
    setMfaBusy(true)
    setMfaError(null)
    try {
      await api.mfaConfirm(trimmed, session.token)
      revoked('两步验证已开启，本次登录已失效，请用验证码重新登录。')
    } catch (err) {
      setMfaError(formatApiError(err, '开启两步验证失败'))
      setMfaBusy(false)
    }
  }

  async function disableMfa(event: FormEvent) {
    event.preventDefault()
    if (!session) return
    const trimmed = mfaCode.trim()
    if (!/^\d{6}$/.test(trimmed)) {
      setMfaError('请输入 6 位验证码')
      return
    }
    setMfaBusy(true)
    setMfaError(null)
    try {
      await api.mfaDisable(trimmed, session.token)
      revoked('两步验证已关闭，本次登录已失效，请重新登录。')
    } catch (err) {
      setMfaError(formatApiError(err, '关闭两步验证失败'))
      setMfaBusy(false)
    }
  }

  return (
    <div className={shell.wrap}>
      <ProjectRail projects={projects} onLogout={logout} />
      <main className={shell.main}>
        <div className={shell.inner}>
          <header className={shell.header}>
            <div>
              <h1>账号</h1>
              <p className={shell.hint}>查看当前账号并更新登录密码。</p>
            </div>
          </header>

          <div className={styles.grid}>
            <section className={`panel ${styles.card}`} aria-labelledby="current-account">
              <h2 id="current-account">当前账号</h2>
              <dl className={styles.account}>
                <div>
                  <dt>用户名</dt>
                  <dd>{guest ? '未登录' : session?.username}</dd>
                </div>
                <div>
                  <dt>账号级别</dt>
                  <dd>{guest ? '—' : tierLabel(session?.tier ?? 'normal')}</dd>
                </div>
                <div>
                  <dt>账号角色</dt>
                  <dd>{guest ? '—' : roleLabel(session?.role ?? 'user')}</dd>
                </div>
              </dl>
            </section>

            <section className={`panel ${styles.card}`} aria-labelledby="change-password">
              <h2 id="change-password">修改密码</h2>
              <p className={shell.hint}>修改成功后，该账号在所有浏览器中的登录都会失效，需要重新登录。</p>
              <form className={styles.form} onSubmit={submit}>
                <label className={styles.field}>
                  <span>当前密码</span>
                  <input
                    className="input"
                    type="password"
                    value={currentPassword}
                    onChange={(event) => setCurrentPassword(event.target.value)}
                    autoComplete="current-password"
                  />
                </label>
                <label className={styles.field}>
                  <span>新密码</span>
                  <input
                    className="input"
                    type="password"
                    value={newPassword}
                    onChange={(event) => setNewPassword(event.target.value)}
                    autoComplete="new-password"
                  />
                </label>
                <label className={styles.field}>
                  <span>确认新密码</span>
                  <input
                    className="input"
                    type="password"
                    value={confirmPassword}
                    onChange={(event) => setConfirmPassword(event.target.value)}
                    autoComplete="new-password"
                  />
                </label>
                {error && <div className="banner banner-error" role="alert">{error}</div>}
                <button type="submit" className="btn btn-primary" disabled={busy}>
                  {busy ? '修改中…' : '修改密码'}
                </button>
              </form>
            </section>

            {isAdmin && (
              <section className={`panel ${styles.card} ${styles.wide}`} aria-labelledby="admin-console">
                <h2 id="admin-console">管理后台</h2>
                <p className={shell.hint}>查看全部作品的运行记录、成本与配额，管理账号与邀请码。</p>
                <div><Link className="btn btn-secondary" to="/admin">打开管理后台</Link></div>
              </section>
            )}

            {isAdmin && (
              <section className={`panel ${styles.card} ${styles.wide}`} aria-labelledby="mfa">
                <h2 id="mfa">两步验证</h2>
                {enrolling ? (
                  <form className={styles.form} onSubmit={confirmEnroll}>
                    <div className={styles.field}>
                      <span>密钥</span>
                      <code className={styles.secret}>{mfaSecret}</code>
                    </div>
                    <div className={styles.field}>
                      <span>otpauth 链接</span>
                      <code className={styles.secret}>{mfaUri}</code>
                    </div>
                    <label className={styles.field}>
                      <span>验证码</span>
                      <input
                        className="input"
                        value={mfaCode}
                        onChange={(event) => setMfaCode(event.target.value)}
                        inputMode="numeric"
                        autoComplete="one-time-code"
                        maxLength={6}
                        spellCheck={false}
                      />
                    </label>
                    {mfaError && <div className="banner banner-error" role="alert">{mfaError}</div>}
                    <button className="btn btn-primary" type="submit" disabled={mfaBusy}>
                      {mfaBusy ? '确认中…' : '确认开启'}
                    </button>
                  </form>
                ) : mfaEnabled === true ? (
                  <form className={styles.form} onSubmit={disableMfa}>
                    <div className="badge badge-success">已开启</div>
                    <label className={styles.field}>
                      <span>验证码</span>
                      <input
                        className="input"
                        value={mfaCode}
                        onChange={(event) => setMfaCode(event.target.value)}
                        inputMode="numeric"
                        autoComplete="one-time-code"
                        maxLength={6}
                        spellCheck={false}
                      />
                    </label>
                    {mfaError && <div className="banner banner-error" role="alert">{mfaError}</div>}
                    <button className="btn btn-secondary" type="submit" disabled={mfaBusy}>
                      {mfaBusy ? '关闭中…' : '关闭两步验证'}
                    </button>
                  </form>
                ) : mfaEnabled === false ? (
                  <form className={styles.form} onSubmit={startEnroll}>
                    <label className={styles.field}>
                      <span>账号密码</span>
                      <input
                        className="input"
                        type="password"
                        value={mfaPassword}
                        onChange={(event) => setMfaPassword(event.target.value)}
                        autoComplete="current-password"
                      />
                    </label>
                    {mfaError && <div className="banner banner-error" role="alert">{mfaError}</div>}
                    <button className="btn btn-primary" type="submit" disabled={mfaBusy}>
                      {mfaBusy ? '生成中…' : '开启两步验证'}
                    </button>
                  </form>
                ) : null}
              </section>
            )}

            <section className={`panel ${styles.card} ${styles.wide}`} aria-labelledby="password-help">
              <h2 id="password-help">忘记密码</h2>
              <p className={shell.hint}>
                本地部署不提供邮件找回。请联系本机管理员，通过 Myink 管理命令为账号重设密码。
              </p>
            </section>
          </div>
        </div>
      </main>
    </div>
  )
}
