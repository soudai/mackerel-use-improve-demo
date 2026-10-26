#!/usr/bin/env python3
"""Capture read-only Mackerel API evidence without recording credentials."""
import datetime as dt
import html
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
SKILL=ROOT/'.agents/skills/mackerel-dev-improve/scripts'
sys.path.insert(0,str(SKILL))
import observe
import publish

def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00','Z')

def stamp(epoch):
    point=dt.datetime.fromtimestamp(epoch,dt.timezone.utc)
    return {'epoch_seconds':epoch,'utc':point.isoformat().replace('+00:00','Z'),'jst':point.astimezone(ZoneInfo('Asia/Tokyo')).isoformat()}

def summaries(path,body,response,identity):
    route=urlsplit(path).path
    if route.endswith('/org'):
        return {'organization':response.get('name'),'matches_expected':response.get('name')=='mackerel-seminar'}
    if route.endswith('/services'):
        items=response.get('services',[])
        return {'returned_count':len(items),'selected_service_exists':any(x.get('name')=='mackerel-seminar-demo' for x in items)}
    if route.endswith('/metadata/dev-quality'):
        return {'schema_version':response.get('schema_version'),'service':response.get('service'),'environment':response.get('environment'),'profiles':response.get('profiles')}
    if route.endswith('/metrics'):
        return {'point_count':len(response.get('metrics',[])),'points':response.get('metrics',[])}
    if route.endswith('http-server-stats') or route.endswith('db-query-stats'):
        return {'returned_group_count':len(response.get('results',[])),'has_next_page':response.get('hasNextPage'),'groups':response.get('results',[])}
    if route.endswith('/logs'):
        matched=[]
        for item in response.get('results',[]):
            attrs=observe.resource_strings(item.get('resourceAttributes',[]))
            if attrs.get('service.version')!=identity.get('version') or attrs.get('deployment.environment.name',attrs.get('deployment.environment'))!=identity.get('environment'):
                continue
            selected={'timestamp':item.get('timestamp'),'severity':item.get('severity'),'trace_id':item.get('traceId'),'span_id':item.get('spanId'),'service_version':attrs.get('service.version')}
            try:
                raw=json.loads(item.get('body',''))
                selected['request']={k:raw[k] for k in ['method','route','status','request_time','query_count','peak_memory_bytes'] if k in raw}
            except (ValueError,TypeError):
                selected['request']='body not JSON; omitted'
            matched.append(selected)
        return {'returned_count':len(response.get('results',[])),'matched_scope_count':len(matched),'matched_with_trace_id':sum(bool(x['trace_id']) for x in matched),'has_next_page':response.get('pagination',{}).get('hasNextPage'),'sample_records':matched[:3]}
    return {'keys':sorted(response)}

class AuditClient:
    def __init__(self,delegate):
        self.delegate=delegate
        self.records=[]
        self.phase='preflight'
        self.identity={}
        self.last=0

    def request(self,method,path,body=None):
        allowed=method=='GET' or (method=='POST' and path=='/api/v0/logs')
        if not allowed: raise RuntimeError('This audit cannot write to Mackerel.')
        time.sleep(max(0,1.1-(time.monotonic()-self.last)))
        self.last=time.monotonic()
        parsed=urlsplit(path)
        entry={'sequence':len(self.records)+1,'phase':self.phase,'method':method,'origin':publish.API_BASE,'path':parsed.path,'query':{k:v[0] if len(v)==1 else v for k,v in parse_qs(parsed.query).items()},'body':body,'started_at_utc':utc_now()}
        try:
            response=self.delegate.request(method,path,body)
            entry.update(http_status=200,summary=summaries(path,body,response,self.identity),finished_at_utc=utc_now())
            return response
        except publish.APIError as error:
            entry.update(http_status=error.status,outcome='request failed',finished_at_utc=utc_now())
            raise
        finally:
            self.records.append(entry)

