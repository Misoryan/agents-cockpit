"use strict";
function nApprove(sid, tuid, allow, always){ postJSON("/api/napprove", {sid:sid, tool_use_id:tuid, allow:allow, always:!!always}); }
function nativeReconnectDelay(sid, baseDelay){
  var rs=nativeReconnectState[sid]||{attempts:0,lastLog:0};
  var base=baseDelay==null?1500:baseDelay;
  if(base<=0) return 0;
  var mult=Math.pow(2, Math.min(5, Math.max(0, rs.attempts||0)));
  return Math.min(30000, Math.max(base, base*mult));
}
function nativeScheduleReconnect(sid, delay){
  if(!sid || currentSid!==sid || !nativeStages[sid]) return;
  var ws=nativeWs[sid];
  if(ws && (ws.readyState===0 || ws.readyState===1)) return;
  if(nativeReconnectTimers[sid]) return;
  var wait=nativeReconnectDelay(sid, delay);
  nativeReconnectTimers[sid]=setTimeout(function(){
    delete nativeReconnectTimers[sid];
    if(currentSid===sid) nativeConnect(sid);
  }, wait);
}
function nativeConnect(sid, opts){
  opts=opts||{};
  var existing=nativeWs[sid];
  if(existing && (existing.readyState===0 || existing.readyState===1) && !opts.force) return existing;
  if(nativeReconnectTimers[sid]){ clearTimeout(nativeReconnectTimers[sid]); delete nativeReconnectTimers[sid]; }
  if(existing){ try{ existing.close(); }catch(e){} }
  var st=nativeStage(sid);
  if(st){
    var hasContent=nStageHasReplayContent(st);
    if(!hasContent){
      nStopThinking(st); st.curTxt=null; st.curThink=null; st.turnCard=null;
    }
    nReplayProgressCancel(st);
    if(currentSid===sid && !hasContent){
      st.replayWaiting=true;
      st.replayWaitTimer=setTimeout(function(){
        if(currentSid!==sid || st.replayActive || nStageHasReplayContent(st)) return;
        nReplayProgressStart(st,0,"Connecting session","waiting");
        st.replayWaitTimer=setTimeout(function(){ nReplayProgressWait(st); }, 8000);
      }, 250);
    }
  }
  var proto=location.protocol==="https:"?"wss:":"ws:";
  var afterSeq=(st && nStageHasReplayContent(st)) ? nativeReplayAfter(st) : 0;
  var after=afterSeq ? ("?after="+encodeURIComponent(String(afterSeq))) : "";
  var ws=new WebSocket(proto+"//"+location.host+"/t/"+sid+"/ws"+after);
  ws._afterSeq=afterSeq;
  ws._openedAt=Date.now();
  nativeWs[sid]=ws;
  ws.onopen=function(){
    if(nativeWs[sid]!==ws){
      if(window.NATIVE_DEBUG){ try{ console.log("[N] stale ws open ignored", sid); }catch(_e){} }
      try{ ws.close(); }catch(_e){}
      return;
    }
    nativeStopPolling(sid);
    var rs=nativeReconnectState[sid]||{attempts:0,lastLog:0};
    rs.openedAt=Date.now();
    nativeReconnectState[sid]=rs;
    setTimeout(function(){
      if(nativeWs[sid]===ws && ws.readyState===1){
        nativeReconnectState[sid]={attempts:0,lastLog:0,openedAt:Date.now()};
      }
    }, 10000);
  };
  ws.onmessage=function(ev){
    if(nativeWs[sid]!==ws) return;
    try{ nHandle(sid, JSON.parse(ev.data)); }catch(e){}
  };
  ws.onclose=function(ev){
    clearInterval(ws._ka);
    var isCurrent=(nativeWs[sid]===ws);
    if(!isCurrent){
      if(window.NATIVE_DEBUG){ try{ console.log("[N] stale ws close ignored", sid, "code="+ev.code); }catch(_e){} }
      return;
    }
    var now=Date.now(), rs=nativeReconnectState[sid]||{attempts:0,lastLog:0};
    var lived=now-(rs.openedAt||ws._openedAt||now);
    rs.attempts = lived>10000 ? 0 : Math.min(6, (rs.attempts||0)+1);
    nativeReconnectState[sid]=rs;
    if(window.NATIVE_DEBUG || now-(rs.lastLog||0)>10000){
      var _st=nativeStages[sid]||{};
      console.log("[N] ws closed", sid, "code="+ev.code, ev.reason||"",
        "retry="+nativeReconnectDelay(sid,1500)+"ms",
        "lastSeq="+((_st&&_st.lastSeq)||0),
        "after="+(ws._afterSeq||0),
        "hasContent="+(!!(_st&&nStageHasReplayContent(_st))),
        "visibility="+(document.visibilityState||""));
      rs.lastLog=now;
    }
    nativeWs[sid]=null;
    if(currentSid===sid && nativeStages[sid] && !(typeof nativeViewIsWork==="function" && nativeViewIsWork())){
      nativeStartPolling(sid, true);
      nativeScheduleReconnect(sid, 30000);
    }
  };
  ws.onerror=function(){ console.log("[N] ws error", sid); };
  ws._ka=setInterval(function(){ if(ws.readyState===1){ try{ ws.send("ping"); }catch(e){} } }, 20000);
}
/* 标签页切回前台:后台时浏览器(尤其手机)常会杀掉空闲 WS。与其干等 onclose 的 1.5s 重试,
   不如可见时立刻检查当前原生会话的 WS —— 不健康(无 / closing / closed)就连,健康就不动(避免无谓闪屏);
   顺手刷一下侧边栏状态(后台期间运行/需确认可能已变化)。 */
