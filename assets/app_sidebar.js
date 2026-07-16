"use strict";
/* ---- sessions + sidebar model ---- */
var runSessions=[], sessionWatch={}, dirModel=[], expanded={}, dirExpandClicks={}, sbSearch="", sbArchived=false, lastSig="", sidebarLoadSeq=0;
var pendingOpenSid=""; try{ pendingOpenSid=new URLSearchParams(location.search).get("open")||""; }catch(e){}
try{ sbArchived=localStorage.getItem("acHistoryView")==="archived"; }catch(e){ sbArchived=false; }

var openTabs=[], sessionsLoaded=false;
try{ openTabs=JSON.parse(localStorage.getItem("acOpenTabs")||"[]")||[]; }catch(e){ openTabs=[]; }
function saveOpenTabs(){ try{ localStorage.setItem("acOpenTabs", JSON.stringify(openTabs)); }catch(e){} }
function ensureTabOpen(sid){
  if(!sid) return;
  if(openTabs.indexOf(sid)<0){ openTabs.push(sid); saveOpenTabs(); }
}
function pruneOpenTabs(){
  if(!sessionsLoaded) return;
  var live={}; runSessions.forEach(function(s){ live[s.sid]=true; });
  var before=openTabs.length;
  openTabs=openTabs.filter(function(sid){ return live[sid]; });
  if(openTabs.length!==before) saveOpenTabs();
}
function tabSession(sid){
  for(var i=0;i<runSessions.length;i++){ if(runSessions[i].sid===sid) return runSessions[i]; }
  return null;
}
function sessionDot(s){ return s.state==="confirm"?"confirm":s.state==="plan"?"plan":s.state==="new"?"new":(s.state==="running"?"run":"idle"); }
function sessionStateText(s){ return s.state==="running"?"\u751f\u6210\u4e2d":s.state==="confirm"?"\u5f85\u786e\u8ba4":s.state==="plan"?"\u8ba1\u5212\u4e2d":s.state==="new"?"\u65b0\u4f1a\u8bdd":"\u7a7a\u95f2"; }
function renderSessionTabs(){
  var bar=$("sessiontabs"); if(!bar) return;
  bar.innerHTML="";
  var rendered=0;
  openTabs.forEach(function(sid){
    var s=tabSession(sid); if(!s) return;
    var btn=document.createElement("button"); btn.type="button"; btn.className="stab"+(sid===currentSid?" active":"");
    btn.title=(s.title||basename(s.dir)||sid)+"\n"+(s.dir||"");
    btn.innerHTML='<span class="dot '+sessionDot(s)+'"></span><span class="st-main"><span class="st-title">'+esc(s.title||basename(s.dir)||sid)+'</span><span class="st-meta">'+esc(sessionStateText(s)+" / "+backendShort(s.backend))+'</span></span>';
    var close=document.createElement("span"); close.className="st-close"; close.setAttribute("aria-label","Close tab"); close.textContent="x";
    close.addEventListener("click", function(ev){ ev.stopPropagation(); closeTab(sid); });
    btn.appendChild(close);
    btn.addEventListener("click", function(){ showNativeSession(sid, s.title||basename(s.dir)); });
    bar.appendChild(btn); rendered++;
  });
  bar.classList.toggle("tabs-empty", !rendered);
  var dock=$("mobilebar"); if(dock) dock.classList.toggle("has-tabs", !!rendered);
  var ts=$("topstatus"); if(ts) ts.style.display=currentSid?"":"none";
}
function closeTab(sid){
  var idx=openTabs.indexOf(sid); if(idx<0) return;
  openTabs.splice(idx,1); saveOpenTabs();
  if(sid===currentSid){
    var nextSid=openTabs[idx] || openTabs[idx-1] || "";
    if(nextSid){ openSessionBySid(nextSid, true); }
    else { currentSid=null; setMainView("landing"); nSetGen(false); nUpdateScrollButton(); }
  }
  renderSessionTabs();
}
function switchTab(delta){
  if(!openTabs.length) return;
  var idx=openTabs.indexOf(currentSid); if(idx<0) idx=delta>0?-1:0;
  var next=(idx+delta+openTabs.length)%openTabs.length;
  openSessionBySid(openTabs[next], true);
}

