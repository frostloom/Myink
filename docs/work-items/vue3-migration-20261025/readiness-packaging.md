> 最终状态（2026-10-26）：三镜像构建及实际运行门禁均已通过，非法selector按64失败，全部自有资源清理成功。下文保留中间执行历史；最终结果以末节与replacement-readiness.md为准。

# 可替换产物准备与安全补丁 — 2026-10-26

## 基线复现

原Caddy Dockerfile只有`npm run build`与React dist复制，即使传`FRONTEND_VARIANT=vue`仍构建React。实际构建myink-caddy:readiness-baseline-20261026后，frontend-image-smoke以expected vue执行，退出1：缺少所选frontend标记；构建日志明确为React产物index-BDxdzfd9.js。回执`/var/folders/sw/_x387kld25bgsp22s4n5rfjm0000gn/T/myink-image-smoke-WacUeW/receipt.json`。未运行/替换任何现有服务。

## 改动

- Caddy镜像新增FRONTEND_VARIANT=react|vue，默认react保持原生产行为；独立输出复制到相同/srv/web/dist位置，最终镜像io.myink.frontend标记可核验。非法值必须构建失败。
- Compose仅透传显式构建参数，默认react；CI继续验证React并增加Vue镜像构建。Docker context排除dist-vue，避免复制宿主旧候选。
- CI与构建Node对齐受支持的24.22版本；本机24.22.0，实际隔离构建容器24.22.1，不改Python/Caddy运行协议或生产配置。
- npm audit实际发现Vite8.2.1高危dev-server/editor路径问题、Vitest4.1.10及mocker中危问题（3个package findings）。只补丁升级Vite8.2.4、Vitest4.1.12，未跨大版本。安装后及独立audit均报告0已知漏洞；CI新增moderate门槛审计。

## 验证状态

新镜像双变体构建、原生runtime/深链/cache及错误参数门禁执行中，完成后附实际回执。所有镜像使用独立readiness标签，不覆盖myink-caddy:local，不执行compose up生产服务。

工具链更新后React599 tests、React/Vue lint与两构建通过。一次同时运行7个检查及Docker构建时，Vue出现3个5秒超时（556过/3超时）；原断言和timeout不改，单独复跑App/Login33项通过。后续固定maxWorkers=2、断言与5秒限制不变，完整559通过；真实事件修复后最终完整76文件561通过。该中间超时失败保留，不计作通过。

## 追加：实际旧客户端资产与碰撞门禁

实际只读确认当前运行版本使用index-Cvlt329b.js，和本地React补丁构建BDxd不同。已从其不可变镜像ID及React/Vue候选镜像提取6个公开JS/CSS文件，停止状态临时容器均清理，详见retained-assets-receipt.json。未挂载数据/证书卷，未替换服务。

独立评审指出裸COPY保留文件可能覆盖新构建同名文件；已按现有COPY语义实际复现2个失败（碰撞/symlink）后改为Node预扫描验证再合并，3项回归通过。Dockerfile仅复制合并后的统一产物；提取helper使用不可变image ID创建容器。CI增加安全合并回归。真实合并后双变体镜像仍待构建验收。

镜像smoke已分别清理browser/container/network，任何清理失败均令passed=false和退出1，独立复审原清理P2已关闭。一次Docker VM资源异常导致就绪及清理超时，回执W8xnra明确失败，不计作产品通过；后续只读ps未发现残留myink-image-smoke容器。

当前工作树未包含gateway目录或go.mod，项目规则中的Go通用入口在本版本不适用；未声称执行Go检查通过。CI YAML与Compose YAML已成功解析，并断言myink-caddy构建参数默认React。

## 镜像重试前的环境阻断

最终canonical Vue构建在同源码本机type/build已通过后，于Docker内vue-tsc阶段超过十分钟无输出；BuildKit history确认仍Running。同期API/Redis/worker健康，而专用Rabbit实际AMQP5s连接超时、health unhealthy；其他项目部分服务也出现健康超时。仅向本轮唯一docker build CLI发送SIGINT，实际exit130、BuildKit CANCELED（日志/tmp/myink-vue-final-image-build.log），不计通过。未重启daemon、未停止其他项目。先释放构建负载并完成真实browser/清理自有测试栈，再重试镜像门禁。不能单靠host build替代最终镜像通过。

## 最终三镜像结果（替代历史pending）

- Vue myink-caddy:vue-ready-final-20261026：canonicalDockerfile构建exit0，入口LHE，7项镜像浏览器检查passedtrue，原Cvlt旧JS可取，cleanupErrors=[]。
- 默认React myink-caddy:react-ready-final-20261026：未传variant仍构建React，入口BDxd，7项通过，最终LHE旧JS可取，cleanupErrors=[]。两镜像8个JS/CSS资源集及SHA完全相同，完整来源见retained-assets-receipt.json。
- API myink-api:vue-sse-ready-final-20261026：根Dockerfile构建exit0，实际镜像SSE源码SHA39587e77c3cb7334519f1e0957c2ba3d680e93f3336164ea62167a3afccb1454；25核心版本与跑1966测试的venv完全一致，113路径OpenAPI逐字节相同，TestClient healthz200。原API不可变镜像同门禁RED，最终修复镜像GREEN。
- 最终invalid前端selector构建退出1，内部明确exit64，未生成标签。未覆盖任何local生产标签或启动生产服务。
- scripts/api-image-smoke.py保留可复现镜像验收。新增纯fakeDocker部分创建故障：修前创建资源标记残留（RED），创建前登记回收责任后仍返回失败但无残留（GREEN），随后真实API镜像再跑passedtrue/cleanupErrors=[]。该故障注入不创建真实容器、不冒充实际API测试。
- readiness-final-{vue,react,api}-image-receipt.json及构建日志、baseline拒绝与invalid日志均保存。最终Docker只读inventory确认所有本轮prefix容器/网络均空，原真实链路8端口已关闭，无残留zombie。
- 三镜像均标记uncommitted-readiness-final-20261026，仅代表未提交候选，HEAD不可作为最终源身份。具体ID见build-provenance.json。

API镜像验收需在同一已安装项目核心/测试依赖的Python环境运行：`python scripts/api-image-smoke.py --image <候选API镜像> --output <回执JSON>`；它比较该环境的25核心版本并禁用网络，仅验证镜像启动，不替代真实DB/队列/worker验收。
