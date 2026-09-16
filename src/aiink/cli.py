"""阶段 1 CLI：本地端到端跑通（章节生成 / 校验证据 / 批次 / 任务时间线）。

用法：
    aiink init                                  # 建表 + RLS + demo 种子
    aiink chapter <project_id> <seq>            # 生成单章
    aiink batch <project_id> <N> <start_seq>    # 自动写作批次
    aiink status <task_id>                      # 任务状态 + 每节点成本/耗时
"""

from __future__ import annotations

import uuid

import typer
from rich.console import Console
from rich.table import Table
from sqlalchemy import text

from aiink.db import get_engine, tenant_session
from aiink.models import Base
from aiink.seed import create_demo_project
from aiink.workflow.runner import generate_batch, generate_chapter, new_task

app = typer.Typer(help="Ai Ink 推理层 CLI（阶段 1 单体闭环）")
console = Console()


@app.command()
def init() -> None:
    """初始化数据库：建表 + RLS + demo 种子数据。"""
    from aiink.db import (enable_row_level_security, ensure_chapter_versions,
                          ensure_genre_pack, ensure_global_audit_reports,
                          ensure_memory_candidate_kinds, ensure_storage_indexes,
                          ensure_unique_constraints, ensure_user_environment,
                          ensure_user_tier, get_admin_engine)
    from aiink.seed import create_sample_books

    # 建表 + RLS 走超级用户（owner）连接；业务运行走 aiink_app（NOBYPASSRLS，受 RLS 约束）
    # 扩展须在 create_all 之前建（HNSW 索引/vector 列依赖 vector 类型，评审存储建议）
    with get_admin_engine().begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    console.print("[bold]1/3[/] 建表（PostgreSQL + pgvector）...")
    Base.metadata.create_all(get_admin_engine())
    console.print("[bold]1.5/3[/] 补齐唯一约束 + 组合索引/HNSW（幂等，评审 A6/存储建议）...")
    ensure_unique_constraints()
    ensure_storage_indexes()
    console.print("[bold]1.55/3[/] 补齐 users.tier（阶段 6 VIP 优先级，幂等）...")
    ensure_user_tier()
    console.print("[bold]1.56/3[/] 补齐 users.environment（账号级环境配置，幂等）...")
    ensure_user_environment()
    console.print("[bold]1.57/3[/] 补齐 project_settings.genre_pack（本书题材包，幂等）...")
    ensure_genre_pack()
    console.print("[bold]1.6/3[/] 补齐记忆候选 kind 枚举（memory_removal，阶段 3 编辑校正）...")
    ensure_memory_candidate_kinds()
    console.print("[bold]1.7/3[/] 补齐全局审计报告表（global_audit_reports，阶段 3 长线治理）...")
    ensure_global_audit_reports()
    console.print("[bold]1.8/3[/] 补齐章节版本表（chapter_versions，阶段 4 历史/回退）...")
    ensure_chapter_versions()
    console.print("[bold]2/3[/] 启用 RLS 主强制（FORCE ROW LEVEL SECURITY）...")
    enable_row_level_security()
    console.print("[bold]3/3[/] 写入 demo 种子（《九州问天》+ 示例书）...")
    pid = create_demo_project()
    new_books = create_sample_books()
    console.print(f"[green]✓[/] 初始化完成。demo project_id = [bold]{pid}[/]"
                  + (f"；新增示例书 {len(new_books)} 本（多书展示）" if new_books else ""))


@app.command()
def chapter(project_id: str, seq: int, instruction: str | None = None) -> None:
    """生成单章（含校验证据 + 战力通胀/大纲偏差报告）。"""
    task_id = new_task(project_id=project_id, task_type="chapter_generate",
                       payload={"seq": seq}, chapter_seq=seq)
    console.print(f"task_id = {task_id}\n[dim]生成中（10–60s）...[/]")
    result = generate_chapter(project_id=project_id, chapter_seq=seq, task_id=task_id,
                              user_instruction=instruction)
    _print_chapter_result(result)


