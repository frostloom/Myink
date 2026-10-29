"""真实事务检查：被拒绝的题材修改不能留下部分写入。"""
import uuid

import pytest
from fastapi import HTTPException

from myink.api import routes_book, routes_genre
from myink.db import tenant_session
from myink.genre_catalog import build_book_pack
from myink.memory.repository import get_settings
from myink.models import Project


@pytest.mark.parametrize('action', ['name', 'fields', 'restore'])
def test_ready_long_rejects_genre_mutation_without_changing_saved_book(temp_project, action):
    pid = uuid.UUID(temp_project)
    pack = build_book_pack('xiuxian', None)
    with tenant_session(temp_project) as db:
        project = db.get(Project, pid)
        project.form = 'long'
        project.creation_status = 'ready'
        project.genre = '修仙'
        original_title = project.title
        st = get_settings(db, pid)
        if st is None:
            from myink.models import ProjectSettings
            st = ProjectSettings(project_id=pid)
            db.add(st)
        st.genre_pack = pack
        db.flush()
        original_version = st.version
    with pytest.raises(HTTPException) as error:
        if action == 'name':
            routes_book.update_project(temp_project, routes_book.ProjectUpdateBody(title='不应保存', genre='都市'))
        elif action == 'fields':
            routes_genre.put_genre_pack(temp_project, routes_genre.GenrePackFieldsBody(pacing='不应保存'))
        else:
            routes_genre.restore_genre_pack(temp_project)
    assert error.value.status_code == 409
    with tenant_session(temp_project) as db:
        project = db.get(Project, pid)
        st = get_settings(db, pid)
        assert project.genre == '修仙'
        assert project.title == original_title
        assert st.genre_pack == pack
        assert st.version == original_version
