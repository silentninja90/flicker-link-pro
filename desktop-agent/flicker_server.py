
"""Fresh Flicker Link Pro MCP runtime. Tool signatures are defined in tool_catalog.json."""
from __future__ import annotations
import argparse, base64, collections, datetime, fnmatch, hashlib, http.server, json, os, pathlib, re, shutil, socket, subprocess, sys, threading, time, uuid, zipfile, hmac
from urllib.parse import urlsplit
from concurrent.futures import ThreadPoolExecutor

HERE=pathlib.Path(__file__).resolve().parent
CATALOG=json.loads((HERE/'tool_catalog.json').read_text(encoding='utf-8'))
ROOT=pathlib.Path(os.getenv('FLICKER_STATE_DIR',str(pathlib.Path.home()/'.flicker-link-pro')))
ROOT.mkdir(parents=True,exist_ok=True)
JOBS={}
SEARCHES={}
CALLS=collections.deque(maxlen=1000)
LOCK=threading.RLock()
CONFIG={'response_chunk_chars':65536,'auto_create_parents':True}
def path(p):return pathlib.Path(p).expanduser()
def require_keys(a,*names):
    for n in names:
        if n not in a:raise ValueError('Missing required argument: '+n)
def ensure_parent(p):p.parent.mkdir(parents=True,exist_ok=True)
def text_read(p):return path(p).read_text(encoding='utf-8',errors='replace')
def write_data(p,data,append=False):
    p=path(p);ensure_parent(p)
    with p.open('ab' if append else 'wb') as f:f.write(data)
    return {'path':str(p),'bytes_written':len(data)}
def entries(p):
    return [{'name':q.name,'path':str(q),'is_dir':q.is_dir(),'size':q.stat().st_size if q.is_file() else 0} for q in sorted(path(p).iterdir())]
def process_list():
    import psutil
    return [dict(p.info) for p in psutil.process_iter(['pid','name','username','status','cpu_percent','memory_percent'],ad_value=None)]
def psutil():
    import psutil
    return psutil
def launch(command,cwd=None):
    import subprocess
    kwargs={'cwd':cwd,'stdout':subprocess.PIPE,'stderr':subprocess.STDOUT,'stdin':subprocess.PIPE,'text':True,'bufsize':1}
    if os.name=='nt':kwargs['creationflags']=subprocess.CREATE_NEW_PROCESS_GROUP
    else:kwargs['start_new_session']=True
    proc=subprocess.Popen(command,shell=True,**kwargs)
    job='job_'+uuid.uuid4().hex
    record={'session_id':job,'command':command,'pid':proc.pid,'status':'running','output':'','process':proc,'created_at':time.time()}
    with LOCK:JOBS[job]=record
    def collect():
        try:
            for line in proc.stdout:
                with LOCK:record['output']+=line
            code=proc.wait()
            with LOCK:record.update(status='finished' if code==0 else 'failed',exit_code=code)
        except Exception as exc:
            with LOCK:record.update(status='failed',error=str(exc))
    threading.Thread(target=collect,daemon=True).start()
    return {'session_id':job,'pid':proc.pid,'status':'running'}
def job_result(a):
    j=JOBS[a['session_id']]
    if 'input' in a and j['process'].poll() is None:
        j['process'].stdin.write(a['input']);j['process'].stdin.flush()
    offset=max(0,int(a.get('offset',0)));limit=int(a.get('length',65536))
    output=j['output'];chunk=output[offset:] if limit==0 else output[offset:offset+limit]
    return {'session_id':j['session_id'],'status':j['status'],'pid':j['pid'],'exit_code':j.get('exit_code'),'output':chunk,'next_offset':offset+len(chunk) if offset+len(chunk)<len(output) else None}