def _print_chapter_result(result: dict) -> None:
    if result.get("error"):
        console.print(f"[red]✗ 失败: {result['error']}[/]")
        return
    draft = result.get("draft", "")
    console.print(f"\n[bold]第 {result.get('chapter_seq')} 章[/]（{len(draft)} 字）")
    console.print(draft[:500] + ("..." if len(draft) > 500 else ""))

    report = result.get("report") or {}
    findings = report.get("findings", [])
    if findings:
        table = Table(title=f"校验报告（{report.get('summary', {}).get('total', 0)} 项）")
        table.add_column("类型"); table.add_column("严重度"); table.add_column("证据"); table.add_column("建议")
        for f in findings:
            ev = "; ".join(q["quote"][:60] for q in f.get("evidence", []))
            table.add_row(f.get("conflict_type"), f.get("severity"),
                          ev or "-", f.get("suggestion", ""))
        console.print(table)
    else:
        console.print("[green]✓ 校验通过，无冲突[/]")

    if result.get("needs_review"):
        console.print("[yellow]⏸ 存在 critical 冲突 → 候选已转待人工确认（批次将暂停）[/]")


@app.command()
def batch(project_id: str, n: int, start_seq: int = 1) -> None:
    """自动写作批次：一次规划 N 章推进蓝图，逐章生成（§6.11）。"""
    if n < 1 or n > 20:
        console.print("[red]N 需在 1–20（硬上限，§6.11）[/]")
        raise typer.Exit(1)
    task_id = new_task(project_id=project_id, task_type="batch_generate",
                       payload={"size": n, "start": start_seq}, chapter_seq=start_seq)
    console.print(f"batch_task_id = {task_id}\n[dim]批次生成中（N 章，每章 10–60s）...[/]")
    result = generate_batch(project_id=project_id, size=n, start_chapter=start_seq,
                            batch_task_id=task_id)
    if result.get("error"):
        console.print(f"[red]✗ 批次中断: {result['error']}[/]")
    summary = result.get("batch_summary") or {}
    console.print(f"[bold]批次汇总[/]: 状态={summary.get('status')} 完成={summary.get('completed')}/{summary.get('size')} "
                  f"总成本≈¥{summary.get('total_cost', 0)} 总耗时={summary.get('total_duration_ms', 0)}ms")


@app.command()
def status(task_id: str) -> None:
    """任务状态 + 每节点 token/成本/耗时（§6.8 节点时间线）。"""
    from aiink.models import AgentRun, Task

    # agent_runs / tasks 是观测/队列数据，不走 RLS（§14 隔离清单：Redis/观测数据无租户语义）
    from aiink.db import new_session

    with new_session() as db:
        task = db.get(Task, uuid.UUID(task_id))
        if task is None:
            console.print("[red]任务不存在[/]")
            raise typer.Exit(1)
        # 批次内每章 run 的 task_id = {task_id}:ch{seq}，前缀匹配才不漏章成本（同 node_batch_end）
        runs = db.query(AgentRun).filter(AgentRun.task_id.like(f"{task_id}%")).order_by(AgentRun.id).all()
        table = Table(title=f"任务 {task_id[:8]} · {task.task_type} · {task.status}")
        table.add_column("节点"); table.add_column("模型"); table.add_column("输入tok")
        table.add_column("输出tok"); table.add_column("缓存"); table.add_column("耗时ms")
        table.add_column("成本¥"); table.add_column("重试"); table.add_column("降级")
        for r in runs:
            table.add_row(r.node, r.model_id or "-", str(r.input_tokens), str(r.output_tokens),
                          "✓" if r.cache_hit else "-", str(r.duration_ms),
                          f"{r.cost_est:.4f}", str(r.retry_count), "✓" if r.degraded else "-")
        console.print(table)
        total = round(sum(r.cost_est for r in runs), 6)
        console.print(f"合计成本 ≈ ¥{total}，总耗时 {sum(r.duration_ms for r in runs)}ms")


contract_app = typer.Typer(help="契约工具：导出 OpenAPI 响应契约（阶段 5 契约测试形式化）")
app.add_typer(contract_app, name="contract")


@contract_app.command()
def export() -> None:
    """导出 OpenAPI 契约到 spec/api-openapi.json（HTTP 响应契约单一事实源）。"""
    import json
    import pathlib

    from aiink.api.main import app  # 延迟导入：CLI 不模块级引入 API 装配

    spec_path = pathlib.Path(__file__).resolve().parents[2] / "spec" / "api-openapi.json"
    spec_path.write_text(
        json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    # ASCII 输出（✓ 在 GBK 控制台会 UnicodeEncodeError，见 scripts/ci-local.sh 同款修复）
    console.print(f"[green]OK[/] OpenAPI 契约已导出"
                  f"（{len(app.openapi()['paths'])} 条路径）：{spec_path}")


if __name__ == "__main__":
    app()
