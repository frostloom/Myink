// 四只吊灯，对应主题里的可选样式。画面只画灯，不带任何标语。
// lit 关掉时灯罩里的暖光收掉，页上那摊光由调用方另外决定。
import { useId } from 'react'
import { LAMP_HANG, type LampId } from '../lib/theme'

type LampProps = {
  id: LampId
  lit: boolean
  className?: string
  /** 挂在页面上时绳子另画，这里只留灯头，绳长才能跟着拖拽变。 */
  hanging?: boolean
}

function gid(prefix: string, name: string): string {
  return `${prefix}-${name}`
}

function Shade({ prefix, lit }: { prefix: string; lit: boolean }) {
  const fabric = gid(prefix, 'fabric')
  const wood = gid(prefix, 'wood')
  const clip = gid(prefix, 'clip')
  return (
    <g>
      <defs>
        <linearGradient id={fabric} x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#d8ccb6" />
          <stop offset="14%" stopColor="#f6efe4" />
          <stop offset="46%" stopColor="#fbf7f0" />
          <stop offset="78%" stopColor="#efe3d2" />
          <stop offset="100%" stopColor="#c9bba6" />
        </linearGradient>
        <radialGradient id={wood} cx="32%" cy="28%" r="75%">
          <stop offset="0%" stopColor="#c48962" />
          <stop offset="48%" stopColor="#7a4630" />
          <stop offset="100%" stopColor="#3d2418" />
        </radialGradient>
        <clipPath id={clip}>
          <path d="M62 186 C62 174 138 174 138 186 L142 252 C142 266 58 266 58 252 Z" />
        </clipPath>
      </defs>
      <path d="M100 2 C104 36 96 70 100 104 C104 132 96 150 100 168" fill="none" stroke="#cbbda6" strokeWidth="1.7" />
      <path d="M100 2 C96 36 104 70 100 104 C96 132 104 150 100 168" fill="none" stroke="#8f806c" strokeWidth="0.7" opacity="0.75" />
      <ellipse cx="128" cy="276" rx="36" ry="7" fill="#000" opacity="0.07" />
      <ellipse cx="100" cy="176" rx="8.5" ry="7.6" fill={`url(#${wood})`} />
      <ellipse cx="97" cy="173" rx="2.6" ry="1.6" fill="#fff" opacity="0.28" />
      <rect x="96.2" y="182" width="7.6" height="3.4" rx="1" fill="#b7aea2" />
      <g clipPath={`url(#${clip})`}>
        <path d="M62 186 C62 174 138 174 138 186 L142 252 C142 266 58 266 58 252 Z" fill={`url(#${fabric})`} />
        {Array.from({ length: 16 }, (_, index) => (
          <line
            key={index}
            x1={66 + index * 4.6}
            y1="174"
            x2={64 + index * 4.6}
            y2="268"
            stroke="#e3d5c2"
            strokeWidth="0.7"
            opacity="0.7"
          />
        ))}
        <rect x="76" y="174" width="3.3" height="94" fill="#d24b42" />
        <rect x="116" y="174" width="3.3" height="94" fill="#d24b42" />
      </g>
      <ellipse cx="100" cy="186" rx="38" ry="9" fill="#f8f3ea" />
      <ellipse cx="100" cy="186" rx="31" ry="5.2" fill="#efe4d4" />
      <ellipse cx="100" cy="256" rx="40" ry="9" fill={lit ? '#fff3d8' : '#e4d8c6'} />
      <ellipse cx="100" cy="256" rx="27" ry="4.6" fill={lit ? '#fffdf8' : '#efe6d6'} opacity={lit ? 1 : 0.45} />
    </g>
  )
}

