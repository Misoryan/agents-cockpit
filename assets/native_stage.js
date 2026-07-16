"use strict";
function nativeStage(sid){
  if(nativeStages[sid]) return nativeStages[sid];
  var d=document.createElement("div");
  d.style.cssText="display:none;width:100%;flex-direction:column;gap:10px";
  d.dataset.sid=sid; $("nativemsgs").appendChild(d);
  nativeStages[sid]={sid:sid, root:d, curTxt:null, curThink:null, turnCard:null, shownCount:0, model:"", lastToolGroup:null,
                      planMode:null, taskMode:null, todos:null, tasksCollapsed:false, lastPendingResync:0,
                      renderedEvents:{}, lastBatchSig:"", lastSeq:0, replayActive:false, replayPending:[], replayCard:null, replayTimer:null,
                      replayWaiting:false, replayWaitTimer:null, lastReplayBatchSig:"", replaySigParts:[],
                      lastCatchupPoll:0, catchupInFlight:false};
  return nativeStages[sid];
}
function dropNativeStage(sid){
  var st=nativeStages[sid]; if(!st) return;
  if(st.root.parentNode) st.root.parentNode.removeChild(st.root);
  delete nativeStages[sid];
  if(nativeReconnectTimers[sid]){ clearTimeout(nativeReconnectTimers[sid]); delete nativeReconnectTimers[sid]; }
  delete nativeReconnectState[sid];
  if(nativePollTimers[sid]){ clearTimeout(nativePollTimers[sid]); delete nativePollTimers[sid]; }
  delete nativePollBusy[sid];
  if(nativeWs[sid]){ try{ nativeWs[sid].close(); }catch(e){} delete nativeWs[sid]; }
  if(currentSid===sid) hideNative();
}
function hideNative(){ currentSid=null; nSetGen(false); setMainView("landing"); renderSessionTabs(); nUpdateScrollButton(); }
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
function nAddRow(st, cls, html){
  if(cls!=="result") st.lastToolGroup=null;
  st.curTxt=null;
  var d=document.createElement("div"); d.className="nmsg "+cls;
  d.innerHTML=html; if(cls==="user"){var _mt=document.createElement("div");_mt.className="mtime";_mt.textContent=_msgTime();d.appendChild(_mt);} (st.turnCard||st.root).appendChild(d); nScrollBottom();
}
function nFirstValue(obj, keys){
  obj=obj||{};
  for(var i=0;i<keys.length;i++){
    var v=obj[keys[i]];
    if(v!=null && v!=="") return v;
  }
  return "";
}
function nMiniKvHtml(rows){
  rows=(rows||[]).filter(function(r){ return r && r[1]!=null && r[1]!==""; });
  if(!rows.length) return "";
  return '<div class="special-kv">'+rows.map(function(r){
    return '<div><span>'+nEsc(r[0])+'</span><b>'+nEsc(r[1])+'</b></div>';
  }).join("")+'</div>';
}
function nSafeLinkHtml(url, cls){
  url=String(url||"");
  var safe=url.indexOf("http://")===0 || url.indexOf("https://")===0 || url.indexOf("/api/")===0;
  return safe ? '<a class="'+cls+'" href="'+nEscAttr(url)+'" target="_blank" rel="noopener">'+nEsc(url)+'</a>'
              : '<div class="'+cls+'">'+nEsc(url)+'</div>';
}
function nSpecialToolBody(name, input){
  name=String(name||"").toLowerCase(); input=input||{};
  if(name==="sleep"){
    var dur=nFirstValue(input, ["durationMs","duration_ms","milliseconds","ms","seconds","duration"]);
    return '<div class="special-card sleep-card"><div class="special-title">'+_I('hourglass')+' Sleep</div>'+
           nMiniKvHtml([["duration", dur], ["reason", input.reason||input.message||""]])+'</div>';
  }
  if(name==="contextcompaction"){
    return '<div class="special-card compact-card"><div class="special-title">'+_I('archive')+' Context compaction</div>'+
           nMiniKvHtml([["status", input.status||input.phase||""], ["tokens", input.tokens||input.tokenCount||input.inputTokens||""], ["summary", input.summary||input.message||""]])+'</div>';
  }
  if(name==="imagegeneration"){
    var prompt=input.prompt||input.description||input.text||"";
    var imageSize=input.size || ((input.width&&input.height)?(input.width+"x"+input.height):"");
    return '<div class="special-card image-card"><div class="special-title">'+_I('sparkles')+' Image generation</div>'+
           (prompt?'<div class="special-prompt">'+nEsc(prompt)+'</div>':'')+
           nMiniKvHtml([["size", imageSize], ["model", input.model||""]])+'</div>';
  }
  if(name==="imageview"){
    var path=input.path||input.file||input.url||input.imageUrl||"";
    return '<div class="special-card image-card"><div class="special-title">'+_I('file-text')+' Image view</div>'+
           (path?nSafeLinkHtml(path, "special-path"):"")+
           nMiniKvHtml([["mime", input.mimeType||input.mime||""], ["size", input.size||""]])+'</div>';
  }
  return "";
}
function nToolInputPreview(input){
  if(!input || typeof input!=="object" || Array.isArray(input)) return "";
  var keys=Object.keys(input), shown=keys.slice(0,4);
  if(!shown.length) return "";
  return '<div class="tool-arg-preview">'+shown.map(function(k){
    var v=input[k], text=(v && typeof v==="object")?JSON.stringify(v):String(v);
    return '<div><span>'+nEsc(k)+'</span><b>'+nEsc(text.slice(0,180))+'</b></div>';
  }).join("")+(keys.length>shown.length?'<div><span>more</span><b>'+nEsc(keys.length-shown.length)+' fields</b></div>':'')+'</div>';
}
function nStructuredToolBody(name, input){
  var raw=String(name||""), lower=raw.toLowerCase();
  if(lower.indexOf(".")<0 && lower.indexOf("/")<0) return "";
  if(["webfetch","websearch","exitplanmode"].indexOf(lower)>=0) return "";
  var split=raw.indexOf(".")>=0 ? raw.split(".", 2) : raw.split("/", 2);
  var server=split[0]||"tool", tool=raw.slice((split[0]||"").length+1)||raw;
  var pretty="";
  try{ pretty=JSON.stringify(input||{}, null, 2); }catch(e){ pretty=String(input||""); }
  return '<div class="special-card mcp-card"><div class="special-title">'+_I('wrench')+' Tool call</div>'+
         nMiniKvHtml([["server", server], ["tool", tool]])+
         nToolInputPreview(input||{})+
         '<details class="tool-args"><summary>Arguments</summary><pre>'+nEsc(pretty)+'</pre></details></div>';
}
function nShellGroupKey(name){
  name=String(name||"").toLowerCase();
  return (name==="bash"||name==="powershell")?name:"";
}
function nAppendShellGroupEntry(st, b, summaryHtml, bodyHtml){
  var key=nShellGroupKey(b.name), g=st.lastToolGroup, host=nTurnCard(st);
  if(!g || g.key!==key || !g.el || !g.el.parentNode){
    var card=document.createElement("div");
    card.className="nmsg tool tool-group";
    card.innerHTML='<details><summary class="tool-group-summary"></summary><div class="tool-group-body"></div></details>';
    host.appendChild(card);
    g={key:key, el:card, count:0, summary:card.querySelector(".tool-group-summary"), body:card.querySelector(".tool-group-body"), baseSummary:summaryHtml};
    st.lastToolGroup=g;
  }
  g.count++;
  g.summary.innerHTML=g.baseSummary+' <span class="tcdesc">(x'+g.count+')</span>';
  var entry=document.createElement("div");
  entry.className="tool-entry";
  entry.dataset.tuid=b.id||"";
  entry.dataset.tname=b.name||"";
  entry.innerHTML='<div class="tool-entry-idx">#'+g.count+'</div>'+bodyHtml+'<div class="tres">Running...</div>';
  g.body.appendChild(entry);
  st.curTxt=null; nScrollBottom();
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
/* 事件指纹:用 type+uuid 序列 + 数量签名(不 stringify 正文,免得大对话卡顿)。
   同一份事件流 → 同一指纹;新增/裁剪事件 → 指纹变。用于「内容没变就跳过重放」杜绝闪屏。 */
