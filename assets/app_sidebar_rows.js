"use strict";
function renderDirRow(d, q){
  var mc=matchConvs(d,q);
  var dirNameMatch = !q || (d.cwd||"").toLowerCase().indexOf(q)>=0;
  var open = !!expanded[d.cwd] || (!!q && !dirNameMatch && (mc.sessions.length||mc.history.length));
  var row=document.createElement("div");
  row.className="drow"+(d.running?" hasrun":"")+(open?" open":"");
  var head=document.createElement("div"); head.className="dhead";
  head.innerHTML='<span class="icn"><i class="ic" data-lucide="folder"></i></span>'+
    '<span class="nm">'+esc(basename(d.cwd)||d.cwd)+'</span>'+
    (d.running?'<span class="badge">●'+d.running+'</span>':'')+
    '<span class="chev"><i class="ic" data-lucide="'+(open?'chevron-down':'chevron-right')+'"></i></span>';
  var plus=document.createElement("button"); plus.className="plus"; plus.innerHTML='<i class="ic" data-lucide="plus"></i>'; plus.title="在此目录发起新对话";
  plus.addEventListener("click", function(ev){ ev.stopPropagation(); openLaunchForDir(d.cwd, basename(d.cwd)); });
  head.appendChild(plus);
  head.addEventListener("click", function(){ expanded[d.cwd]=!expanded[d.cwd]; renderSidebar(); });
  row.appendChild(head);
  var sub=document.createElement("div"); sub.className="dsub";
  sub.textContent=d.cwd+" · "+(d.count||(d.history&&d.history.length)||0)+" 段 · "+relTime(d.lastActivity);
  row.appendChild(sub);
  if(open) row.appendChild(renderDirBody(d, mc));
  return row;
}
function renderDirBody(d, mc){
  var body=document.createElement("div"); body.className="dbody";
  var runIds={}; (d.sessions||[]).forEach(function(s){ if(s.session_id) runIds[s.session_id]=true; });
  var running=(mc.sessions||[]).slice().sort(function(a,b){ return (b.last_output_ts||0)-(a.last_output_ts||0); });
  var history=(mc.history||[]).filter(function(h){ return !runIds[h.session_id]; }).sort(function(a,b){ return (b.ts||0)-(a.ts||0); });
  var items=running.map(function(s){ return {kind:"run", data:s}; }).concat(history.map(function(h){ return {kind:"hist", data:h}; }));
  if(!items.length){ var e=empty("（暂无对话）"); e.style.padding="8px"; body.appendChild(e); return body; }
  var clicks=Number(dirExpandClicks[d.cwd]||0);
  var limit;
  if(running.length){
    var slotLimit=clicks<=0?3:(5+(clicks-1)*5);
    limit=Math.max(running.length, slotLimit);
  }else{
    limit=clicks<=0?6:(6+clicks*5);
  }
  items.slice(0,limit).forEach(function(it){ body.appendChild(renderConv(it)); });
  if(items.length>limit){
    var more=document.createElement("button"); more.className="more"; more.textContent="展开";
    more.addEventListener("click", function(){ dirExpandClicks[d.cwd]=clicks+1; renderSidebar(); });
    body.appendChild(more);
  }
  return body;
}
function closeSession(sid, btn){
  if(btn){ btn.disabled=true; btn.textContent="关闭中"; }
  postJSON("/api/stop",{sid:sid}).then(function(){
    if(openTabs.indexOf(sid)>=0){ openTabs=openTabs.filter(function(x){ return x!==sid; }); saveOpenTabs(); renderSessionTabs(); }
    if(sid===currentSid){ dropNativeStage(sid); setMainView("landing"); }
    pollSessionSignals(); loadSidebarData();
  }).catch(function(){ if(btn){ btn.disabled=false; btn.textContent="关闭"; } alert("关闭失败:网络错误"); });
}
function renderConv(it){
  var el=document.createElement("div"); el.className="conv";
  if(it.kind==="run"){
    var s=it.data; var dot=s.state==="confirm"?"confirm":s.state==="plan"?"plan":s.state==="new"?"new":(s.state==="running"?"run":"idle");
    var _sl=s.state==="running"?"生成中":s.state==="confirm"?"待确认":s.state==="plan"?"计划中":s.state==="new"?"新会话":"空闲";
    var meta=_sl+" · "+backendShort(s.backend)+(s.yolo?" · 自动批准":"")+(s.mode==="resume"?" · 恢复":"")+" · "+elapsedStr(s.last_input_ts);
    el.innerHTML='<span class="dot '+dot+'"></span><div class="cmain"><div class="ct">'+esc(s.title||basename(s.dir))+'</div><div class="cm">'+esc(meta)+'</div></div>';
    var b=document.createElement("button"); b.className="cbtn"; b.textContent="打开";
    var openFn=function(){ showNativeSession(s.sid, s.title||basename(s.dir)); };
    b.addEventListener("click", function(ev){ ev.stopPropagation(); openFn(); });
    el.addEventListener("click", openFn); el.appendChild(b);
    var cb=document.createElement("button"); cb.className="cbtn ghost"; cb.textContent="关闭"; cb.title="停止该会话并从列表移除(历史保留,可恢复)";
    cb.addEventListener("click", function(ev){ ev.stopPropagation(); closeSession(s.sid, cb); }); el.appendChild(cb);
    appendCodexRunActions(el, s);
  } else {
    var h=it.data; var be=h.backend||"codex";
    el.innerHTML='<span class="dot idle"></span><div class="cmain"><div class="ct">'+esc(h.title||"(无标题)")+'</div><div class="cm">'+esc(backendShort(be)+" · "+relTime(h.ts))+'</div></div>';
    var rb=document.createElement("button"); rb.className="cbtn ghost"; rb.textContent="恢复";
    var resumeFn=function(){ resumeHist(h); };
    rb.addEventListener("click", function(ev){ ev.stopPropagation(); resumeFn(); });
    el.addEventListener("click", resumeFn); el.appendChild(rb);
    var delbtn=document.createElement("button"); delbtn.className="cbtn ghost delbtn"; delbtn.textContent="删除"; delbtn.title=isCodexBackend(be)?"删除此 Codex thread(不可恢复)":"删除此历史(移除底层会话文件,不可恢复)";
    delbtn.addEventListener("click", function(ev){ ev.stopPropagation(); delHist(h, delbtn); });
    el.appendChild(delbtn);
    appendCodexHistoryActions(el, h);
  }
  return el;
}
function resumeHist(h){
  var be=h.backend||"codex";
  postJSON("/api/resume", {session_id:h.session_id, dir:h.cwd, title:h.title, backend:be}).then(function(r){
    if(r.error){ alert("恢复失败："+r.error); return; }
    var title=(h.title||"恢复会话")+" · "+backendLabel(be);
    showNativeSession(r.sid, title);
    nRenderYoloBadge({yolo:r.yolo});
    loadSidebarData();
  });
}
function delHist(h, btn){
  var be=h.backend||"codex";
  var target=isCodexBackend(be)?"Codex thread":"底层会话文件";
  if(!confirm("确认删除「"+(h.title||"(无标题)")+"」?将移除"+target+",删除后无法再恢复或续聊该对话。")) return;
  if(btn){ btn.disabled=true; btn.textContent="删除中"; }
  if(h.session_id){ postJSON("/api/stop",{sid:h.session_id}); }
  if(h.session_id && currentSid===h.session_id){ dropNativeStage(h.session_id); setMainView("landing"); }
  postJSON("/api/history_delete", {sid:h.session_id, backend:be}).then(function(r){
    if(r.error){ alert("删除失败："+r.error); if(btn){ btn.disabled=false; btn.textContent="删除"; } return; }
    if(!r.deleted){ alert("未找到对应会话文件,可能已被删除。"); }
    loadSidebarData();
  }).catch(function(){ if(btn){ btn.disabled=false; btn.textContent="删除"; } alert("删除失败:网络错误"); });
}
