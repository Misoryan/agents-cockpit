"use strict";
/* ---- sessions + sidebar model ---- */
var runSessions=[], sessionWatch={}, dirModel=[], expanded={}, dirExpandClicks={}, sbSearch="", sbArchived=false, lastSig="", sidebarLoadSeq=0;
var pendingOpenSid=""; try{ pendingOpenSid=new URLSearchParams(location.search).get("open")||""; }catch(e){}
try{ sbArchived=localStorage.getItem("acHistoryView")==="archived"; }catch(e){ sbArchived=false; }

var openTabs=[], sessionsLoaded=false, sessionSwitcherOpen=false;
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
function sessionPriority(s){
  if(!s) return 0;
  if(s.state==="confirm") return 5;
  if(s.state==="plan") return 4;
  if(s.state==="running") return 3;
  if(s.state==="new") return 2;
  return 1;
}
function sessionStatusBadge(s){
  var dot=sessionDot(s), label=sessionStateText(s);
  if(dot==="idle") label="\u7a7a\u95f2";
  return {cls:dot, label:label};
}
function sessionActivityTs(s){
  return sessionSortTs(s);
}
function sessionRunStartedTs(s){
  return Number((s&&s.current_turn_started_at)||(s&&s.last_input_ts)||(s&&s.started)||0);
}
function sessionCompletedTs(s){
  return Number((s&&s.last_completed_at)||0);
}
function sessionSortTs(s){
  if(!s) return 0;
  var st=s.state||"";
  if(st==="running" || st==="confirm" || st==="plan"){
    return Number(s.current_turn_started_at||s.last_input_ts||s.started||0);
  }
  return sessionCompletedTs(s) || Number(s.last_output_ts||s.last_input_ts||s.started||0);
}
function sessionTitle(s){
  return (s&&(s.title||basename(s.dir)||s.sid)) || "";
}
function sessionSort(a,b){
  return sessionSortTs(b)-sessionSortTs(a) ||
    Number(b&&b.started||0)-Number(a&&a.started||0) ||
    String(a&&a.sid||"").localeCompare(String(b&&b.sid||""));
}
function openSessionMeta(s){
  var bits=["\u5df2\u5f00\u542f"], time=sessionTimeText(s);
  bits.push(time || (isFreshRecoveredSession(s)?"\u5df2\u6062\u590d":sessionStateText(s)));
  bits.push(backendShort(s.backend));
  if(s.yolo) bits.push("\u81ea\u52a8\u6279\u51c6");
  if(s.mode==="resume" && !isFreshRecoveredSession(s)) bits.push("\u6062\u590d");
  return bits.join(" \u00b7 ");
}
function isFreshRecoveredSession(s){
  if(!s || s.mode!=="resume") return false;
  if(s.state==="running" || s.state==="confirm" || s.state==="plan") return false;
  var started=Number(s.started||0), completed=sessionCompletedTs(s);
  if(!completed) return true;
  return !!started && completed <= started + 5;
}
function sessionTimeText(s){
  if(!s) return "";
  var st=s.state||"";
  if(st==="running"){
    var rt=sessionRunStartedTs(s);
    return rt ? ("\u5df2\u8fd0\u884c "+elapsedStr(rt)) : "\u8fd0\u884c\u4e2d";
  }
  if(st==="confirm"){
    var ct=sessionRunStartedTs(s);
    return ct ? ("\u5f85\u786e\u8ba4 \u00b7 \u5df2\u8fd0\u884c "+elapsedStr(ct)) : "\u5f85\u786e\u8ba4";
  }
  if(st==="plan"){
    var pt=sessionRunStartedTs(s);
    return pt ? ("\u8ba1\u5212\u4e2d \u00b7 \u5df2\u8fd0\u884c "+elapsedStr(pt)) : "\u8ba1\u5212\u4e2d";
  }
  if(isFreshRecoveredSession(s)) return "";
  if(st==="idle"){
    var done=sessionCompletedTs(s);
    return done ? (relTime(done)+"\u5b8c\u6210") : "\u7a7a\u95f2";
  }
  if(st==="new") return s.mode==="resume" ? "\u5df2\u6062\u590d" : "\u65b0\u4f1a\u8bdd";
  return sessionStateText(s);
}
function sessionTabMeta(s, model){
  var status=sessionTimeText(s) || (isFreshRecoveredSession(s)?"\u5df2\u6062\u590d":sessionStateText(s));
  return status+" / "+(model||backendShort(s.backend));
}
function sortedRunSessions(q){
  q=(q||"").toLowerCase();
  return (runSessions||[]).filter(function(s){
    if(!q) return true;
    return (sessionTitle(s)||"").toLowerCase().indexOf(q)>=0 || (s.dir||"").toLowerCase().indexOf(q)>=0;
  }).sort(sessionSort);
}
function renderSessionSwitcher(){
  var quick=$("sessionquick"), quickCount=$("sessionquick-count");
  var sessions=sortedRunSessions("");
  if(quick){
    quick.classList.toggle("available", sessions.length>1);
    quick.setAttribute("aria-expanded", sessionSwitcherOpen?"true":"false");
    quick.title=sessions.length>1?("切换 "+sessions.length+" 个已开启会话"):"切换已开启会话";
  }
  if(quickCount) quickCount.textContent=String(sessions.length||0);
  if(sessionSwitcherOpen && sessions.length<2) closeSessionSwitcher();
  var list=$("session-switcher-list"); if(!list) return;
  list.innerHTML="";
  if(!sessions.length){
    list.appendChild(empty("还没有已开启会话。"));
    return;
  }
  sessions.forEach(function(s){
    var state=sessionStatusBadge(s), title=sessionTitle(s);
    var row=document.createElement("button");
    row.type="button";
    row.className="ssrow ss-"+state.cls+(s.sid===currentSid?" current":"");
    if(s.sid===currentSid) row.setAttribute("aria-current", "page");
    row.title=title+"\n"+(s.dir||"");
    row.innerHTML='<span class="dot '+state.cls+'"></span>'+
      '<span class="ssmain"><span class="sst">'+esc(title)+'</span><span class="ssm">'+esc(openSessionMeta(s))+'</span></span>'+
      '<span class="ssbadge '+state.cls+'">'+esc(state.label)+'</span>';
    row.addEventListener("click", function(){ openSessionRow(s); });
    list.appendChild(row);
  });
}
function openSessionSwitcher(){
  if((runSessions||[]).length<2) return;
  sessionSwitcherOpen=true;
  renderSessionSwitcher();
  document.body.classList.add("session-switcher-open");
  var wrap=$("session-switcher"); if(wrap) wrap.setAttribute("aria-hidden","false");
  var quick=$("sessionquick"); if(quick) quick.setAttribute("aria-expanded","true");
}
function closeSessionSwitcher(){
  sessionSwitcherOpen=false;
  document.body.classList.remove("session-switcher-open");
  var wrap=$("session-switcher"); if(wrap) wrap.setAttribute("aria-hidden","true");
  var quick=$("sessionquick"); if(quick) quick.setAttribute("aria-expanded","false");
}
function toggleSessionSwitcher(){
  if(sessionSwitcherOpen) closeSessionSwitcher();
  else openSessionSwitcher();
}
function bindSessionSwitcher(){
  var quick=$("sessionquick");
  if(quick && !quick.dataset.bound){
    quick.dataset.bound="1";
    quick.addEventListener("click", function(ev){ ev.stopPropagation(); toggleSessionSwitcher(); });
  }
  var close=$("session-switcher-close");
  if(close && !close.dataset.bound){
    close.dataset.bound="1";
    close.addEventListener("click", closeSessionSwitcher);
  }
  var scrim=$("session-switcher-scrim");
  if(scrim && !scrim.dataset.bound){
    scrim.dataset.bound="1";
    scrim.addEventListener("click", closeSessionSwitcher);
  }
}
bindSessionSwitcher();
document.addEventListener("keydown", function(e){
  if(e.key==="Escape" && sessionSwitcherOpen) closeSessionSwitcher();
});
function renderSessionTabs(){
  var bar=$("sessiontabs"); if(!bar) return;
  bar.innerHTML="";
  var rendered=0;
  var activeRendered=false;
  openTabs.forEach(function(sid){
    var s=tabSession(sid); if(!s) return;
    var model=(nativeStages[sid]&&nativeStages[sid].model) ? nShortModel(nativeStages[sid].model) : "";
    var meta=sessionTabMeta(s, model);
    var btn=document.createElement("button"); btn.type="button"; btn.className="stab"+(sid===currentSid?" active":"");
    if(sid===currentSid) activeRendered=true;
    btn.title=(s.title||basename(s.dir)||sid)+"\n"+(s.dir||"");
    btn.innerHTML='<span class="dot '+sessionDot(s)+'"></span><span class="st-main"><span class="st-title">'+esc(s.title||basename(s.dir)||sid)+'</span><span class="st-meta">'+esc(meta)+'</span></span>';
    var close=document.createElement("span"); close.className="st-close"; close.setAttribute("aria-label","Close tab"); close.textContent="x";
    close.addEventListener("click", function(ev){ ev.stopPropagation(); closeTab(sid); });
    btn.appendChild(close);
    btn.addEventListener("click", function(){
      if(sid===currentSid && typeof isNarrow==="function" && isNarrow() && (runSessions||[]).length>1){
        toggleSessionSwitcher();
        return;
      }
      showNativeSession(sid, s.title||basename(s.dir));
    });
    bar.appendChild(btn); rendered++;
  });
  bar.classList.toggle("tabs-empty", !rendered);
  bar.classList.toggle("tabs-current", activeRendered);
  var dock=$("mobilebar"); if(dock) dock.classList.toggle("has-tabs", !!rendered);
  var ts=$("topstatus"); if(ts) ts.style.display=currentSid?"":"none";
  renderSessionSwitcher();
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
  return runSessions.slice().sort(function(a,b){ return a.sid<b.sid?-1:1; }).map(function(s){ return s.sid+":"+s.state+":"+(s.yolo?"1":"0")+":"+sessionSortTs(s); }).join("|");
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
    d.sessions.forEach(function(s){ var t=sessionSortTs(s); if(t>d.lastActivity) d.lastActivity=t; });
  });
  dirModel.sort(function(a,b){ return (b.lastActivity||0)-(a.lastActivity||0) || String(a.cwd||"").localeCompare(String(b.cwd||"")); });
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
  if(typeof nativeViewIsWork==="function" && nativeViewIsWork()) return;
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
      _visibleCatchup={session:_cs, prevSession:_prev};
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
  renderOpenSessions(sbSearch.toLowerCase());
  if(dirModel.length && !sbArchived){
    ensureSessionDirs(); attachSessionsToModel();
    var sig=sessionSignature(); if(sig!==lastSig){ lastSig=sig; renderSidebar(); }
  }
  if(_visibleCatchup && typeof nativeMaybeCatchupPoll==="function"){
    nativeMaybeCatchupPoll(_visibleCatchup.session, _visibleCatchup.prevSession);
  }
  if(_visibleCatchup && typeof nativeWorkMaybeRefresh==="function"){
    nativeWorkMaybeRefresh(_visibleCatchup.session, _visibleCatchup.prevSession);
  }
  if(!skipPendingOpen && pendingOpenSid){ openSessionBySid(pendingOpenSid, true); pendingOpenSid=""; try{ history.replaceState(null,"",location.pathname); }catch(e){} }
}
function pollSessionSignals(){ api("/api/sessions").then(function(r){ rememberSessions(r.sessions||[]); }); }