document.addEventListener("visibilitychange", function(){
  if(document.visibilityState !== "visible") return;
  var sid=currentSid;
  if(sid && nativeStages[sid]){
    var ws=nativeWs[sid];
    if(typeof nativeViewIsWork==="function" && nativeViewIsWork()){
      if(typeof nativeWorkPollOnce==="function") nativeWorkPollOnce(sid);
    }else if(!ws || ws.readyState>1){
      nativeStartPolling(sid, true);
      nativeScheduleReconnect(sid, 30000);
    }else if(nStageHasReplayContent(nativeStages[sid])){
      nativeCatchupPoll(sid, "foreground");
    }
  }
  pollSessionSignals();
});
function showNativeSession(sid, title){
  ensureTabOpen(sid);
  currentSid=sid;
  var _rs=nFindRunSession(sid);
  $("nativettl").textContent=title||(_rs&&(_rs.title||basename(_rs.dir)))||sid;
  nRenderModelBadge((nativeStages[sid]||{}).model||"");
  nRenderYoloBadge(_rs);
  nSetGen(!!(_rs && _rs.state==="running"));
  Object.keys(nativeStages).forEach(function(k){ nativeStages[k].root.style.display=(k===sid)?"flex":"none"; });
  var st=nativeStage(sid);
  // 恢复计划/任务模式开关:优先 stage 内存(切会话保持),首次加载从 localStorage 读
  if(st.planMode==null){ st.planMode = localStorage.getItem("acPlan_"+sid)==="1"; }
  if(st.taskMode==null){ st.taskMode = localStorage.getItem("acTask_"+sid)==="1"; }
  nSyncModes(st); nRenderTasks(st);
  if(typeof nativeRenderViewToggle==="function") nativeRenderViewToggle();
  // 后端(尤其重启后)模式可能已丢,把当前开关推回去重同步
  postJSON("/api/nmode",{sid:sid, plan:st.planMode, task:st.taskMode});
  if(typeof nativeViewIsWork==="function" && nativeViewIsWork()){
    if(typeof nativeShowWorkSession==="function") nativeShowWorkSession(sid);
  }else{
    if(typeof nativeHideWorkSession==="function") nativeHideWorkSession(sid);
    if(typeof nativeHideAllWorkStages==="function") nativeHideAllWorkStages();
    st.root.style.display="flex";
    if(!nStageHasReplayContent(st)) nativeStartPolling(sid, true);
    if(!nativeWs[sid] || nativeWs[sid].readyState>1){
      if(nStageHasReplayContent(st)) nativeConnect(sid);
      else nativeScheduleReconnect(sid, 1200);
    }
    if(nStageHasReplayContent(st)) nativeCatchupPoll(sid, "switch");
    nEnsurePendingVisible(nFindRunSession(sid));
  }
  renderSessionTabs();
  setMainView("native"); nUpdateScrollButton(); closeSidebar();
  setTimeout(function(){ $("nativeinput").focus({preventScroll:true}); }, 60);
}
