"""Fixed operator entry for the original maintenance protocol and lock.

No compose fallback, approval generation, model tool or HTTP endpoint exists.
Canonical ACTUAL host capability and root-issued permission gates still apply.
"""
import argparse,json
from .audit import require,hash_value
from .product_runtime import LinuxProductHost
from .product_bootstrap import prepare_bootstrap
from .product_release import NativeProductRelease
from .product_lineage import retire as retire_previous


def execute(action,*,host_path,host_sha256,control_path=None,control_sha256=None,control_approval_path=None,control_approval_sha256=None,rollback_lease_path=None,rollback_lease_sha256=None):
    require(action in ('prepare','activate','rollback','retire') and host_path is not None and hash_value(host_sha256),'fixed product operator action required')
    require((rollback_lease_path is None)==(rollback_lease_sha256 is None) and (rollback_lease_path is None or action=='rollback' and hash_value(rollback_lease_sha256)),'rollback-only operator lease required')
    control=(control_path,control_sha256,control_approval_path,control_approval_sha256)
    if action in ('prepare','retire'):require(all(v is None for v in control),'preparation or retirement cannot receive release controls')
    else:require(all(v is not None for v in control) and hash_value(control_sha256) and hash_value(control_approval_sha256),'complete sealed product controls required')
    host=LinuxProductHost(host_path,host_sha256,rollback_lease_path=rollback_lease_path,rollback_lease_sha256=rollback_lease_sha256)
    if action=='prepare':return prepare_bootstrap(host.ledger,host.plan,host)
    with host.lock(host.plan):
        if action=='retire':return retire_previous(host)
        controller=NativeProductRelease(host,control_path,control_sha256,control_approval_path,control_approval_sha256)
        return controller.activate() if action=='activate' else controller.rollback()


def main(argv=None):
    parser=argparse.ArgumentParser(description='Fixed root-approved Myink product protocol entry')
    parser.add_argument('action',choices=('prepare','activate','rollback','retire'))
    for flag in ('host-config','host-sha256','control-config','control-sha256','control-approval','control-approval-sha256','rollback-lease','rollback-lease-sha256'):
        parser.add_argument('--'+flag,required=flag.startswith('host-'))
    args=parser.parse_args(argv)
    try:
        result=execute(args.action,host_path=args.host_config,host_sha256=args.host_sha256,control_path=args.control_config,control_sha256=args.control_sha256,control_approval_path=args.control_approval,control_approval_sha256=args.control_approval_sha256,rollback_lease_path=args.rollback_lease,rollback_lease_sha256=args.rollback_lease_sha256)
        print(json.dumps(dict(operation_id=result.operation_id,status=result.status,phase=result.evidence.get('phase'),model_requests=0)))
        return 0 if result.status=='done' else 1
    except Exception as error:
        # The canonical ledger retains the actual pending/uncertain stage.
        # Never expose private file paths or label an unknown effect as blocked.
        print(json.dumps(dict(status='unconfirmed',error_class=type(error).__name__,model_requests=0)));return 1


if __name__=='__main__':raise SystemExit(main())
