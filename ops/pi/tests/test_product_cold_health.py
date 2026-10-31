"""Runtime cold checks use ASGI/lifespan; separate PID1 still proves real HTTP."""
import ast,asyncio
from contextlib import asynccontextmanager
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from ops.pi.product_cold_probe import PROBE


def health():
    definitions=[n for n in ast.parse(PROBE).body if isinstance(n,ast.AsyncFunctionDef) and n.name=='verify_asgi_health']
    assert len(definitions)==1,'missing runtime ASGI health verification'
    def check(ok,reason):
        if not ok:raise RuntimeError(reason)
    namespace=dict(check=check);exec(compile(ast.Module(body=definitions,type_ignores=[]),'<fixed cold health>','exec'),namespace)
    return namespace['verify_asgi_health']


def make(fault=None):
    events=[]
    @asynccontextmanager
    async def lifespan(app):
        if fault=='startup':raise RuntimeError('startup rejected')
        events.append('start')
        try:yield
        finally:events.append('stop')
    app=FastAPI(lifespan=lifespan)
    @app.get('/healthz')
    async def endpoint():return JSONResponse({'status':'bad' if fault=='body' else 'ok'},status_code=503 if fault=='status' else 200)
    return app,events


def test_runtime_health_executes_app_lifespan_and_endpoint():
    app,events=make();asyncio.run(health()(app));assert events==['start','stop']


@pytest.mark.parametrize('fault',['body','status','startup'])
def test_runtime_health_refuses_unhealthy_or_failed_lifespan_and_closes(fault):
    app,events=make(fault)
    with pytest.raises(RuntimeError):asyncio.run(health()(app))
    assert events==([] if fault=='startup' else ['start','stop'])