function sessionSignature(){
  return runSessions.slice().sort(function(a,b){ return a.sid<b.sid?-1:1; }).map(function(s){ return s.sid+":"+s.state+":"+(s.yolo?"1":"0"); }).join("|");
}
function ensureSessionDirs(){
  var byNorm={}; dirModel.forEach(function(d){ byNorm[d.norm]=d; });
  runSessions.forEach(function(s){ var k=normDir(s.dir); if(!byNorm[k]){ dirModel.push({cwd:s.dir, norm:k, count:0, last_ts:0, history:[], sessions:[]}); byNorm[k]=dirModel[dirModel.length-1]; } });
}
function attachSessionsToModel(){
  dirModel.forEach(function(d){
    d.sessions=runSessions.filter(function(s){ return normDir(s.dir)===d.norm; });
    d.running=d.sessions.length;
    d.lastActivity=d.last_ts||0;
    d.sessions.forEach(function(s){ var t=(s.last_output_ts||s.started||0); if(t>d.lastActivity) d.lastActivity=t; });
  });
  dirModel.sort(function(a,b){ return (b.running?1:0)-(a.running?1:0) || (b.lastActivity||0)-(a.lastActivity||0); });
}
function nFindRunSession(sid){
  for(var i=0;i<runSessions.length;i++){ if(runSessions[i].sid===sid) return runSessions[i]; }
  return null;
}
function nRenderYoloBadge(s){
  var el=$("nativeyolo"); if(!el) return;
  if(s && s.yolo){
    el.textContent="Auto";
    el.title="Auto approve is enabled for this session";
    el.style.display="";
  }else{
    el.style.display="none";
    el.textContent="Auto";
  }
}
function nHasPendingUi(st, state){
  if(!st || !st.root) return false;
  if(state==="confirm") return !!st.root.querySelector(".nmsg.approval,.nmsg.ask,.nmsg.form");
  if(state==="plan") return !!st.root.querySelector(".nmsg.plan");
  return true;
}
function nEnsurePendingVisible(s){
  if(!s || s.sid!==currentSid || (s.state!=="confirm" && s.state!=="plan")) return;
  var st=nativeStages[s.sid]; if(!st || nHasPendingUi(st, s.state)) return;
  var ws=nativeWs[s.sid], now=Date.now();
  if(ws && (ws.readyState===0 || ws.readyState===1)) return;
  if(st.lastPendingResync && now-st.lastPendingResync<30000) return;
  st.lastPendingResync=now;
  st.pendingExpectedAt=now;
  nativeScheduleReconnect(s.sid, 0);
}
function rememberSessions(ss, skipPendingOpen){
  runSessions=ss||[]; sessionsLoaded=true;
  var _rg=0,_pg=0; (ss||[]).forEach(function(s){ if(s.state==="running")_rg++; else if(s.state==="confirm"||s.state==="plan")_pg++; });
  var _parts=[]; if(_rg)_parts.push(_rg+" 生成中"); if(_pg)_parts.push(_pg+" 待处理");
  var rc=$("runcnt"); if(rc) rc.textContent=_parts.length?("· "+_parts.join(" · ")):"";
  var _visibleCatchup=null;
  if(currentSid){
    var _cs=nFindRunSession(currentSid), _prev=sessionWatch[currentSid];
    if(_cs){
      nSetGen(_cs.state==="running"); nRenderYoloBadge(_cs); nEnsurePendingVisible(_cs);
      _visibleCatchup={session:_cs, prevState:_prev&&_prev.state};
    }
  }
  Object.keys(nativeStages).forEach(function(sid){ if(!ss.some(function(s){return s.sid===sid;})) dropNativeStage(sid); });
  ss.forEach(function(s){
    var prev=sessionWatch[s.sid];
    if(prev && prev.state){
      if(s.state==="confirm" && prev.state!=="confirm") emitAiNotice("confirm", s);
      else if(s.state==="plan" && prev.state!=="plan") emitAiNotice("plan", s);
      else if(s.state==="idle" && prev.state!=="idle" && prev.state!=="new") emitAiNotice("done", s);
    }
    sessionWatch[s.sid]={state:s.state, last_output_ts:s.last_output_ts||0, last_input_ts:s.last_input_ts||0};
  });
  Object.keys(sessionWatch).forEach(function(sid){ if(!ss.some(function(s){return s.sid===sid;})) delete sessionWatch[sid]; });
  pruneOpenTabs(); renderSessionTabs();
  if(dirModel.length && !sbArchived){
    ensureSessionDirs(); attachSessionsToModel();
    var sig=sessionSignature(); if(sig!==lastSig){ lastSig=sig; renderSidebar(); }
  }
  if(_visibleCatchup && typeof nativeMaybeCatchupPoll==="function"){
    nativeMaybeCatchupPoll(_visibleCatchup.session, _visibleCatchup.prevState);
  }
  if(!skipPendingOpen && pendingOpenSid){ openSessionBySid(pendingOpenSid, true); pendingOpenSid=""; try{ history.replaceState(null,"",location.pathname); }catch(e){} }
}
function pollSessionSignals(){ api("/api/sessions").then(function(r){ rememberSessions(r.sessions||[]); }); }