def search_start(a):
    sid='search_'+uuid.uuid4().hex
    rec={'search_id':sid,'status':'running','hits':[],'stop':False,'scanned':0}
    with LOCK:SEARCHES[sid]=rec
    def worker():
        try:
            root=path(a['root'])
            files=[root] if root.is_file() else (p for p in root.rglob('*') if p.is_file())
            query=a.get('content_query','');pattern=a.get('filename_pattern','*')
            for f in files:
                if rec['stop']:break
                rec['scanned']+=1
                if not fnmatch.fnmatch(f.name,pattern):continue
                if not query:rec['hits'].append({'path':str(f),'line':0});continue
                try:
                    for i,line in enumerate(f.open(encoding='utf-8',errors='replace'),1):
                        match=(re.search(query,line,re.I if a.get('ignore_case',True) else 0) if a.get('regex') else query.lower() in line.lower() if a.get('ignore_case',True) else query in line)
                        if match:rec['hits'].append({'path':str(f),'line':i,'preview':line.strip()[:1000]})
                except OSError:pass
            rec['status']='stopped' if rec['stop'] else 'finished'
        except Exception as e:rec.update(status='failed',error=str(e))
    threading.Thread(target=worker,daemon=True).start()
    return {'search_id':sid,'status':'running'}
def ui():
    import pyautogui
    return pyautogui
