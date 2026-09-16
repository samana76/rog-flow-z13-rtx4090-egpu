#!/usr/bin/python3
"""ALPM pre/post safeguards: build before transaction; never load a driver."""
import base64
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
import sys
import tempfile
import tarfile
import urllib.parse
import urllib.request
import registry

BASE = Path('/opt/gpd-egpu/update-support')
STATE = Path('/var/lib/gpd-egpu-updates')
SOURCE_HASH = 'e5545862c291f3991a91ee40dd9c7a71cccc69247a193d5e5b891bfd964ac104'
KERNELS = {'linux':'linux-headers', 'linux-cachyos':'linux-cachyos-headers'}
BOOT_NAMES = ('linux','linux-cachyos','linux-cachyos-lts')


def require(ok, message):
    if not ok: raise RuntimeError(message)

def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''): h.update(b)
    return h.hexdigest()

def run(argv, cwd=None, timeout=180, user=None):
    env=dict(os.environ,LC_ALL='C',LANG='C'); env.pop('LD_PRELOAD',None); env.pop('PYTHONPATH',None)
    if user: argv=['/usr/bin/runuser','-u',user,'--',*argv]
    print('$ '+' '.join(map(str,argv)),flush=True)
    r=subprocess.run(argv,cwd=cwd,env=env,capture_output=True,text=True,timeout=timeout)
    if r.stderr: print(r.stderr[-6000:],file=sys.stderr,flush=True)
    require(r.returncode==0,'Command failed ('+str(r.returncode)+'): '+repr(argv)+'\n'+r.stdout[-3000:])
    return r.stdout.strip()

def atomic(path, data):
    path=Path(path); temp=path.with_name(path.name+'.tmp')
    with temp.open('x') as f:
        json.dump(data,f,indent=2); f.write('\n'); f.flush(); os.fsync(f.fileno())
    temp.chmod(0o600); temp.replace(path)
    fd=os.open(path.parent,os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)

def installed(name):
    out=run(['/usr/bin/pacman','-Q',name]); fields=out.split()
    require(len(fields)==2 and fields[0]==name,'Ambiguous installed package: '+name)
    return fields[1]

def parse_plan(text):
    result={}
    for line in text.splitlines():
        if not line: continue
        fields=line.split('|')
        require(len(fields)==3 and re.fullmatch(r'[a-zA-Z0-9@._+-]+',fields[0]),'Unrecognized package plan output: '+line)
        name,version,url=fields
        require(name not in result,'Duplicate planned package')
        result[name]={'version':version,'url':url}
    return result

def plan():
    return parse_plan(run(['/usr/bin/pacman','-Sup','--print-format','%n|%v|%l']))

def check_invocation(argv):
    # Require the normal full repo upgrade, not -U, removals, alternate config,
    # selected repos/packages, IgnorePkg overrides, or a transaction we cannot identify.
    rest=list(argv[1:]); sync=upgrade=False
    while rest:
        a=rest.pop(0)
        if a=='--color':
            require(rest and rest.pop(0) in ('always','auto','never'),'Invalid color option'); continue
        if a in ('--noconfirm','--needed','--refresh','--sysupgrade','--sync'):
            sync |= a=='--sync'; upgrade |= a=='--sysupgrade'; continue
        if re.fullmatch('-[Syu]+',a):
            sync |= 'S' in a; upgrade |= 'u' in a; continue
        raise RuntimeError('Sensitive updates require a normal full upgrade: sudo pacman -Syu; unsupported argument '+a)
    require(sync and upgrade,'Sensitive updates require sudo pacman -Syu')

def pacman_parent():
    pid=os.getppid()
    for _ in range(12):
        p=Path('/proc')/str(pid)
        try:
            if (p/'exe').resolve()==Path('/usr/bin/pacman'):
                args=(p/'cmdline').read_bytes().decode().rstrip('\0').split('\0')
                check_invocation(args); return pid
            pid=int(re.search(r'^PPid:\s+(\d+)',(p/'status').read_text(),re.M)[1])
        except (OSError,TypeError): break
        if pid<=1: break
    raise RuntimeError('No supported pacman parent; direct pre/post invocation is forbidden')

