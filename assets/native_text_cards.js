"use strict";
function nNewTextBubble(st){
  var d=document.createElement("div"); d.className="nmsg assistant";
  var t=document.createElement("div"); t.className="ntxt";
  d.appendChild(t); var _mt=document.createElement("div"); _mt.className="mtime"; _mt.textContent=_msgTime(); d.appendChild(_mt); nTurnCard(st).appendChild(d); st.curTxt=t; nScrollBottom();
}
function nStartThinking(st, startedAt){
  nSetThinkingStart(st, startedAt);
  if(st.thinking || st.thinkBox){ nUpdateThinkingLabel(st); return; }
  st.thinking=true;
  var d=document.createElement("div"); d.className="nmsg assistant thinking-ind";
  d.innerHTML='<span class="ti-dot"></span><span class="ti-txt"></span>';
  nTurnCard(st).appendChild(d); st.thinkBubble=d; nUpdateThinkingLabel(st); nScrollBottom();
  st.thinkTimer=setInterval(function(){ nUpdateThinkingLabel(st); },1000);
}
function nStopThinking(st){
  st.thinking=false;
  if(st.thinkTimer){ clearInterval(st.thinkTimer); st.thinkTimer=null; }
  if(st.thinkBubble){
    var card=st.thinkBubble.parentNode;
    st.thinkBubble.remove(); st.thinkBubble=null;
    nPruneEmptyTurn(st, card);
  }
}
/* 收束思考框:停止计时、摘要显示耗时、默认折叠;清空引用以便下一轮思考重建 */
function nFinalizeThinking(st){
  if(st.thinkTimer){ clearInterval(st.thinkTimer); st.thinkTimer=null; }
  if(st.thinkBox){
    var dur=st.thinkStart?nThinkingSeconds(st):0;
    if(st.thinkSum) st.thinkSum.innerHTML = st.thinkStart?(_I('message-circle')+' \u601d\u8003 ('+dur+'s)'):_I('message-circle')+' \u601d\u8003';
    st.thinkBox.open=false;
  }
  st.curThink=null; st.thinkBox=null; st.thinkSum=null; st.thinkStart=null;
}

function nAppendThinkingDelta(st, obj, thinking){
  st.lastToolGroup=null;
  if(st.thinkBubble) nStopThinking(st);
  if(!st.curThink){
    nSetThinkingStart(st, obj);
    var _thd=document.createElement("details"); _thd.open=false;
    var _sum=document.createElement("summary"); _sum.innerHTML=_I('message-circle')+' '+nThinkingLabel(st);
    var _pre=document.createElement("pre");
    _thd.appendChild(_sum); _thd.appendChild(_pre);
    nTurnCard(st).appendChild(_thd);
    st.curThink=_pre; st.thinkBox=_thd; st.thinkSum=_sum;
    if(st.thinkTimer){ clearInterval(st.thinkTimer); st.thinkTimer=null; }
    st.thinkTimer=setInterval(function(){ nUpdateThinkingLabel(st); },1000);
  }
  st.curThink.appendChild(document.createTextNode(thinking));
  nScrollBottom();
}

function nHandleStreamEvent(sid, st, obj){
  if(currentSid===sid) nSetGen(true);
  var dl=(obj.event||{}).delta||{};
  if(dl.type==="text_delta" && dl.text){
    st.lastToolGroup=null;
    nFinalizeThinking(st);
    nStopThinking(st);
    if(!st.curTxt) nNewTextBubble(st);
    st.curTxt.appendChild(document.createTextNode(dl.text));
    nScrollBottom();
  } else if(dl.type==="thinking_delta" && dl.thinking){
    nAppendThinkingDelta(st, obj, dl.thinking);
  }
}

function nRenderAssistantThinkingBlock(sid, st, obj, block){
  st.lastToolGroup=null;
  if(obj.replay){
    var _th=document.createElement("details");
    _th.innerHTML='<summary>'+_I('message-circle')+' \u601d\u8003</summary><pre>'+nEsc(block.thinking||"")+'</pre>';
    nTurnCard(st).appendChild(_th); nScrollBottom();
  }
}
function nExtractProposedPlan(text){
  text=String(text==null?"":text);
  var open="<proposed_plan>", close="</proposed_plan>";
  var s=text.indexOf(open);
  if(s<0) return null;
  var e=text.indexOf(close, s+open.length);
  if(e<0) return null;
  return {before:text.slice(0,s).trim(), plan:text.slice(s+open.length,e).trim(), after:text.slice(e+close.length).trim()};
}
function nSetPromptIfEmpty(text){
  var inp=$("nativeinput");
  if(inp && !inp.value.trim()){ inp.value=text; }
  if(inp){ inp.focus({preventScroll:true}); }
}
function nAcceptProposedPlan(sid, st, card){
  card.querySelectorAll("button").forEach(function(b){ b.disabled=true; });
  postJSON("/api/nmode",{sid:sid, plan:false}).then(function(r){
    if(r && r.error){ nAddRow(st, "sys", _I('alert')+' 退出 Plan 模式失败: '+nEsc(r.error)); return; }
    st.planMode=false; localStorage.setItem("acPlan_"+sid, "0");
    if(currentSid===sid){ nSyncModes(st); nSetPromptIfEmpty("请按上一条计划开始实现。"); }
    pollSessionSignals();
    var h=card.querySelector(".plan-head"); if(h) h.innerHTML=_I('clipboard-list')+' 计划方案 · 已采纳并退出 Plan 模式';
  }).catch(function(e){
    card.querySelectorAll("button").forEach(function(b){ b.disabled=false; });
    nAddRow(st, "sys", _I('alert')+' 退出 Plan 模式失败: '+nEsc(e&&e.message||e));
  });
}
function nKeepPlanning(st){
  if(currentSid){ nSetPromptIfEmpty("请继续完善上面的计划："); }
}
function nRenderAssistantText(sid, st, text){
  st.lastToolGroup=null;
  var pp=nExtractProposedPlan(text);
  if(!pp){
    if(!text || !String(text).trim()){ return; }
    if(!st.curTxt) nNewTextBubble(st);
    st.curTxt.innerHTML=renderMd(text); nHljs(st.curTxt);
    return;
  }
  var old=st.curTxt?st.curTxt.closest(".nmsg.assistant"):null;
  if(old) old.remove();
  st.curTxt=null;
  if(pp.before){
    nNewTextBubble(st);
    st.curTxt.innerHTML=renderMd(pp.before); nHljs(st.curTxt);
    st.curTxt=null;
  }
  var pcard=document.createElement("div"); pcard.className="nmsg plan codex-plan";
  pcard.innerHTML='<div class="plan-head">'+_I('clipboard-list')+' 计划方案 · Codex Plan Mode</div><div class="plan-body">'+renderMd(pp.plan)+'</div>'+
    '<div class="abtns"><button class="allow">'+_I('circle-check')+' 采纳并退出 Plan 模式</button><button class="deny">'+_I('pencil')+' 继续完善计划</button></div>';
  nHljs(pcard.querySelector(".plan-body"));
  pcard.querySelector(".allow").addEventListener("click", function(){ nAcceptProposedPlan(sid, st, pcard); });
  pcard.querySelector(".deny").addEventListener("click", function(){ nKeepPlanning(st); });
  nTurnCard(st).appendChild(pcard);
  if(pp.after){
    nNewTextBubble(st);
    st.curTxt.innerHTML=renderMd(pp.after); nHljs(st.curTxt);
    st.curTxt=null;
  }
  nScrollBottom();
}
