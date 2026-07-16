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
function nToolResultHtml(txt){
  var _nl=String.fromCharCode(10), _lines=String(txt).split(_nl).length;
  var _resSum='Result ('+_lines+' lines)';
  return '<details class="tres-det"><summary>'+nEsc(_resSum)+'</summary><pre>'+nEsc(txt)+'</pre></details>';
}
function nDiffStats(txt){
  var lines=String(txt==null?"":txt).split(String.fromCharCode(10));
  var files={}, add=0, del=0;
  function fkey(path){
    path=String(path||"");
    if(path.indexOf("a/")===0 || path.indexOf("b/")===0) path=path.slice(2);
    return path;
  }
  lines.forEach(function(line){
    if(line.indexOf("diff --git ")===0){
      var parts=line.split(" ");
      files[fkey(parts[3]||parts[2]||line)]=true;
    }
    else if(line.indexOf("+++ ")===0){ files[fkey(line.slice(4))]=true; }
    else if(line.indexOf("+")===0){ add++; }
    else if(line.indexOf("-")===0 && line.indexOf("--- ")!==0){ del++; }
  });
  var fileCount=Object.keys(files).filter(function(k){ return k && k!=="/dev/null"; }).length;
  return {lines:lines.length, files:fileCount, add:add, del:del};
}
function nLooksLikeDiff(txt){
  txt=String(txt==null?"":txt);
  return txt.indexOf("diff --git ")>=0 || txt.indexOf(String.fromCharCode(10)+"@@ ")>=0 ||
         txt.indexOf("--- ")===0 || txt.indexOf(String.fromCharCode(10)+"--- ")>=0;
}
function nDiffLineClass(line){
  if(line.indexOf("@@")===0) return "du-hunk";
  if(line.indexOf("diff --git ")===0 || line.indexOf("index ")===0 || line.indexOf("+++ ")===0 || line.indexOf("--- ")===0) return "du-file";
  if(line.indexOf("+")===0) return "du-add";
  if(line.indexOf("-")===0) return "du-del";
  return "du-line";
}
function nDiffResultHtml(txt){
  txt=String(txt==null?"":txt);
  var st=nDiffStats(txt), summary="Diff";
  if(st.files) summary+=" · "+st.files+" file"+(st.files>1?"s":"");
  summary+=" · +"+st.add+" -"+st.del+" · "+st.lines+" lines";
  var rows=txt.split(String.fromCharCode(10)).map(function(line){
    return '<span class="du-line '+nDiffLineClass(line)+'">'+nEsc(line || " ")+'</span>';
  }).join("");
  return '<details class="tres-det diff-det" open><summary>'+nEsc(summary)+'</summary><pre class="diff-unified">'+rows+'</pre></details>';
}
function nTryJson(txt){
  txt=String(txt==null?"":txt).trim();
  if(!txt || ("[{".indexOf(txt.charAt(0))<0)) return null;
  try{ return JSON.parse(txt); }catch(e){ return null; }
}
function nJsonResultSummary(obj, toolName){
  var label=toolName?("JSON · "+toolName):"JSON result";
  if(Array.isArray(obj)) return label+" · "+obj.length+" items";
  if(obj && typeof obj==="object"){
    var n=0; Object.keys(obj).forEach(function(){ n++; });
    if(obj.isError || obj.error) label+=" · error";
    else if(Array.isArray(obj.content)) label+=" · "+obj.content.length+" content";
    else if(Array.isArray(obj.contents)) label+=" · "+obj.contents.length+" resource";
    else label+=" · "+n+" fields";
  }
  return label;
}
function nJsonResultPreview(obj){
  var items=[];
  function addText(t){ t=String(t||"").trim(); if(t) items.push(t.slice(0,240)); }
  if(Array.isArray(obj)){ obj.slice(0,3).forEach(function(x){ addText(typeof x==="string"?x:JSON.stringify(x)); }); }
  else if(obj && typeof obj==="object"){
    var arr=Array.isArray(obj.content)?obj.content:(Array.isArray(obj.contents)?obj.contents:[]);
    arr.slice(0,3).forEach(function(x){ addText((x&&x.text) || (x&&x.uri) || (x&&x.name) || JSON.stringify(x)); });
    if(!items.length && obj.error) addText(obj.error);
  }
  if(!items.length) return "";
  return '<div class="json-preview">'+items.map(function(t){ return '<div>'+nEsc(t)+'</div>'; }).join("")+'</div>';
}
function nJsonResultHtml(txt, toolName){
  var obj=nTryJson(txt);
  if(obj==null) return "";
  var pretty;
  try{ pretty=JSON.stringify(obj,null,2); }catch(e){ pretty=txt; }
  var summary=nJsonResultSummary(obj, toolName);
  return '<details class="tres-det json-det" open><summary>'+nEsc(summary)+'</summary>'+nJsonResultPreview(obj)+'<pre class="json-result">'+nEsc(pretty)+'</pre></details>';
}
function nToolResultMarkup(toolId, txt, toolName){
  if(toolId==="turn-diff" || nLooksLikeDiff(txt)) return nDiffResultHtml(txt);
  var json=nJsonResultHtml(txt, toolName);
  return json || nToolResultHtml(txt);
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
function nFindToolResultHost(st, tuid){
  var root=st.turnCard||st.root, nodes=root.querySelectorAll('.tool-entry,.nmsg.tool');
  for(var i=0;i<nodes.length;i++){ if(nodes[i].dataset && nodes[i].dataset.tuid===String(tuid||"")) return nodes[i]; }
  return null;
}
function nFindStandaloneResultHost(st, tuid){
  if(!tuid) return null;
  var root=st.turnCard||st.root, nodes=root.querySelectorAll('.nmsg.result[data-tuid]');
  for(var i=nodes.length-1;i>=0;i--){ if(nodes[i].dataset && nodes[i].dataset.tuid===String(tuid)) return nodes[i]; }
  return null;
}
function nRenderToolResult(st, tuid, txt){
  var tu=nFindToolResultHost(st, tuid);
  var toolName=tu&&tu.dataset?tu.dataset.tname:"";
  var html=nToolResultMarkup(tuid, txt, toolName);
  if(tu){
    var r=tu.querySelector('.tres'); if(r){ r.innerHTML=html; }
    return;
  }
  var old=nFindStandaloneResultHost(st, tuid);
  if(old){ old.innerHTML=html; return; }
  var d=document.createElement("div"); d.className="nmsg result";
  if(tuid) d.dataset.tuid=String(tuid);
  d.innerHTML=html; (st.turnCard||st.root).appendChild(d); nScrollBottom();
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