def entries(text):
    found={}; current=None
    for line in text.splitlines():
        s=line.strip()
        if s.startswith('/'):
            current=s[2:] if s.startswith('//') and not s.startswith('///') and s[2:] in BOOT_NAMES else None
            if current:
                require(current not in found,'Duplicate normal boot entry'); found[current]={}
        elif current and ':' in s:
            k,v=s.split(':',1)
            if k in ('path','module_path','cmdline'):found[current][k]=v.strip()
    return found

DRIVER_PATTERN = r'(?:^|/)(?:nvidia(?:[-_](?:drm|modeset|uvm|peermem))?|nouveau)\.ko(?:\.|\s|$)'
BLOCKED_MODULES = ('nvidia','nvidia_uvm','nvidia_modeset','nvidia_drm','nvidia_peermem','nouveau')

def embedded_drivers(listing):
    return [line.strip() for line in listing.splitlines() if re.search(DRIVER_PATTERN,line)]

def validate_dependency_report(text):
    lines=[x.strip() for x in text.splitlines() if x.strip()]
    require('install /usr/bin/false' in lines,'Embedded install-block did not win')
    for line in lines:
        if line.startswith('install '):
            require(line=='install /usr/bin/false','Unexpected embedded install command')
        elif line.startswith('insmod '):
            require(not re.search(DRIVER_PATTERN,line),'Embedded policy would insert a display driver: '+line)
        else:
            raise RuntimeError('Unexpected module dependency output: '+line)

def image_config_files(root):
    # Match kmod directory precedence; same basename at higher priority masks lower.
    chosen={}
    for relative in ('etc/modprobe.d','run/modprobe.d','usr/local/lib/modprobe.d','usr/lib/modprobe.d','lib/modprobe.d'):
        directory=root/relative
        if not directory.exists():continue
        require(directory.resolve().is_relative_to(root.resolve()),'Embedded configuration directory escapes image')
        for p in sorted(directory.glob('*.conf')):
            if p.name in chosen:continue
            if p.is_symlink() and os.readlink(p)=='/dev/null':
                chosen[p.name]='';continue
            require(p.resolve().is_relative_to(root.resolve()) and p.is_file(),'Embedded config escapes image')
            text=p.read_text()
            require(not re.search(r'^\s*include\s',text,re.M),'Embedded config include requires review')
            chosen[p.name]=text
    return chosen

def check_embedded_forced_loads(root):
    import shlex
    config=root/'config'
    if config.exists():
        require(config.resolve().is_relative_to(root.resolve()),'Config escapes image')
        text=config.read_text()
        matches=re.findall(r'^\s*MODULES=\((.*?)\)',text,re.M|re.S)
        require(len(matches)<=1,'Ambiguous embedded MODULES configuration')
        for value in matches:
            require(not any(x in value for x in ('$','`')),'Dynamic embedded MODULES requires review')
            names=shlex.split(value)
            require(not any(n.rstrip('?').replace('-','_') in BLOCKED_MODULES for n in names),'Display driver explicitly requested in embedded MODULES')
    for relative in ('etc/modules-load.d','run/modules-load.d','usr/lib/modules-load.d'):
        directory=root/relative
        if not directory.exists():continue
        require(directory.resolve().is_relative_to(root.resolve()),'modules-load directory escapes image')
        for p in directory.glob('*.conf'):
            if p.is_symlink() and os.readlink(p)=='/dev/null':continue
            require(p.resolve().is_relative_to(root.resolve()),'modules-load config escapes image')
            names=[x.split('#',1)[0].strip().replace('-','_') for x in p.read_text().splitlines()]
            require(not set(names)&set(BLOCKED_MODULES),'Display driver explicitly requested by '+str(p))

