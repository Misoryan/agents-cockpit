"use strict";
var _nGenerating=false;
function nSetGen(on){
  if(_nGenerating===on) return;
  _nGenerating=on;
  var sb=$("nativesubmit"); if(!sb) return;
  sb.innerHTML = on ? _I('square') : _I('arrow-up');
  sb.title = on ? "停止生成" : "发送 (Enter)";
}
function nInterrupt(){
  if(!currentSid) return;
  postJSON("/api/ninterrupt",{sid:currentSid}).then(function(){}).catch(function(){});
}
function nativeSend(){
  var inp=$("nativeinput"), p=inp.value.trim();
  if(!p || !currentSid) return;
  var st=nativeStage(currentSid); if(!st) return;
  var _w=nativeWs[currentSid];
  if(!_w||_w.readyState>1){ nativeConnect(currentSid); }
  nHandle(currentSid, {type:"user", message:{role:"user", content:p}});   // 渲染用户气泡,并计入「已渲染指纹」(与服务端 replay 的合成 user 事件同形 → 重连可命中跳过)
  nStartThinking(st);
  inp.value=""; inp.style.height="auto";
  nSetGen(true);
  postJSON("/api/nsend", {sid:currentSid, prompt:p, plan:!!st.planMode, task:!!st.taskMode}).then(function(r){
    if(r && r.error){ nFinalizeThinking(st); nStopThinking(st); nAddRow(st, "sys", "\u26a0\ufe0f \u53d1\u9001\u5931\u8d25: "+nEsc(r.error)+"\uff08\u82e5\u521a\u66f4\u65b0\u4ee3\u7801,\u8bf7\u300c\u8bbe\u7f6e \u2192 \u91cd\u542f\u540e\u7aef\u5c42\u300d\u52a0\u8f7d native.py \u540e\u5237\u65b0\u9875\u9762\uff09"); nEndTurn(st); nSetGen(false); }
  }).catch(function(e){ nFinalizeThinking(st); nStopThinking(st); nAddRow(st, "sys", "\u26a0\ufe0f \u7f51\u7edc\u9519\u8bef: "+nEsc(e&&e.message||e)); nEndTurn(st); nSetGen(false); });
}
$("nativeback").addEventListener("click", hideNative);
$("nativesend").addEventListener("submit", function(e){ e.preventDefault(); if(_nGenerating){ nInterrupt(); }else{ nativeSend(); } });
/* 计划/任务模式开关:点击翻转 stage 状态 + 即时同步 UI + 推后端(/api/nmode 广播 mode_state 回环确认)。
   plan/task 两键独立,可同时开(先计划后任务跟踪)。持久化进 localStorage,跨刷新保留。 */
function nToggleMode(which){
  if(!currentSid) return;
  var st=nativeStage(currentSid); if(!st) return;
  var key = which==="plan"?"planMode":"taskMode";
  st[key]=!st[key];
  if(which==="plan"){ localStorage.setItem("acPlan_"+currentSid, st.planMode?"1":"0"); }
  else { localStorage.setItem("acTask_"+currentSid, st.taskMode?"1":"0"); }
  nSyncModes(st);
  var payload={sid:currentSid}; payload[which]=st[key];
  postJSON("/api/nmode", payload);
}
$("nmode-plan").addEventListener("click", function(){ nToggleMode("plan"); });
$("nmode-task").addEventListener("click", function(){ nToggleMode("task"); });
$("nativeinput").addEventListener("keydown", function(e){ if(e.key==="Enter" && !e.shiftKey){ e.preventDefault(); nativeSend(); } });
$("nativeinput").addEventListener("input", function(){ this.style.height="auto"; this.style.height=Math.min(this.scrollHeight,200)+"px"; });
$("nativemsgs").addEventListener("scroll", nUpdateScrollButton);
$("scrollbottom").addEventListener("click", nJumpBottom);
document.addEventListener("keydown", function(e){
  if(e.ctrlKey && e.key==="Tab"){ e.preventDefault(); switchTab(e.shiftKey?-1:1); }
});
function openSessionBySid(sid, skipFetch){
  if(!sid) return false;
  var i, s; for(i=0;i<runSessions.length;i+=1){ if(runSessions[i].sid===sid){ s=runSessions[i]; break; } }
  if(s){
    showNativeSession(s.sid, s.title||basename(s.dir));
    return true;
  }
  if(!skipFetch){ api("/api/sessions").then(function(r){ rememberSessions(r.sessions||[], true); openSessionBySid(sid, true); }); }
  return false;
}