function Cube({ prefix, lit }: { prefix: string; lit: boolean }) {
  const chrome = gid(prefix, 'chrome')
  const paper = gid(prefix, 'paper')
  return (
    <g>
      <defs>
        <linearGradient id={chrome} x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#8d8d8d" />
          <stop offset="24%" stopColor="#f8f8f8" />
          <stop offset="48%" stopColor="#b9b9b9" />
          <stop offset="74%" stopColor="#f3f3f3" />
          <stop offset="100%" stopColor="#6f6f6f" />
        </linearGradient>
        <linearGradient id={paper} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={lit ? '#fff6df' : '#e7dcc8'} />
          <stop offset="100%" stopColor={lit ? '#f0d7a4' : '#d9cdb8'} />
        </linearGradient>
      </defs>
      <line x1="100" y1="0" x2="100" y2="124" stroke="#1c1c1c" strokeWidth="2.1" />
      <ellipse cx="142" cy="262" rx="34" ry="7" fill="#000" opacity="0.08" />
      <ellipse cx="100" cy="128" rx="14" ry="5" fill="#f7f7f7" />
      <path d="M86 128 h28 v18 a14 5 0 0 1 -28 0 z" fill={`url(#${chrome})`} />
      <rect x="93" y="130" width="2.4" height="14" rx="1" fill="#fff" opacity="0.85" />
      <path d="M44 172 L78 148 L156 148 L122 172 Z" fill="rgba(255,255,255,0.72)" stroke="#bdbdbd" strokeWidth="1.7" strokeLinejoin="round" />
      <path d="M122 172 L156 148 L156 224 L122 248 Z" fill="rgba(214,214,214,0.55)" stroke="#b0b0b0" strokeWidth="1.7" strokeLinejoin="round" />
      <path d="M44 172 H122 V248 H44 Z" fill="rgba(255,255,255,0.38)" stroke="#c4c4c4" strokeWidth="1.8" strokeLinejoin="round" />
      <path d="M58 184 H108 V232 H58 Z" fill={`url(#${paper})`} />
      <g stroke={lit ? '#d9a84c' : '#c9b48a'} strokeWidth="0.9" opacity="0.95">
        {[0, 1, 2, 3, 4].map((index) => (
          <line key={index} x1="58" y1={192 + index * 8} x2="108" y2={192 + index * 8} />
        ))}
        {[0, 1, 2, 3, 4, 5].map((index) => (
          <line key={`v${index}`} x1={66 + index * 8} y1="184" x2={66 + index * 8} y2="232" />
        ))}
      </g>
      <path d="M122 190 L146 174 L146 214 L122 230 Z" fill={lit ? 'rgba(245,214,150,0.72)' : 'rgba(214,204,184,0.45)'} />
      {lit && <ellipse cx="84" cy="222" rx="16" ry="6" fill="#fff6dc" opacity="0.75" />}
    </g>
  )
}

function Globe({ prefix, lit }: { prefix: string; lit: boolean }) {
  const red = gid(prefix, 'red')
  const amber = gid(prefix, 'amber')
  return (
    <g>
      <defs>
        <radialGradient id={red} cx="34%" cy="30%" r="72%">
          <stop offset="0%" stopColor="#ff9b90" />
          <stop offset="42%" stopColor="#e23a32" />
          <stop offset="100%" stopColor="#8c1514" />
        </radialGradient>
        <radialGradient id={amber} cx="46%" cy="42%" r="68%">
          <stop offset="0%" stopColor={lit ? '#fff3c8' : '#e4d2ae'} stopOpacity="0.98" />
          <stop offset="38%" stopColor={lit ? '#f0c27a' : '#c9a56e'} stopOpacity="0.82" />
          <stop offset="72%" stopColor="#a56b3c" stopOpacity="0.78" />
          <stop offset="100%" stopColor="#5c3a28" stopOpacity="0.92" />
        </radialGradient>
      </defs>
      <line x1="100" y1="0" x2="100" y2="108" stroke="#1c1c1c" strokeWidth="2.1" />
      <ellipse cx="138" cy="268" rx="52" ry="8" fill="#000" opacity="0.08" />
      <circle cx="100" cy="118" r="11" fill={`url(#${red})`} />
      <ellipse cx="96" cy="114" rx="3.2" ry="2" fill="#fff" opacity="0.45" />
      <circle cx="100" cy="142" r="16.5" fill={`url(#${red})`} />
      <ellipse cx="94" cy="136" rx="4.4" ry="2.6" fill="#fff" opacity="0.35" />
      <ellipse cx="100" cy="198" rx="74" ry="52" fill={`url(#${amber})`} />
      <ellipse cx="68" cy="176" rx="16" ry="24" fill="#fff" opacity="0.18" transform="rotate(-16 68 176)" />
      <ellipse cx="100" cy="214" rx="48" ry="22" fill={lit ? '#ffe7ad' : '#d7c09a'} opacity={lit ? 0.72 : 0.28} />
      <ellipse cx="100" cy="228" rx="58" ry="16" fill="none" stroke="rgba(255,255,255,0.35)" strokeWidth="1.5" />
    </g>
  )
}