function updateHistoryFilterButtons(){
  var active=$("hist-active"), archived=$("hist-archived");
  if(active) active.classList.toggle("active", !sbArchived);
  if(archived) archived.classList.toggle("active", !!sbArchived);
  if(active) active.setAttribute("aria-pressed", sbArchived?"false":"true");
  if(archived) archived.setAttribute("aria-pressed", sbArchived?"true":"false");
  var title=$("history-section-title"), hint=$("history-section-hint"), search=$("sb-search");
  if(title) title.textContent=sbArchived?"归档":"项目";
  if(hint){
    hint.textContent=sbArchived?"仅显示已归档的 Codex 会话；已开启任务仍固定在上方。":"";
    hint.classList.toggle("show", !!sbArchived);
  }
  if(search) search.placeholder=sbArchived?"搜索归档历史 / 目录":"搜索目录 / 任务";
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
function compactSessionMeta(s){
  return openSessionMeta(s);
}
function openSessionRow(s){
  if(typeof closeSessionSwitcher==="function") closeSessionSwitcher();
  showNativeSession(s.sid, s.title||basename(s.dir));
  renderOpenSessions(sbSearch.toLowerCase());
  if(typeof isNarrow==="function" && isNarrow() && typeof closeSidebar==="function") closeSidebar();
}
function renderOpenSessionRow(s){
  var state=sessionStatusBadge(s);
  var row=document.createElement("button");
  row.type="button";
  row.className="osrow os-"+state.cls+(s.sid===currentSid?" current":"");
  if(s.sid===currentSid) row.setAttribute("aria-current", "page");
  row.title=(s.title||basename(s.dir)||s.sid)+"\n"+(s.dir||"");
  row.innerHTML='<span class="dot '+state.cls+'"></span><span class="osmain"><span class="ost">'+esc(s.title||basename(s.dir)||s.sid)+'</span><span class="osm">'+esc(compactSessionMeta(s))+'</span></span>'+
    '<span class="osbadge '+state.cls+'">'+esc(state.label)+'</span>';
  row.addEventListener("click", function(){ openSessionRow(s); });
  return row;
}
function sidebarOpenSessionsVisible(){
  if(typeof window==="undefined" || !window.matchMedia) return true;
  return !window.matchMedia("(max-width:640px)").matches;
}
function renderOpenSessions(q){
  var wrap=$("open-section"), list=$("openlist"), title=$("open-section-title");
  if(!wrap || !list) return;
  if(!sidebarOpenSessionsVisible()){
    list.innerHTML="";
    if(title) title.textContent="\u5df2\u5f00\u542f";
    wrap.style.display="none";
    return;
  }
  q=(q||"").toLowerCase();
  var sessions=sortedRunSessions(q);
  list.innerHTML="";
  sessions.forEach(function(s){ list.appendChild(renderOpenSessionRow(s)); });
  if(title) title.textContent=sessions.length?("\u5df2\u5f00\u542f \u00b7 "+sessions.length):"\u5df2\u5f00\u542f";
  wrap.style.display=sessions.length?"":"none";
}
if(typeof window!=="undefined" && window.addEventListener){
  window.addEventListener("resize", function(){ renderOpenSessions(sbSearch.toLowerCase()); });
}
function dirStatusInfo(d){
  var ss=(d&&d.sessions)||[];
  if(!ss.length) return null;
  var best=ss.slice().sort(function(a,b){ return sessionPriority(b)-sessionPriority(a); })[0];
  var state=sessionStatusBadge(best);
  var label;
  if(state.cls==="confirm") label="\u5f85\u786e\u8ba4 "+ss.length;
  else if(state.cls==="plan") label="\u8ba1\u5212 "+ss.length;
  else if(state.cls==="run") label="\u8fd0\u884c "+ss.length;
  else if(state.cls==="new") label="\u65b0\u5f00 "+ss.length;
  else label="\u7a7a\u95f2 "+ss.length;
  return {cls:state.cls, label:label};
}
function renderSidebar(){
  document.querySelectorAll(".cactions-pop").forEach(function(pop){ pop.remove(); });
  updateHistoryFilterButtons();
  var list=$("dirlist"); var st=list.scrollTop;
  list.innerHTML="";
  var q=sbSearch.toLowerCase();
  renderOpenSessions(q);
  var shown=dirModel.filter(function(d){
    if(!q) return true;
    if((d.cwd||"").toLowerCase().indexOf(q)>=0) return true;
    var mc=matchConvs(d,q); return mc.sessions.length || mc.history.length;
  });
  if(!shown.length){
    var emptyText=sbSearch?(sbArchived?"没有匹配的归档历史":"没有匹配的目录或任务"):(sbArchived?"没有已归档的 Codex 会话":"还没有目录。点「新建」开始。");
    list.appendChild(empty(emptyText));
    list.scrollTop=st; return;
  }
  shown.forEach(function(d){ list.appendChild(renderDirRow(d, q)); });
  list.scrollTop=st;
}