def verify_image_policy(image,listing):
    matches=embedded_drivers(listing)
    if not matches:return {'drivers':[],'policy':'no-display-driver-payload'}
    print('Embedded display-driver payloads: '+repr(matches),flush=True)
    releases=set(re.findall(r'(?:^|/)lib/modules/([^/\s]+)/',listing,re.M))
    require(len(releases)==1,'Ambiguous initramfs kernel release')
    kernel=releases.pop()
    require(re.fullmatch(r'[A-Za-z0-9_.+-]+',kernel),'Invalid embedded kernel release')
    work=Path(tempfile.mkdtemp(prefix='gpd-egpu-initramfs-check-',dir='/var/tmp'))
    try:
        shutil.copyfile(image,work/'image'); (work/'image').chmod(0o600)
        extracted=work/'extracted';extracted.mkdir()
        configs=work/'effective-modprobe.d';configs.mkdir()
        account=pwd.getpwnam('nobody')
        for p in (work,work/'image',extracted,configs):os.chown(p,account.pw_uid,account.pw_gid)
        # Extract only as an unprivileged user. Never execute files from the image.
        run(['/usr/bin/lsinitcpio','-x',str(work/'image')],cwd=extracted,user='nobody',timeout=180)
        check_embedded_forced_loads(extracted)
        for name,text in image_config_files(extracted).items():
            p=configs/name;p.write_text(text);p.chmod(0o600);os.chown(p,account.pw_uid,account.pw_gid)
        command=['/usr/bin/modprobe','--config',str(configs),'--dirname',str(extracted),'--set-version',kernel]
        effective=run([*command,'--showconfig'],user='nobody')
        for module in BLOCKED_MODULES:
            require(re.search(r'^blacklist\s+'+re.escape(module)+r'\s*$',effective,re.M),'Embedded blacklist missing: '+module)
            # --show-depends prints install directives and dependency paths only;
            # it cannot execute install commands or insert/remove a module.
            report=run([*command,'--show-depends',module],user='nobody')
            validate_dependency_report(report)
        print('PASS: embedded display modules are blocked by the effective initramfs policy; no module load performed.',flush=True)
        return {'drivers':matches,'policy':'blacklist-and-install-false-verified'}
    finally:
        shutil.rmtree(work)


def boot_check(check_init=False):
    found=entries(Path('/boot/limine.conf').read_text()); result={}
    for name in ('linux','linux-cachyos'):
        require(name in found,'Missing fallback boot entry: '+name)
        e=found[name]; cmd=e.get('cmdline','').split()
        require('rootflags=subvol=/@' in cmd and 'amdgpu.dcdebugmask=0x40600' in cmd,'Normal root/AMD parameters changed')
        result[name]={}
        for key in ('path','module_path'):
            match=re.fullmatch(r'boot\(\):(/[^#]+)#([0-9a-f]{128})',e.get(key,''))
            require(match is not None,'Unrecognized checksummed boot resource')
            relative=Path(match[1].lstrip('/'))
            require('..' not in relative.parts,'Boot path traversal')
            p=Path('/boot')/relative
            require(p.resolve().is_relative_to('/boot'),'Boot resource leaves /boot')
            h=hashlib.blake2b()
            with p.open('rb') as f:
                for b in iter(lambda:f.read(1048576),b''):h.update(b)
            require(h.hexdigest()==match[2],'Boot checksum mismatch: '+str(p))
            result[name][key]={'path':str(p),'sha256':sha(p)}
            if check_init and key=='module_path':
                listing=run(['/usr/bin/lsinitcpio','-l',str(p)],timeout=120)
                result[name][key]['load_policy']=verify_image_policy(p,listing)
    return result