function Cone({ prefix, lit }: { prefix: string; lit: boolean }) {
  const red = gid(prefix, 'red')
  const cone = gid(prefix, 'cone')
  return (
    <g>
      <defs>
        <radialGradient id={red} cx="34%" cy="30%" r="72%">
          <stop offset="0%" stopColor="#ff9b90" />
          <stop offset="42%" stopColor="#e23a32" />
          <stop offset="100%" stopColor="#8c1514" />
        </radialGradient>
        <linearGradient id={cone} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#fff" />
          <stop offset="70%" stopColor="#f7f4ef" />
          <stop offset="100%" stopColor="#e7e1d8" />
        </linearGradient>
      </defs>
      <line x1="100" y1="0" x2="100" y2="112" stroke="#d8d8d8" strokeWidth="2.2" />
      <line x1="99" y1="0" x2="99" y2="112" stroke="#f7f7f7" strokeWidth="0.8" />
      <ellipse cx="136" cy="246" rx="52" ry="8" fill="#000" opacity="0.07" />
      <circle cx="100" cy="126" r="14" fill={`url(#${red})`} />
      <ellipse cx="94" cy="120" rx="4" ry="2.4" fill="#fff" opacity="0.4" />
      <path
        d="M86 142 C84 166 42 190 20 208 C68 222 132 222 180 208 C158 190 116 166 114 142 Z"
        fill={`url(#${cone})`}
      />
      <ellipse cx="100" cy="208" rx="80" ry="14" fill="#f3eee6" />
      <ellipse cx="100" cy="208" rx="46" ry="8" fill={lit ? '#fff6e4' : '#ebe4da'} />
      <circle cx="100" cy="222" r="15" fill={lit ? '#fffdf8' : '#e6e1d8'} />
      <circle cx="100" cy="222" r="8" fill={lit ? '#fff' : '#ddd6cc'} opacity={lit ? 1 : 0.7} />
      {lit && <ellipse cx="94" cy="216" rx="4" ry="2.4" fill="#fff" opacity="0.9" />}
    </g>
  )
}

export function PendantLamp({ id, lit, className, hanging = false }: LampProps) {
  const prefix = useId().replace(/:/g, '')
  const hang = LAMP_HANG[id]
  const span = 300 - hang.top
  const viewBox = hanging ? `0 ${hang.top} 200 ${span}` : '0 0 200 300'
  return (
    <svg
      className={className}
      viewBox={viewBox}
      overflow="hidden"
      aria-hidden="true"
      focusable="false"
      style={hanging ? { width: 104, height: 104 * span / 200 } : undefined}
    >
      {id === 'shade' && <Shade prefix={prefix} lit={lit} />}
      {id === 'cube' && <Cube prefix={prefix} lit={lit} />}
      {id === 'globe' && <Globe prefix={prefix} lit={lit} />}
      {id === 'cone' && <Cone prefix={prefix} lit={lit} />}
    </svg>
  )
}