function updateHistoryFilterButtons(){
  var active=$("hist-active"), archived=$("hist-archived");
  if(active) active.classList.toggle("active", !sbArchived);
  if(archived) archived.classList.toggle("active", !!sbArchived);
}
function setHistoryView(archived){
  archived=!!archived;
  if(sbArchived===archived){ updateHistoryFilterButtons(); return; }
  sbArchived=archived;
  try{ localStorage.setItem("acHistoryView", archived?"archived":"active"); }catch(e){}
  dirExpandClicks={}; lastSig="";
  loadSidebarData();
  updateHistoryFilterButtons();
}
function loadSidebarData(){
  updateHistoryFilterButtons();
  var loadSeq=++sidebarLoadSeq;
  var histUrl="/api/history?limit=200&live_codex=1"+(sbArchived?"&archived=1":"");
  var dirsReq=sbArchived ? Promise.resolve({dirs:[]}) : api("/api/recent_dirs?limit=50");
  Promise.all([dirsReq, api(histUrl)]).then(function(res){
    if(loadSeq!==sidebarLoadSeq) return;
    var dirs=res[0].dirs||[], hist=res[1].history||[];
    var map={}, order=[];
    function ensure(cwd){ var k=normDir(cwd); if(!map[k]){ map[k]={cwd:cwd, norm:k, count:0, last_ts:0, history:[], sessions:[]}; order.push(k); } return map[k]; }
    dirs.forEach(function(d){ var e=ensure(d.cwd); e.count=d.count||0; if((d.last_ts||0)>e.last_ts) e.last_ts=d.last_ts||0; });
    hist.forEach(function(h){ var e=ensure(h.cwd||"(unknown directory)"); e.history.push(h); if((h.ts||0)>e.last_ts) e.last_ts=h.ts||0; });
    dirModel=order.map(function(k){ return map[k]; });
    if(!sbArchived){ ensureSessionDirs(); attachSessionsToModel(); }
    lastSig=sessionSignature(); renderSidebar();
  });
}


function matchConvs(d, q){
  if(!q) return {sessions:(d.sessions||[]).slice(), history:(d.history||[]).slice()};
  var ms=(d.sessions||[]).filter(function(s){ return (s.title||"").toLowerCase().indexOf(q)>=0 || (s.dir||"").toLowerCase().indexOf(q)>=0; });
  var mh=(d.history||[]).filter(function(h){ return (h.title||"").toLowerCase().indexOf(q)>=0 || (h.cwd||"").toLowerCase().indexOf(q)>=0; });
  return {sessions:ms, history:mh};
}
function renderSidebar(){
  var list=$("dirlist"); var st=list.scrollTop;
  list.innerHTML="";
  var q=sbSearch.toLowerCase();
  var shown=dirModel.filter(function(d){
    if(!q) return true;
    if((d.cwd||"").toLowerCase().indexOf(q)>=0) return true;
    var mc=matchConvs(d,q); return mc.sessions.length || mc.history.length;
  });
  if(!shown.length){
    list.appendChild(empty(sbSearch?"没有匹配的目录":(sbArchived?"没有已归档的 Codex 会话":"还没有目录。点「新建」开始。")));
    list.scrollTop=st; return;
  }
  shown.forEach(function(d){ list.appendChild(renderDirRow(d, q)); });
  list.scrollTop=st;
}