def policy_check(updates, records):
    for name in ('nvidia-utils','opencl-nvidia'):
        if name in updates:
            require(updates[name]['version']==installed(name),name+' update needs driver compatibility review; no automatic NVIDIA release transition')
    require(installed('nvidia-utils')=='615.71.09-1','NVIDIA userspace differs from approved driver')
    if 'nvidia-open' in updates:
        require(updates['nvidia-open']['version'].rsplit('-',1)[0]=='615.71.09','New NVIDIA driver release needs review')
    require(not any(n in updates for n in ('nvidia','nvidia-dkms','nvidia-open-dkms')),'Unreviewed NVIDIA driver package transition')
    fallback=[k for k,v in records.items() if v['validation']=='previously-tested' and v['package'] not in updates and installed(v['package'])==v['package_version'] and (Path('/usr/lib/modules')/k).is_dir()]
    require(fallback,'Transaction replaces every tested eGPU kernel. Keep one tested kernel unchanged; do not force or partially upgrade around this check.')
    return fallback

def download(url,path):
    require(urllib.parse.urlparse(url).scheme=='https','Only HTTPS package downloads are supported')
    with urllib.request.urlopen(url,timeout=60) as response, Path(path).open('xb') as f:
        require(urllib.parse.urlparse(response.url).scheme=='https','Insecure package redirect')
        shutil.copyfileobj(response,f)

def parse_desc(text):
    fields={}
    for block in text.strip().split('\n\n'):
        lines=block.splitlines()
        if lines and re.fullmatch('%[A-Z0-9_]+%',lines[0]):
            fields[lines[0].strip('%')]='\n'.join(lines[1:])
    return fields

def header_metadata(name,version):
    repos=run(['/usr/bin/pacman-conf','--repo-list']).splitlines()
    for repo in repos:
        require(re.fullmatch(r'[A-Za-z0-9_.+-]+',repo),'Invalid repo identifier')
        db=Path('/var/lib/pacman/sync')/(repo+'.db')
        if not db.exists():continue
        with tarfile.open(db) as archive:
            for member in archive:
                if member.name.startswith(name+'-') and member.name.endswith('/desc') and member.isfile():
                    fields=parse_desc(archive.extractfile(member).read().decode())
                    if fields.get('NAME')!=name:continue
                    require(fields['VERSION']==version,'Highest priority headers do not match target kernel package')
                    require(re.fullmatch(r'[A-Za-z0-9_.+:-]+',fields['FILENAME']) and fields['FILENAME'].endswith('.pkg.tar.zst'),'Invalid header archive name')
                    require(re.fullmatch('[0-9a-f]{64}',fields['SHA256SUM']),'Missing header checksum')
                    servers=run(['/usr/bin/pacman-conf','--repo',repo,'Server']).splitlines()
                    return fields,[x.rstrip('/')+'/'+fields['FILENAME'] for x in servers if x.startswith('https://')]
    raise RuntimeError('Matching signed header metadata unavailable: '+name)

def header_package(name,version,work):
    fields,urls=header_metadata(name,version)
    package=work/'headers.pkg.tar.zst'; sig=work/'headers.sig'
    sig.write_bytes(base64.b64decode(fields['PGPSIG'],validate=True))
    error=None
    for url in urls[:3]:
        try:
            download(url,package)
            require(sha(package)==fields['SHA256SUM'],'Headers checksum differs from repository metadata')
            run(['/usr/bin/pacman-key','--verify',str(sig),str(package)],timeout=120)
            return package
        except Exception as exc:
            error=exc
            if package.exists():package.unlink()
    raise RuntimeError('Unable to obtain verified headers: '+str(error))

def modmeta(p):
    r={'sha256':sha(p)}
    for field in ('version','vermagic','srcversion','license'):
        r[field]=run(['/usr/bin/modinfo','-F',field,str(p)])
    return r