def create_page(evidence):
    esc=html.escape
    requests=evidence['read_only_recheck']['requests']
    rows=[]
    details=[]
    for req in requests:
        query=req['query']
        summary=req.get('summary',{})
        if req['path'].endswith('/metrics'):
            result=f"{query.get('name')}: {summary.get('points',[])}"
        elif 'groups' in summary:
            result=f"{summary.get('returned_group_count')} groups"
        elif req['path'].endswith('/logs'):
            result=f"scope一致 {summary.get('matched_scope_count')} / 取得 {summary.get('returned_count')}; trace ID {summary.get('matched_with_trace_id')}"
        elif req['path'].endswith('/org'):
            result=f"organization match: {summary.get('matches_expected')}"
        elif req['path'].endswith('/services'):
            result=f"target service exists: {summary.get('selected_service_exists')}"
        else:
            result='metadata profiles: '+', '.join((summary.get('profiles') or {}).keys())
        rows.append(f"<tr><td>{req['sequence']}</td><td>{esc(req['phase'])}</td><td><code>{req['method']} {esc(req['path'])}</code></td><td>{req.get('http_status')}</td><td>{esc(result)}</td></tr>")
        sample={k:req[k] for k in ['method','origin','path','query','body','http_status','summary'] if k in req}
        details.append(f"<details><summary>#{req['sequence']} {esc(req['method']+' '+req['path'])} — リクエスト条件と応答の抜粋</summary><div class=\"code-block\"><pre><code>{esc(json.dumps(sample,ensure_ascii=False,indent=2))}</code></pre></div></details>")
    ui_links=''.join(f'<li><a href="{esc(url, quote=True)}">{esc(label)}</a></li>' for label,url in evidence.get('ui_links',{}).items())
    windows=''.join(f"<tr><td>{esc(x['label'])}</td><td><code>{esc(x['identity']['version'])}</code></td><td>{esc(x['from']['utc'])}<br>{esc(x['to']['utc'])}</td><td>{esc(x['from']['jst'])}<br>{esc(x['to']['jst'])}</td></tr>" for x in evidence['windows'])
    old=evidence['historical_writes']
    historic=''.join(f"<details><summary>{esc(x['method']+' '+x['path'])} — 過去の実投稿（今回再送なし）</summary><div><p>{esc(x['evidence'])}</p><div class=\"code-block\"><pre><code>{esc(json.dumps(x,ensure_ascii=False,indent=2))}</code></pre></div></div></details>" for x in old)
    return f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Mackerel API検証のリクエストと根拠</title><link rel="stylesheet" href="assets/style.css"><link rel="icon" href="assets/favicon.svg"></head><body><aside class="sidebar"><a class="brand" href="index.html"><span class="brand-mark">m</span><span>Mackerel<br><small>API Evidence</small></span></a><div class="nav-label">REQUEST AUDIT</div><nav><a href="#summary">確認範囲</a><a href="#windows">対象期間</a><a href="#requests">実行したAPI</a><a href="#writes">過去の投稿API</a><a href="validation.html">検証レポートへ</a></nav></aside><div class="document"><header class="topbar"><span>API監査 / 2026-10-26</span><a href="validation.html">検証結果へ戻る ↗</a></header><main><section class="section" id="summary"><p class="eyebrow">REAL API REQUEST EVIDENCE</p><h1>Mackerel APIの条件と、<br>根拠になったデータ。</h1><p>対象組織 <code>mackerel-seminar</code>、対象サービス <code>mackerel-seminar-demo</code>。APIキーは記録せず、同じ期間・versionを指定して読取りAPIを再実行しました。</p><p>再確認時刻（UTC）: <code>{esc(evidence['read_only_recheck']['started_at_utc'])}</code>。このページの成功HTTPステータスは、クライアントがHTTP 200を確認した応答です。認証情報や全ログ本文は保存していません。過去の書込みは再実行していません。</p><p>品質系列の再取得値一致: <strong>{evidence['read_only_recheck'].get('metric_readback',{}).get('matched_count',0)} / 25</strong>。</p><div class="note"><h3>Mackerelの実画面で確認する</h3><ul>{ui_links}</ul></div><p><a href="api-evidence.json">全リクエスト条件と応答抜粋のJSON</a> / <a href="https://mackerel.io/orgs/mackerel-seminar/apm/mackerel-seminar-demo?tab=traces&amp;serviceNamespace=demo">MackerelのAPM・トレース一覧</a></p><div class="note"><h3>読み取りと書込みの区別</h3><p><code>POST /api/v0/logs</code> はログ検索で、Mackerel上のデータを変更しません。今回の監査はGETとこのログ検索だけです。<code>POST .../tsdb</code> と <code>PUT .../metadata/dev-quality</code> は過去の投稿証跡を示しています。</p></div></section><section class="section" id="windows"><h2>取得した期間と実行版</h2><div class="table-wrap"><table><thead><tr><th>区間</th><th>service.version</th><th>UTC from / to</th><th>JST from / to</th></tr></thead><tbody>{windows}</tbody></table></div><p>namespaceは <code>demo</code>、環境は <code>development</code>。APMは両方をAPI条件に指定し、ログは返却resource属性で環境・versionを照合しています。サービスメトリックス自体にはversionフィルターがないため、投稿metadataとrunを照合します。</p></section><section class="section" id="requests"><h2>今回再実行した読取りAPI</h2><p>APIホストは <code>https://api.mackerelio.com</code>。認証ヘッダー名は <code>X-Api-Key</code>、値は非記録です。1.1秒以上の間隔を空け、各取得を最大3ページで制限しています。以下は論理リクエストの監査で、既存クライアント内部のGET再試行は個別の通信ログとしては分離していません。</p><div class="table-wrap"><table><thead><tr><th>#</th><th>区間</th><th>API</th><th>HTTP</th><th>応答の要点</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>{''.join(details)}</section><section class="section" id="writes"><h2>過去に実行した品質投稿API</h2><p>この監査で再投稿していません。生の通信キャプチャではなく、実行済みpublisherの結果、固定payload、metadataの読戻しに基づく記録です。<a href="{esc(evidence['published_artifact_url'])}">元の品質レポート</a>でchecksum、revision、run、25系列を確認できます。</p>{historic}</section><footer class="footer"><a href="validation.html">検証レポートへ戻る</a><a href="api-evidence.json">監査JSON</a></footer></main></div></body></html>"""

