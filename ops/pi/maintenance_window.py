"""Automatic night admission and finish bounds, independent of model output."""
from datetime import timezone,timedelta
from .audit import require

SHANGHAI=timezone(timedelta(hours=8))


def budget(now,ceiling):
    require(now.utcoffset() is not None and type(ceiling) is int and 1<=ceiling<=2100,'aware bounded automatic deadline required')
    local=now.astimezone(SHANGHAI);start=local.replace(hour=2,minute=0,second=0,microsecond=0);cutoff=local.replace(hour=5,minute=30,second=0,microsecond=0);end=local.replace(hour=6,minute=0,second=0,microsecond=0)
    require(start<=local<cutoff,'outside automatic admission window')
    seconds=min(ceiling,int((end-local).total_seconds())-2);require(seconds>=120,'insufficient automatic execution window');return seconds


def cycle_deadline(now,ceiling):
    limit=budget(now,ceiling);local=now.astimezone(SHANGHAI);end=local.replace(hour=6,minute=0,second=0,microsecond=0)
    seconds=min(limit,2090,int((end-local).total_seconds())-180)
    require(seconds>=120,'insufficient handoff and wakeup window');return seconds


def manager_budget(mode,automatic,now):
    require(mode in ('ACTUAL','SIMULATED') and type(automatic) is bool,'explicit manager admission kind required')
    return budget(now,2100) if mode=='ACTUAL' and automatic else 2100


def completion_budget(now,ceiling):
    """Existing candidate only: leave180seconds for bounded stop/cleanup/audit."""
    require(now.utcoffset() is not None and type(ceiling) is int and 1<=ceiling<=120,'aware bounded candidate-review deadline required')
    local=now.astimezone(SHANGHAI);start=local.replace(hour=2,minute=0,second=0,microsecond=0);end=local.replace(hour=6,minute=0,second=0,microsecond=0)
    require(start<=local<end and int((end-local).total_seconds())-182>=ceiling,'candidate review cannot finish within maintenance window');return ceiling