def build(pkg,version,attempt):
    work=Path(tempfile.mkdtemp(prefix='gpd-egpu-build-',dir='/var/tmp'))
    print('Build workspace: '+str(work),flush=True)
    succeeded=False
    try:
        archive=header_package(KERNELS[pkg],version,work)
        shutil.copy2(BASE/'vendor.run',work/'vendor.run')
        require(sha(work/'vendor.run')==SOURCE_HASH,'Vendor source archive changed')
        account=pwd.getpwnam('nobody')
        for p in work.iterdir():os.chown(p,account.pw_uid,account.pw_gid)
        os.chown(work,account.pw_uid,account.pw_gid)
        # All archive extraction and compilation occur with unprivileged UID.
        run(['/usr/bin/mkdir','headers'],cwd=work,user='nobody')
        run(['/usr/bin/bsdtar','-xf',str(archive),'-C','headers'],cwd=work,user='nobody')
        trees=list((work/'headers/usr/lib/modules').glob('*/build'))
        require(len(trees)==1,'Ambiguous header kernel tree')
        headers=trees[0]; kernel=(headers/'include/config/kernel.release').read_text().strip()
        require(headers.parent.name==kernel and re.fullmatch(r'[A-Za-z0-9_.+-]+',kernel),'Header kernel release mismatch')
        run(['/usr/bin/sh',str(work/'vendor.run'),'--extract-only','--target',str(work/'vendor')],cwd=work,user='nobody',timeout=180)
        source=work/'vendor/kernel'
        require(source.is_dir(),'Proprietary vendor kernel source missing')
        config=(headers/'.config').read_text()
        args=['/usr/bin/make','-j'+str(min(8,os.cpu_count() or 1)),'modules','SYSSRC='+str(headers),'SYSOUT='+str(headers),'KERNEL_UNAME='+kernel]
        if 'CONFIG_CC_IS_CLANG=y' in config:args+=['LLVM=1','CC=clang','LD=ld.lld']
        log=attempt/(kernel+'-build.log')
        with log.open('w') as f:
            r=subprocess.run(['/usr/bin/runuser','-u','nobody','--',*args],cwd=source,stdout=f,stderr=subprocess.STDOUT,timeout=1800,env={'PATH':'/usr/bin:/bin','HOME':str(work),'LC_ALL':'C'})
        require(r.returncode==0,'Module build failed; packages were not upgraded. See '+str(log))
        modules={n:modmeta(source/n) for n in registry.MODULES}
        require(modules['nvidia.ko']['license']=='NVIDIA' and modules['nvidia-modeset.ko']['license']=='NVIDIA','Not the proprietary driver')
        dest=Path('/opt/gpd-egpu/615.71.09')/kernel
        record={'package':pkg,'package_version':version,'payload':str(dest),'display_payload':str(dest),'modules':modules,'validation':'built-not-runtime-tested'}
        registry.validate({'schema':1,'driver':registry.DRIVER,'kernels':{kernel:record}})
        require(not dest.exists(),'Payload already exists; refusing overwrite: '+str(dest))
        dest.mkdir(mode=0o700)
        for n in registry.MODULES:
            require(not (source/n).is_symlink(),'Unexpected module symlink')
            shutil.copyfile(source/n,dest/n); (dest/n).chmod(0o600)
            require(sha(dest/n)==modules[n]['sha256'],'Module copy hash mismatch')
        atomic(attempt/(kernel+'-build.json'), {'kernel':kernel,'package':pkg,'package_version':version,'headers_sha256':sha(archive),'vendor_sha256':SOURCE_HASH,'command':args,'modules':modules})
        succeeded=True
        return kernel,record
    finally:
        if succeeded:
            shutil.rmtree(work)
        else:
            print('Failed build workspace retained for review: '+str(work),flush=True)

def baseline_integrity():
    for p,h in json.loads((BASE/'installed-hashes.json').read_text()).items():
        require(sha(p)==h,'Installed update/driver helper changed: '+p)

