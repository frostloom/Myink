"""Application startup must not run destructive legacy cleanup during upgrades."""

from unittest.mock import MagicMock

from typer.testing import CliRunner


def test_init_does_not_run_legacy_schema_cleanup(monkeypatch):
    import myink.cli as cli
    import myink.db as db
    import myink.invitations as invitations
    import myink.seed as seed

    engine = MagicMock()
    monkeypatch.setattr(db, "get_admin_engine", lambda: engine)
    monkeypatch.setattr(cli.Base.metadata, "create_all", MagicMock())
    for name in (
        "enable_row_level_security", "ensure_chapter_versions", "ensure_genre_pack",
        "ensure_global_audit_reports", "ensure_memory_candidate_kinds",
        "ensure_project_creation", "ensure_project_form", "ensure_storage_indexes", "ensure_unique_constraints", "ensure_user_auth_schema",
        "ensure_user_environment", "ensure_user_role", "ensure_user_tier", "ensure_style_library_schema",
    ):
        monkeypatch.setattr(db, name, MagicMock())
    cleanup = MagicMock()
    monkeypatch.setattr(db, "ensure_legacy_schema_cleanup", cleanup)
    monkeypatch.setattr(invitations, "ensure_invitation_schema", MagicMock())
    monkeypatch.setattr(cli, "create_demo_project", lambda: "demo-project")
    monkeypatch.setattr(seed, "create_sample_books", lambda: [])

    cli.init(seed=True)

    cleanup.assert_not_called()


def test_db_cleanup_command_runs_the_legacy_cleanup(monkeypatch):
    """`myink db-cleanup` 是老库清结构的**唯一**入口，断了这条缝就会再犯同一个错。

    症状：模型侧删掉的列在老库里仍带 NOT NULL，`create_all` 不改已有表，插入时撞非空约束
    （events.related_threads 实际炸过一次）。`init` 被刻意禁止跑它，所以这里钉住另一头。
    """
    import myink.cli as cli
    import myink.db as db

    cleanup = MagicMock()
    monkeypatch.setattr(db, "ensure_legacy_schema_cleanup", cleanup)

    result = CliRunner().invoke(cli.app, ["db-cleanup"])

    assert result.exit_code == 0, result.output
    cleanup.assert_called_once_with()


def test_init_default_runs_additive_setup_without_creating_demo_or_samples(monkeypatch):
    import myink.cli as cli
    import myink.db as db
    import myink.invitations as invitations
    import myink.seed as seed

    engine = MagicMock()
    monkeypatch.setattr(db, "get_admin_engine", lambda: engine)
    monkeypatch.setattr(cli.Base.metadata, "create_all", MagicMock())
    migrations = {}
    for name in (
        "enable_row_level_security", "ensure_chapter_versions", "ensure_genre_pack",
        "ensure_global_audit_reports", "ensure_memory_candidate_kinds",
        "ensure_project_creation", "ensure_project_form", "ensure_storage_indexes", "ensure_unique_constraints",
        "ensure_user_auth_schema", "ensure_user_environment", "ensure_user_role",
        "ensure_user_tier", "ensure_style_library_schema",
    ):
        migrations[name] = MagicMock()
        monkeypatch.setattr(db, name, migrations[name])
    monkeypatch.setattr(invitations, "ensure_invitation_schema", MagicMock())
    demo = MagicMock(return_value="demo-project")
    samples = MagicMock(return_value=[])
    monkeypatch.setattr(cli, "create_demo_project", demo)
    monkeypatch.setattr(seed, "create_sample_books", samples)

    result = CliRunner().invoke(cli.app, ["init"])

    assert result.exit_code == 0, result.output
    demo.assert_not_called()
    samples.assert_not_called()
    migrations["ensure_user_role"].assert_called_once_with()
    migrations["ensure_project_form"].assert_called_once_with()
    migrations["ensure_style_library_schema"].assert_called_once_with()


def test_init_seed_flag_creates_demo_account_and_samples(monkeypatch):
    import myink.cli as cli
    import myink.db as db
    import myink.invitations as invitations
    import myink.seed as seed

    engine = MagicMock()
    monkeypatch.setattr(db, "get_admin_engine", lambda: engine)
    monkeypatch.setattr(cli.Base.metadata, "create_all", MagicMock())
    for name in (
        "enable_row_level_security", "ensure_chapter_versions", "ensure_genre_pack",
        "ensure_global_audit_reports", "ensure_memory_candidate_kinds",
        "ensure_project_creation", "ensure_project_form", "ensure_storage_indexes", "ensure_unique_constraints",
        "ensure_user_auth_schema", "ensure_user_environment", "ensure_user_role",
        "ensure_user_tier", "ensure_style_library_schema",
    ):
        monkeypatch.setattr(db, name, MagicMock())
    monkeypatch.setattr(invitations, "ensure_invitation_schema", MagicMock())
    demo = MagicMock(return_value="demo-project")
    samples = MagicMock(return_value=[])
    monkeypatch.setattr(cli, "create_demo_project", demo)
    monkeypatch.setattr(seed, "create_sample_books", samples)

    result = CliRunner().invoke(cli.app, ["init", "--seed"])

    assert result.exit_code == 0, result.output
    demo.assert_called_once_with()
    samples.assert_called_once_with()