def perform(n,a):
    if n in ('who_am_i','list_devices'):
        info={'hostname':socket.gethostname(),'user':os.getenv('USERNAME') or os.getenv('USER'),'platform':sys.platform}
        return {'devices':[info]} if n=='list_devices' else info
    if n=='get_config':return {'configuration':dict(CONFIG)}
    if n=='set_config':
        vals=a['values']
        if set(vals)-set(CONFIG):raise ValueError('Unsupported configuration key')
        CONFIG.update(vals);return {'configuration':dict(CONFIG)}
    if n in ('path_info','get_file_info'):
        p=path(a['path']);s=p.stat();return {'path':str(p),'exists':True,'is_file':p.is_file(),'is_dir':p.is_dir(),'size_bytes':s.st_size,'modified_at':s.st_mtime}
    if n in ('browse_directory','list_directory'):
        e=entries(a['path']);offset=int(a.get('offset',0));size=int(a.get('page_size',200));return {'items':e[offset:] if size==0 else e[offset:offset+size],'total':len(e)}
    if n=='list_drives':return {'drives':[f'{c}:\\' for c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' if pathlib.Path(f'{c}:\\').exists()]}
    if n in ('read_file_text','read_file'): 
        if n=='read_file_text':return {'content':text_read(a['path'])}
        p=path(a['path']);off=int(a.get('offset',0));length=int(a.get('length',65536))
        with p.open('rb') as f:f.seek(off);raw=f.read(length if length else -1)
        return {'content':None if a.get('base64') else raw.decode('utf-8','replace'),'content_base64':base64.b64encode(raw).decode() if a.get('base64') else None,'offset':off,'total_bytes':p.stat().st_size}
    if n=='read_multiple_files':return {'files':[perform('read_file',{'path':p,'offset':a.get('offset',0),'length':a.get('length',65536),'base64':a.get('base64',False)}) for p in a['paths']]}
    if n=='read_file_base64_chunk':
        with path(a['path']).open('rb') as f:f.seek(a['offset']);data=f.read(a['length'])
        return {'base64_chunk':base64.b64encode(data).decode(),'bytes_read':len(data)}
    if n in ('write_file_text','write_file','write_file_base64_chunk'):
        if n=='write_file_text':return write_data(a['path'],a['content'].encode())
        if n=='write_file_base64_chunk':return write_data(a['path'],base64.b64decode(a['base64_data']),a.get('append',False))
        data=base64.b64decode(a['content_base64']) if 'content_base64' in a else a['content'].encode()
        mode=a.get('mode','overwrite')
        if mode=='create' and path(a['path']).exists():raise FileExistsError(a['path'])
        if mode=='at_offset':
            with path(a['path']).open('r+b') as f:f.seek(a['offset']);f.write(data)
            return {'status':'written','bytes_written':len(data)}
        return write_data(a['path'],data,mode=='append')
    if n=='edit_block':
        s=text_read(a['path']);count=s.count(a['old_text']);expected=a.get('expected_matches',1)
        if count!=expected:raise ValueError(f'Expected {expected} matches, found {count}')
        return write_data(a['path'],s.replace(a['old_text'],a['new_text']).encode())
    if n=='create_directory':path(a['path']).mkdir(parents=True,exist_ok=True);return {'status':'created'}
    if n in ('copy_item','move_item','move_file'):
        src=path(a['src']);dst=path(a['dst']);ensure_parent(dst)
        if n=='copy_item':
            shutil.copytree(src,dst) if src.is_dir() else shutil.copy2(src,dst)
        else:shutil.move(src,dst)
        return {'status':'success','destination':str(dst)}
    if n=='delete_item':
        p=path(a['path']);shutil.rmtree(p) if p.is_dir() else p.unlink();return {'status':'deleted'}
    if n=='checksum_sha256':
        h=hashlib.sha256()
        with path(a['path']).open('rb') as f:
            for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
        return {'sha256':h.hexdigest()}
    if n in ('create_zip','create_project_backup'):
        src=path(a['source_dir'] if n=='create_zip' else a['source_folder'])
        dest=path(a['zip_path']) if n=='create_zip' else path(a['backup_vault'])/(f'backup_{src.name}_{int(time.time())}.zip')
        ensure_parent(dest)
        with zipfile.ZipFile(dest,'w',zipfile.ZIP_DEFLATED) as z:
            for p in src.rglob('*'):
                if p.is_file():z.write(p,p.relative_to(src))
        return {'archive_path':str(dest),'bytes':dest.stat().st_size}
    if n=='unzip_to_folder':
        dest=path(a['extract_to']).resolve()
        with zipfile.ZipFile(a['zip_path']) as z:
            for item in z.infolist():
                target=(dest/item.filename).resolve()
                if not target.is_relative_to(dest):raise ValueError('Unsafe ZIP member')
            z.extractall(dest)
        return {'status':'extracted'}
    if n in ('run_code','start_process'):return launch(a['command'],a.get('working_directory'))
    if n=='run_wsl':
        import shlex
        cmd=a['command'];wd=a.get('wsl_working_directory')
        if wd:cmd=f'cd {shlex.quote(wd)} && {cmd}'
        return launch('wsl.exe bash -lc '+subprocess.list2cmdline([cmd]))
    if n=='interact_with_process':return job_result(a)
    if n=='list_sessions':return {'sessions':[{k:v for k,v in j.items() if k not in ('process','output')} for j in JOBS.values()]}
    if n in ('process_list','list_processes'):return {'processes':process_list()}
    if n in ('process_kill','kill_process','force_terminate','shutdown'):
        pid=a.get('pid');sid=a.get('session_id')
        if sid:pid=JOBS[sid]['pid']
        if not sid and not a.get('confirm',False) and n!='process_kill':raise ValueError('confirm=true required for arbitrary PID')
        if pid is None:raise ValueError('pid or session_id required')
        psutil().Process(int(pid)).terminate()
        if sid:JOBS[sid]['status']='terminated'
        return {'status':'termination-requested','pid':pid}
    if n=='system_resources':
        ps=psutil();return {'cpu_percent':ps.cpu_percent(.1),'memory':ps.virtual_memory()._asdict(),'disk':shutil.disk_usage(path.home())._asdict()}
    if n=='network_info':
        return {'hostname':socket.gethostname(),'addresses':psutil().net_if_addrs().__str__()}
    if n in ('docker_containers','docker_action'):
        cmd=['docker','ps','-a','--format','{{json .}}'] if n=='docker_containers' else ['docker',a['action'],a['container_name_or_id']]
        r=subprocess.run(cmd,capture_output=True,text=True,timeout=30)
        return {'stdout':r.stdout,'stderr':r.stderr,'returncode':r.returncode}
    if n=='read_application_logs':
        lines=collections.deque(path(a['log_path']).open(encoding='utf-8',errors='replace'),maxlen=int(a.get('tail_lines',100)))
        return {'log_segment':''.join(lines)}
    if n=='search_filename':return {'matches':[str(p) for p in path(a['root_dir']).rglob(a['filename']) if p.is_file() and p.name==a['filename']]}
    if n=='start_search':return search_start(a)
    if n=='get_more_search_results':
        rec=SEARCHES[a['search_id']];off=int(a.get('offset',0));size=int(a.get('page_size',100))
        return {'search_id':a['search_id'],'status':rec['status'],'results':rec['hits'][off:] if size==0 else rec['hits'][off:off+size],'scanned':rec['scanned']}
    if n=='list_searches':return {'searches':[{k:v for k,v in r.items() if k!='hits'} for r in SEARCHES.values()]}
    if n=='stop_search':SEARCHES[a['search_id']]['stop']=True;return {'status':'stop-requested'}
    if n=='db_execute':
        import psycopg2
        with psycopg2.connect(a['connection_string']) as db:
            with db.cursor() as cur:
                cur.execute(a['sql'])
                return {'results':[dict(zip([x[0] for x in cur.description],row)) for row in cur.fetchall()]} if cur.description else {'status':'executed'}
    if n in ('download_file_https','upload_file_https_put'):
        import requests
        u=a['url']
        if urlsplit(u).scheme!='https':raise ValueError('HTTPS required')
        if n=='download_file_https':
            r=requests.get(u,timeout=120);r.raise_for_status();return write_data(a['save_path'],r.content)
        with path(a['file_path']).open('rb') as f:r=requests.put(u,data=f,timeout=120);r.raise_for_status()
        return {'status':'uploaded','http_status':r.status_code}
    if n in ('window_list','window_action','focus_and_type','keyboard_type','keyboard_press','mouse_move','click','screenshot'):
        p=ui()
        if n=='window_list':return {'windows':[{'title':w.title,'box':[w.left,w.top,w.width,w.height]} for w in p.getAllWindows() if w.title]}
        if n=='window_action':
            w=p.getWindowsWithTitle(a['window_title'])[0];getattr(w,a['action'])();return {'status':'done'}
        if n=='focus_and_type':
            w=p.getWindowsWithTitle(a['window_title'])[0];w.activate();p.hotkey(*a['keys_to_send']);return {'status':'done'}
        if n=='keyboard_type':p.write(a['text'],interval=a.get('interval',0));return {'status':'done'}
        if n=='keyboard_press':p.hotkey(*a['keys']);return {'status':'done'}
        if n=='mouse_move':p.moveTo(a['x'],a['y'],duration=a.get('duration',0));return {'status':'done'}
        if n=='click':p.click(a['x'],a['y']);return {'status':'done'}
        if n=='screenshot':
            b=__import__('io').BytesIO();p.screenshot().save(b,format='PNG')
            return {'_image_base64':base64.b64encode(b.getvalue()).decode(),'status':'captured'}
    if n=='write_pdf':
        from reportlab.platypus import SimpleDocTemplate,Paragraph
        from reportlab.lib.styles import getSampleStyleSheet
        from xml.sax.saxutils import escape
        dest=path(a['path']);ensure_parent(dest)
        SimpleDocTemplate(str(dest)).build([Paragraph(escape(x),getSampleStyleSheet()['Normal']) for x in a['content'].split('\n')])
        return {'status':'written','path':str(dest)}
    if n in ('get_recent_tool_calls','list_remote_tool_calls'):
        off=int(a.get('offset',0));size=int(a.get('page_size',100));return {'calls':list(CALLS)[off:off+size]}
    if n=='get_tool_result':
        for c in CALLS:
            if c['id']==a['call_id']:return c
        raise KeyError('Call not found')
    if n=='review_device_call':return perform('get_tool_result',a)
    if n=='get_usage_stats':return {'local_calls':len(CALLS),'jobs':len(JOBS),'searches':len(SEARCHES)}
    if n=='keep_tool_result':
        p=ROOT/('saved_'+uuid.uuid4().hex+'.txt')
        write_data(p,a.get('content','').encode());return {'path':str(p)}
    if n=='track_ui_event':return {'status':'noted','event_type':a['event_type']}
    raise NotImplementedError(n)

def handle(req):
    method=req.get('method');rid=req.get('id')
    if method=='initialize':
        return {'jsonrpc':'2.0','id':rid,'result':{'protocolVersion':'2025-03-26','capabilities':{'tools':{'listChanged':False}},'serverInfo':{'name':'flicker-link-pro','version':'2.0.0'}}}
    if method=='ping':return {'jsonrpc':'2.0','id':rid,'result':{}}
    if method=='tools/list':return {'jsonrpc':'2.0','id':rid,'result':{'tools':CATALOG}}
    if method=='tools/call':
        p=req.get('params') or {};name=p.get('name');args=p.get('arguments') or {}
        if name not in {t['name'] for t in CATALOG}:return {'jsonrpc':'2.0','id':rid,'error':{'code':-32602,'message':'Unknown tool'}}
        started=time.monotonic();call='call_'+uuid.uuid4().hex
        try:
            result=perform(name,args)
            image_data=result.pop('_image_base64',None)
            content=[{'type':'text','text':json.dumps(result,default=str)}]
            if image_data:content.append({'type':'image','data':image_data,'mimeType':'image/png'})
            out={'content':content,'structuredContent':result}
            status='success'
        except Exception as exc:
            status='failed';out={'isError':True,'content':[{'type':'text','text':type(exc).__name__+': '+str(exc)}]}
        with LOCK:CALLS.appendleft({'id':call,'name':name,'status':status,'duration_ms':round((time.monotonic()-started)*1000)})
        return {'jsonrpc':'2.0','id':rid,'result':out}
    return None if rid is None else {'jsonrpc':'2.0','id':rid,'error':{'code':-32601,'message':'Method not found'}}

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path!='/health':self.send_error(404);return
        data=b'{"status":"ok"}';self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def do_POST(self):
        if self.path.rstrip('/')!='/mcp':self.send_error(404);return
        secret=os.environ.get('FLICKER_LINK_TOKEN','')
        given=self.headers.get('Authorization','')
        if not secret or not hmac.compare_digest(given,'Bearer '+secret):
            self.send_response(401);self.send_header('WWW-Authenticate','Bearer');self.send_header('Content-Length','0');self.end_headers();return
        try:
            length=int(self.headers.get('Content-Length','0'))
            if length<=0 or length>4*1024*1024:raise ValueError('Invalid request size')
            req=json.loads(self.rfile.read(length))
            resp=handle(req)
            if resp is None:self.send_response(202);self.send_header('Content-Length','0');self.end_headers();return
            data=json.dumps(resp).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        except Exception as e:self.send_error(400,str(e))
    def log_message(self,*args):pass

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--http',action='store_true');parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--port',type=int,default=8080)
    a=parser.parse_args()
    if a.http:
        if not os.getenv('FLICKER_LINK_TOKEN'):raise SystemExit('Set FLICKER_LINK_TOKEN first')
        http.server.ThreadingHTTPServer((a.host,a.port),Handler).serve_forever()
    else:
        for line in sys.stdin:
            try:
                r=handle(json.loads(line))
                if r is not None:print(json.dumps(r),flush=True)
            except Exception as e:print(str(e),file=sys.stderr)
if __name__=='__main__':main()