def pre(targets):
    parent=pacman_parent(); baseline_integrity()
    require(not (STATE/'pending.json').exists(),'Previous update requires review: '+str(STATE/'pending.json'))
    updates=plan()
    require(set(targets)<=set(updates),'Hook targets differ from full repo upgrade plan')
    records=registry.read(); fallbacks=policy_check(updates,records)
    before=boot_check(check_init=True)
    token=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+str(parent)
    attempt=STATE/token; attempt.mkdir(mode=0o700)
    # A Btrfs root snapshot does not include this machine's separate FAT /boot.
    needed=sum(p.stat().st_size for p in Path('/boot').rglob('*') if p.is_file())
    require(shutil.disk_usage(STATE).free>needed+3*1024**3,'Insufficient room for boot backup/build')
    shutil.copytree('/boot',attempt/'boot',symlinks=True)
    for e in before.values():
        for r in e.values():require(sha(attempt/'boot'/Path(r['path']).relative_to('/boot'))==r['sha256'],'Boot backup verification failed')
    snapshot=run(['/usr/bin/snapper','--no-dbus','-c','root','create','--type','single','--print-number','--description','eGPU managed update '+token])
    require(snapshot.isdecimal(),'Snapshot creation did not return an ID')
    pending={'stage':'building','pacman_pid':parent,'plan':updates,'targets':sorted(targets),'fallbacks':fallbacks,'boot_before':before,'snapshot':snapshot,'attempt':str(attempt),'new':{}}
    atomic(STATE/'pending.json',pending)
    for pkg in sorted(set(updates)&set(KERNELS)):
        version=updates[pkg]['version']
        if any(v['package']==pkg and v['package_version']==version for v in records.values()):continue
        k,r=build(pkg,version,attempt); pending['new'][k]=r; atomic(STATE/'pending.json',pending)
    require(plan()==updates,'Repository plan changed during build; no package upgrade authorized')
    pending['stage']='prepared'; atomic(STATE/'pending.json',pending)
    print('eGPU PRECHECK PASSED: modules staged, snapshot '+snapshot+', boot backup '+str(attempt/'boot')+'. No driver load; post-transaction verification still required.',flush=True)

def post():
    parent=pacman_parent(); pending=json.loads((STATE/'pending.json').read_text())
    require(pending['pacman_pid']==parent and pending['stage']=='prepared','Unmatched update transaction')
    baseline_integrity()
    for name,row in pending['plan'].items():require(installed(name)==row['version'],'Installed package differs from prepared transaction: '+name)
    boot_check(check_init=True)
    records=registry.read()
    for kernel,row in pending['new'].items():
        require((Path('/usr/lib/modules')/kernel).is_dir(),'Target kernel module tree missing')
        for n,m in row['modules'].items():require(sha(Path(row['payload'])/n)==m['sha256'],'Candidate payload changed')
    for kernel in pending['fallbacks']:
        r=records[kernel]
        require(installed(r['package'])==r['package_version'],'Fallback kernel package changed')
        for key,old in pending['boot_before'][r['package']].items():
            # Unchanged fallback kernel image must remain identical. Initramfs may be
            # legitimately regenerated; boot_check has verified its new checksum/content.
            if key=='path':require(sha(old['path'])==old['sha256'],'Fallback kernel image changed')
    records.update(pending['new'])
    atomic(BASE/'registry.json',{'schema':1,'driver':registry.DRIVER,'kernels':records})
    pending['stage']='completed'; atomic(Path(pending['attempt'])/'receipt.json',pending)
    (STATE/'pending.json').unlink()
    print('eGPU UPDATE VERIFIED. New builds are not yet runtime-tested. Reboot manually when ready; use a retained tested kernel if needed. No activation or reboot was performed.',flush=True)

def main():
    require(os.geteuid()==0,'Root required')
    require(sys.argv[1:] in (['pre'],['post'],['status']),'Use pre/post hooks or status')
    os.umask(0o077); STATE.mkdir(mode=0o700,parents=True,exist_ok=True)
    lock=open(STATE/'update.lock','a'); fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if sys.argv[1]=='status':
        print(json.dumps({'kernels':registry.read(),'pending':json.loads((STATE/'pending.json').read_text()) if (STATE/'pending.json').exists() else None},indent=2)); return
    if sys.argv[1]=='pre':pre([s.strip() for s in sys.stdin if s.strip()])
    else:post()

if __name__=='__main__':
    try:main()
    except Exception as e:
        print('EGPU UPDATE STOP: '+str(e)+'\nDo not reboot after a post-transaction failure. Evidence: '+str(STATE)+'. No recovery, driver loading or reboot attempted.',file=sys.stderr,flush=True)
        raise SystemExit(1)
