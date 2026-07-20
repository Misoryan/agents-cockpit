"use strict";
function renderDirRow(d, q){
  var mc=matchConvs(d,q);
  var dirNameMatch = !q || (d.cwd||"").toLowerCase().indexOf(q)>=0;
  var open = !!expanded[d.cwd] || (!!q && !dirNameMatch && (mc.sessions.length||mc.history.length));
  var row=document.createElement("div");
  var head=document.createElement("div"); head.className="dhead";
  var ds=typeof dirStatusInfo==="function"?dirStatusInfo(d):null;
  row.className="drow"+(d.running?" hasrun hasopen":"")+(ds?(" dstate-"+ds.cls):"")+(open?" open":"");
  row.setAttribute("data-cwd-key", normDir(d.cwd));
  head.innerHTML='<span class="icn"><i class="ic" data-lucide="folder"></i></span>'+
    '<span class="nm">'+esc(basename(d.cwd)||d.cwd)+'</span>'+
    (ds?'<span class="badge '+ds.cls+'">'+esc(ds.label)+'</span>':'')+
    '<span class="chev"><i class="ic" data-lucide="'+(open?'chevron-down':'chevron-right')+'"></i></span>';
  var plus=document.createElement("button"); plus.className="plus"; plus.innerHTML='<i class="ic" data-lucide="plus"></i>'; plus.title="在此目录发起新对话";
  plus.addEventListener("click", function(ev){ ev.stopPropagation(); openLaunchForDir(d.cwd, basename(d.cwd)); });
  head.appendChild(plus);
  head.title=d.cwd||"";
  head.addEventListener("click", function(){
    var willOpen=!expanded[d.cwd];
    var anchor=null;
    if(willOpen && head.getBoundingClientRect){
      anchor={headTop:head.getBoundingClientRect().top};
    }
    expanded[d.cwd]=willOpen;
    renderSidebar();
    if(willOpen) scheduleDirRowVisible(d.cwd, anchor);
  });
  row.appendChild(head);
  var sub=document.createElement("div"); sub.className="dsub";
  sub.textContent=d.cwd+" · "+(d.count||(d.history&&d.history.length)||0)+" 段 · "+relTime(d.lastActivity);
  row.appendChild(sub);
  if(open) row.appendChild(renderDirBody(d, mc));
  return row;
}
function scheduleDirRowVisible(cwd, anchor){
  var run=function(){ ensureDirRowVisible(cwd, anchor); };
  if(typeof requestAnimationFrame==="function"){
    requestAnimationFrame(function(){ requestAnimationFrame(run); });
  }else{
    setTimeout(run, 0);
  }
}
function ensureDirRowVisible(cwd, anchor){
  var list=$("dirlist");
  if(!list || !list.getBoundingClientRect) return;
  var key=normDir(cwd), rows=list.querySelectorAll?list.querySelectorAll(".drow"):[];
  var row=null;
  for(var i=0;i<rows.length;i++){
    if(rows[i].getAttribute("data-cwd-key")===key){ row=rows[i]; break; }
  }
  if(!row || !row.getBoundingClientRect) return;
  var lr=list.getBoundingClientRect(), rr=row.getBoundingClientRect();
  if(anchor && typeof anchor.headTop==="number"){
    var head=row.querySelector?row.querySelector(".dhead"):null;
    var ar=(head||row).getBoundingClientRect();
    var delta=ar.top-anchor.headTop;
    // Keep the clicked folder head under the pointer; avoid post-click auto-scroll jumps.
    if(Math.abs(delta)>1) list.scrollTop += delta;
    return;
  }
  var pad=12, usable=Math.max(0, lr.height-pad*2), nextPreview=row.nextElementSibling?52:pad;
  if(rr.height>Math.max(0, lr.height-pad-nextPreview)) nextPreview=pad;
  if(!lr.height || !rr.height) return;
  if(rr.height>usable){
    if(Math.abs(rr.top-(lr.top+pad))>1) list.scrollTop += rr.top-(lr.top+pad);
    return;
  }
  if(rr.bottom>lr.bottom-nextPreview) list.scrollTop += rr.bottom-(lr.bottom-nextPreview);
  else if(rr.top<lr.top+pad) list.scrollTop -= (lr.top+pad)-rr.top;
}
function renderDirBody(d, mc){
  var body=document.createElement("div"); body.className="dbody";
  var runIds={}; (d.sessions||[]).forEach(function(s){ if(s.session_id) runIds[s.session_id]=true; });
  var running=(mc.sessions||[]).slice();
  var history=(mc.history||[]).filter(function(h){ return !runIds[h.session_id]; });
  var items=running.map(function(s){ return {kind:"run", data:s}; }).concat(history.map(function(h){ return {kind:"hist", data:h}; })).sort(recentTaskSort);
  if(!items.length){ var e=empty("（暂无对话）"); e.style.padding="8px"; body.appendChild(e); return body; }
  var clicks=Number(dirExpandClicks[d.cwd]||0);
  var limit;
  if(running.length){
    var slotLimit=clicks<=0?2:(4+(clicks-1)*4);
    var liveLimit=0;
    items.forEach(function(it, idx){ if(it.kind==="run") liveLimit=Math.max(liveLimit, idx+1); });
    limit=Math.max(liveLimit, slotLimit);
  }else{
    limit=clicks<=0?4:(4+clicks*4);
  }
  items.slice(0,limit).forEach(function(it){ body.appendChild(renderConv(it)); });
  if(items.length>limit){
    var more=document.createElement("button"); more.className="more"; more.textContent="展开";
    more.addEventListener("click", function(){ dirExpandClicks[d.cwd]=clicks+1; renderSidebar(); });
    body.appendChild(more);
  }
  return body;
}
function recentTaskTs(it){
  if(!it || !it.data) return 0;
  if(it.kind==="run") return (typeof sessionSortTs==="function") ? sessionSortTs(it.data) : Number(it.data.last_completed_at||it.data.last_output_ts||it.data.last_input_ts||it.data.started||0);
  return Number(it.data.ts||0);
}
function recentTaskKey(it){
  var d=(it&&it.data)||{};
  return String(d.session_id||d.thread_id||d.sid||d.title||"");
}
function recentTaskSort(a,b){
  return recentTaskTs(b)-recentTaskTs(a) || recentTaskKey(a).localeCompare(recentTaskKey(b));
}
function closeSession(sid, btn){
  if(btn){ btn.disabled=true; btn.textContent="关闭中"; }
  postJSON("/api/stop",{sid:sid}).then(function(){
    if(openTabs.indexOf(sid)>=0){ openTabs=openTabs.filter(function(x){ return x!==sid; }); saveOpenTabs(); renderSessionTabs(); }
    if(sid===currentSid){ dropNativeStage(sid); setMainView("landing"); }
    pollSessionSignals(); loadSidebarData();
  }).catch(function(){ if(btn){ btn.disabled=false; btn.textContent="关闭"; } alert("关闭失败:网络错误"); });
}
function appendSidebarMenuButton(actions, label, title, fn, extraClass){
  var btn=document.createElement("button");
  btn.className="cbtn ghost"+(extraClass?(" "+extraClass):"");
  btn.type="button";
  btn.textContent=label;
  btn.title=title||label;
  btn.addEventListener("click", function(ev){
    ev.stopPropagation();
    fn(btn);
  });
  actions.appendChild(btn);
  return btn;
}
function renderConv(it){
  var el=document.createElement("div"); el.className="conv";
  var actions=document.createElement("div"); actions.className="cactions-inline";
  var menu=document.createElement("div"); menu.className="cactions";
  if(it.kind==="run"){
    var s=it.data; var dot=s.state==="confirm"?"confirm":s.state==="plan"?"plan":s.state==="new"?"new":(s.state==="running"?"run":"idle");
    el.className="conv conv-open state-"+dot+(s.sid===currentSid?" current":"");
    var meta=(typeof openSessionMeta==="function") ? openSessionMeta(s) : (sessionStateText(s)+" \u00b7 "+backendShort(s.backend));
    el.innerHTML='<span class="dot '+dot+'"></span><div class="cmain"><div class="ct">'+esc(s.title||basename(s.dir))+'</div><div class="cm">'+esc(meta)+'</div></div>';
    var openFn=function(){ showNativeSession(s.sid, s.title||basename(s.dir)); };
    el.addEventListener("click", openFn);
    appendSidebarMenuButton(menu, "\u6253\u5f00", "\u6253\u5f00\u6b64\u4f1a\u8bdd", function(){ openFn(); }, "primary");
    appendSidebarMenuButton(menu, "\u5173\u95ed", "\u505c\u6b62\u8be5\u4f1a\u8bdd\u5e76\u4ece\u5217\u8868\u79fb\u9664\uff08\u5386\u53f2\u4fdd\u7559\uff0c\u53ef\u6062\u590d\uff09", function(btn){ closeSession(s.sid, btn); });
    if(typeof fillCodexRunActions==="function") fillCodexRunActions(menu, s);
  } else {
    var h=it.data; var be=h.backend||"codex";
    el.className="conv conv-history";
    var histState=sbArchived?"归档":"历史";
    el.innerHTML='<span class="dot hist"></span><div class="cmain"><div class="ct">'+esc(h.title||"(\u65e0\u6807\u9898)")+'</div><div class="cm">'+esc(histState+" \u00b7 "+backendShort(be)+" \u00b7 "+relTime(h.ts))+'</div></div>';
    var resumeFn=function(){ resumeHist(h); };
    el.addEventListener("click", resumeFn);
    appendSidebarMenuButton(menu, "\u7ee7\u7eed", "\u7ee7\u7eed\u6b64\u5386\u53f2\u4f1a\u8bdd", function(){ resumeFn(); }, "primary");
    appendSidebarMenuButton(menu, "\u5220\u9664", isCodexBackend(be)?"\u5220\u9664\u6b64 Codex thread\uff08\u4e0d\u53ef\u6062\u590d\uff09":"\u5220\u9664\u6b64\u5386\u53f2\uff08\u79fb\u9664\u5e95\u5c42\u4f1a\u8bdd\u6587\u4ef6\uff0c\u4e0d\u53ef\u6062\u590d\uff09", function(btn){ delHist(h, btn); }, "delbtn");
    if(typeof fillCodexHistoryActions==="function") fillCodexHistoryActions(menu, h);
  }
  if(menu.children.length) appendCodexActionMenu(actions, menu);
  el.appendChild(actions);
  return el;
}
function resumeHist(h){
  var be=h.backend||"codex";
  postJSON("/api/resume", {session_id:h.session_id, dir:h.cwd, title:h.title, backend:be}).then(function(r){
    if(r.error){ alert("恢复失败："+r.error); return; }
    var title=(h.title||"继续会话")+" · "+backendLabel(be);
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
