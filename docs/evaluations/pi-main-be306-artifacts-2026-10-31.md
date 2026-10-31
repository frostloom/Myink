# main be306 产物核验

main/Pi 源提交 `be306a459447a148f5393391c7fb15a9d4f4aef9` 的[main CI四项通过](https://github.com/frostloom/Myink/actions/runs/41180514949)，[Pi CI四项通过](https://github.com/frostloom/Myink/actions/runs/41180480597)。[机器回执](pi-main-be306-artifacts-2026-10-31.json)保留镜像、平台、完整源码、API、静态文件、归档及旧桥接runtime摘要。

API已在本地amd64仿真、UID10001、只读/无网络/去capabilities容器中核验155份Python文件与源提交逐字节一致，128条完整OpenAPI契约一致，未登录管理台状态为401/no-store。Caddy通过类型检查、Vue构建和Caddyvalidate。主工作区初次构建混入10份历史public静态缓存，保留该非候选镜像作本地历史；最后从精确Git archive干净源码构建 `myink-caddy:pi-admin-amd64-be306a45-clean`，成品5文件与已三引擎验收产物逐文件摘要完全相等，index仍为 `3fcdda72ae5455deb2ac0defc0de4a759e8e47774f3ced9592c009b9b9d85629`。机器回执static_sha256按无空格规范JSON映射计算，比较依据是每个路径的实际文件摘要。

归档 `/private/tmp/myink-pi-admin-amd64-be306a45.tar`，127870464字节，SHA256 `b070ea567aa26f8c2040a4fe584b4104368af5532ee8923678fd9f78396c8a6f`。只有两张新amd64镜像，均为be306全长revision/UID10001；目标daemon加载后须重新读取实际image ID并核对归档config摘要。

DockerHub直连metadata曾DeadlineExceeded，失败日志保留；成功构建使用上一批已核验的同digest镜像源及锁定依赖。此记录只证明本地材料，无生产上传/加载/替换、无新模型调用、无预算或未知预留更改。记录中的be306闭合runtime不包含后续开发的人工观察交接；实际安装前须从审查完成的controller提交重建并记录新的pin，不得把本记录当生产发布或完整线上闭环验收。