def main():
    helper=load_module('env_helper',ROOT/'scripts/with_mackerel.py')
    key=os.environ.get('MACKEREL_APIKEY') or helper.local_api_key(ROOT/'.env')
    client=AuditClient(publish.Client(key))
    start=utc_now()
    client.request('GET','/api/v0/org')
    service=client.request('GET','/api/v0/services')
    if not any(x.get('name')=='mackerel-seminar-demo' for x in service.get('services',[])):
        raise RuntimeError('Target service not found')
    live=ROOT/'artifacts/verification/live'
    metrics=json.loads((live/'quality-publish/normalized/metrics.json').read_text())
    manifest=json.loads((live/'quality-publish/normalized/manifest.json').read_text())
    publication=json.loads((live/'quality-publish/normalized/publication-result.json').read_text())
    windows=[]
    observed=[]
    for label,filename in [('HTTP・検索・売上集計','observation.json'),('同時購入・品質系列','checkout-observation.json')]:
        cfg=json.loads((live/filename).read_text())
        if label.startswith('同時'):
            cfg['metrics']=[x['name'] for x in metrics]
        client.phase=label
        client.identity=cfg['identity']
        windows.append({'label':label,'identity':cfg['identity'],'from':stamp(cfg['window']['from']),'to':stamp(cfg['window']['to'])})
        observed.append(observe.observe(cfg,client,'mackerel-seminar',max_pages=3,include_text=False))
    client.phase='品質投稿metadataの再確認'
    metadata=client.request('GET','/api/v0/services/mackerel-seminar-demo/metadata/dev-quality')
    expected_profiles={name:{'revision':manifest['revision'],'run_id':manifest['run_id'],'attempt_id':manifest['attempt_id'],'comparison_key':profile['comparison_key'],'measured_at':manifest['publication']['measurement_timestamp'],'artifact_uri':manifest['artifact_uri'],'report_completeness':manifest['collection'][name]['status'],'published_status':'verified','payload_sha256':manifest['publication']['payload_sha256']} for name,profile in manifest['profiles'].items()}
    writes=[{'method':'POST','path':'/api/v0/services/mackerel-seminar-demo/tsdb','executed_at_utc':'2026-10-26T09:58:00Z','logical_http_status_verified_by_client':200,'wire_capture':False,'evidence':'publication-result.jsonのposting→metrics_verified→verified、および固定payloadのSHA256','payload':metrics,'payload_sha256':publication['payload_sha256'],'outcome':publication['status']},
            {'method':'PUT','path':'/api/v0/services/mackerel-seminar-demo/metadata/dev-quality','executed_at_utc':'2026-10-26T09:58:04Z','logical_http_status_verified_by_client':200,'wire_capture':False,'evidence':'publisherのsuccess応答とGET読戻し一致。保存したprofileの構造・実値を記載。','body_recorded_profiles':expected_profiles,'outcome':publication['status']}]
    evidence={'schema_version':1,'title':'Mackerel demo API evidence','organization':'mackerel-seminar','service':'mackerel-seminar-demo','published_artifact_url':manifest['artifact_uri'],'windows':windows,'authentication':{'header_name':'X-Api-Key','value_recorded':False},'read_only_recheck':{'started_at_utc':start,'finished_at_utc':utc_now(),'request_count':len(client.records),'requests':client.records,'observations':[{k:v for k,v in d.items() if k in ['status','runtime_version_filter_applied']} for d in observed]},'historical_writes':writes,'metadata_profiles_match':all(metadata.get('profiles',{}).get(k)==v for k,v in expected_profiles.items()),'ui_links':{'traces_list':'https://mackerel.io/orgs/mackerel-seminar/apm/mackerel-seminar-demo?tab=traces&serviceNamespace=demo'},'limitations':['The read-only audit is a logical request log, not a packet capture.','GET transport retries, if any, are handled by the existing client and not counted individually.','Historical write timestamps are rounded to seconds from publication stage evidence.','No API key, Authorization value, or full raw log body is recorded.']}
    expected={x['name']:x for x in metrics}
    checks=[]
    for request in client.records:
        if request['path'].endswith('/metrics'):
            name=request['query'].get('name')
            points=request.get('summary',{}).get('points',[])
            checks.append({'name':name,'expected_value':expected[name]['value'],'measurement_timestamp':expected[name]['time'],'points':points,'matches_expected':publish.metric_matches({'metrics':points},expected[name])})
    evidence['read_only_recheck']['metric_readback']={'matched_count':sum(x['matches_expected'] for x in checks),'checked_count':len(checks),'series':checks}
    blob=(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n').encode()
    if key.encode() in blob: raise RuntimeError('Secret leakage guard rejected report.')
    page=create_page(evidence)
    if key in page: raise RuntimeError('Secret leakage guard rejected HTML.')
    (ROOT/'docs/api-evidence.json').write_bytes(blob)
    (ROOT/'docs/api-verification.html').write_text(page,encoding='utf-8')
    print(json.dumps({'requests':len(client.records),'http_statuses':sorted(set(x.get('http_status') for x in client.records)),'metadata_profiles_match':evidence['metadata_profiles_match'],'observation_statuses':[x['status'] for x in evidence['read_only_recheck']['observations']],'files':['docs/api-evidence.json','docs/api-verification.html']},ensure_ascii=False))

if __name__=='__main__':
    main()
