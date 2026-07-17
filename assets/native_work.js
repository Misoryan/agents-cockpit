"use strict";
function nativeViewIsWork(){ return nativeViewMode==="work"; }
function nativeSetViewMode(mode, persist){
  mode = mode==="work" ? "work" : "chat";
  nativeViewMode = mode;
  if(persist!==false){
    try{ localStorage.setItem("acNativeView", mode); }catch(e){}
    if(typeof acPrefSet==="function") acPrefSet("acNativeView", mode, "acNativeView");
  }
  nativeRenderViewToggle();
  if(currentSid){
    var s=nFindRunSession(currentSid);
    showNativeSession(currentSid, s&&(s.title||basename(s.dir)));
  }
}
function nativeRenderViewToggle(){
  var chat=$("nview-chat"), work=$("nview-work");
  if(chat){ chat.classList.toggle("active", nativeViewMode!=="work"); chat.setAttribute("aria-pressed", nativeViewMode==="work"?"false":"true"); }
  if(work){ work.classList.toggle("active", nativeViewMode==="work"); work.setAttribute("aria-pressed", nativeViewMode==="work"?"true":"false"); }
}
function nativeWorkStage(sid){
  if(nativeWorkStages[sid]) return nativeWorkStages[sid];
  var d=document.createElement("div");
  d.className="work-stage";
  d.style.cssText="display:none;width:100%;flex-direction:column;gap:12px";
  d.dataset.sid=sid;
  d.addEventListener("click", function(e){
    var btn=e.target && e.target.closest ? e.target.closest("[data-work-action]") : null;
    if(!btn) return;
    var action=btn.dataset ? btn.dataset.workAction : "";
    if(action==="chat-turn"){ nativeWorkToggleTurnChat(sid, btn); }
    if(action==="refresh"){ nativeWorkPollOnce(sid, true); }
  });
  $("nativemsgs").appendChild(d);
  nativeWorkStages[sid]={sid:sid, root:d, lastSig:"", pollTimer:null, elapsedTimer:null, elapsedBaseMs:null, fetchId:0, lastPrompt:""};
  return nativeWorkStages[sid];
}
function nativeDropWorkStage(sid){
  var st=nativeWorkStages[sid]; if(!st) return;
  nativeStopWorkPolling(sid);
  st.fetchId=(st.fetchId||0)+1;
  if(st.root && st.root.parentNode) st.root.parentNode.removeChild(st.root);
  delete nativeWorkStages[sid];
  delete nativeWorkBusy[sid];
}
function nativeHideAllWorkStages(){
  Object.keys(nativeWorkStages).forEach(function(sid){ if(nativeWorkStages[sid].root) nativeWorkStages[sid].root.style.display="none"; });
}
function nativeCloseChatTransport(sid){
  if(typeof nativeStopPolling==="function") nativeStopPolling(sid);
  if(nativeReconnectTimers[sid]){ clearTimeout(nativeReconnectTimers[sid]); delete nativeReconnectTimers[sid]; }
  var ws=nativeWs[sid];
  if(ws){
    nativeWs[sid]=null;
    try{ ws.close(); }catch(e){}
  }
}
function nativeShowWorkSession(sid){
  nativeRenderViewToggle();
  Object.keys(nativeStages).forEach(function(k){ nativeStages[k].root.style.display="none"; });
  nativeHideAllWorkStages();
  var st=nativeWorkStage(sid);
  st.root.style.display="flex";
  nativeCloseChatTransport(sid);
  nativeStartWorkPolling(sid, true);
  nativeWorkScrollTop(true);
  nUpdateScrollButton();
}
function nativeHideWorkSession(sid){
  if(sid && nativeWorkStages[sid] && nativeWorkStages[sid].root) nativeWorkStages[sid].root.style.display="none";
  nativeStopWorkPolling(sid);
}
function nativeStopWorkPolling(sid){
  var st=nativeWorkStages[sid];
  if(st && st.pollTimer){ clearTimeout(st.pollTimer); st.pollTimer=null; }
  if(st) nativeStopWorkElapsedTimer(st);
  delete nativeWorkBusy[sid];
}
function nativeWorkPollDelay(sid){
  var s=nFindRunSession(sid);
  if(s && (s.state==="running" || s.state==="confirm" || s.state==="plan")) return 1500;
  return 4500;
}
function nativeStartWorkPolling(sid, immediate){
  if(!sid || currentSid!==sid || !nativeViewIsWork()) return;
  var st=nativeWorkStage(sid);
  if(st.pollTimer) return;
  st.pollTimer=setTimeout(function(){
    st.pollTimer=null;
    nativeWorkPollOnce(sid);
  }, immediate?0:nativeWorkPollDelay(sid));
}
function nativeWorkPollOnce(sid, manual){
  if(!sid || currentSid!==sid || !nativeViewIsWork()) return;
  var st=nativeWorkStage(sid);
  if(nativeWorkBusy[sid]){ nativeStartWorkPolling(sid,false); return; }
  var fetchId=++st.fetchId;
  nativeWorkBusy[sid]=true;
  var url="/api/nreplay?sid="+encodeURIComponent(sid)+"&view=work";
  api(url).then(function(r){
    nativeWorkBusy[sid]=false;
    if(!nativeWorkStages[sid] || nativeWorkStages[sid]!==st || st.fetchId!==fetchId) return;
    if(r && r.ok!==false) nativeRenderWork(sid, r, manual);
    nativeStartWorkPolling(sid,false);
  }).catch(function(){
    nativeWorkBusy[sid]=false;
    if(!nativeWorkStages[sid] || nativeWorkStages[sid]!==st || st.fetchId!==fetchId) return;
    nativeRenderWorkError(sid);
    nativeStartWorkPolling(sid,false);
  });
}
function nativeWorkMaybeRefresh(s, prevSession){
  if(!s || s.sid!==currentSid || !nativeViewIsWork()) return;
  var changed=!prevSession || s.state!==prevSession.state || Number(s.last_output_ts||0)>Number(prevSession.last_output_ts||0);
  if(changed) nativeWorkPollOnce(s.sid);
}
function nativeWorkMarkSubmitted(sid, prompt){
  if(!nativeViewIsWork()) return;
  var st=nativeWorkStage(sid);
  st.lastPrompt=String(prompt||"").slice(0,500);
  nativeRenderWork(sid, {ok:true, work:{status:"running", running:true, turn_elapsed_ms:0, tool_total:0, file_total:0, turns:[{status:"running", user_text:st.lastPrompt, tools:[], tool_total:0, tool_counts:{}, tool_summary:[], latest_tool:null, files:[], file_total:0, commands:[], todos:[], elapsed_ms:0, assistant_text:""}], latest_todos:[], pending_count:0}}, true);
  nativeStartWorkPolling(sid, true);
}
function nWorkStatusText(status, running){
  if(status==="confirm") return "等待确认";
  if(status==="plan") return "计划待确认";
  if(running || status==="running") return "运行中";
  if(status==="error") return "出错";
  if(status==="new") return "新会话";
  return "空闲";
}
function nWorkTurnStatusText(status){
  if(status==="running") return "进行中";
  if(status==="error") return "失败";
  if(status==="interrupted") return "已打断";
  return "完成";
}
function nWorkSafeStatus(status){
  status=String(status||"");
  return /^(running|done|error|interrupted|pending|in_progress|completed|confirm|plan|idle|new)$/.test(status) ? status : "pending";
}
function nWorkElapsedMs(work){
  var ms=Number(work&&work.turn_elapsed_ms);
  if(ms>=0) return ms;
  if(work && work.running && work.turn_started_at_ms && work.server_now_ms){
    ms=Number(work.server_now_ms)-Number(work.turn_started_at_ms);
    return ms>=0 ? ms : null;
  }
  if(work && work.running && work.turn_started_at_ms){
    ms=Date.now()-Number(work.turn_started_at_ms||0);
    return ms>=0 ? ms : null;
  }
  return null;
}
function nWorkElapsed(work){
  var ms=nWorkElapsedMs(work);
  return ms!=null ? nFmtDur(ms) : "";
}
function nativeStopWorkElapsedTimer(st){
  if(st && st.elapsedTimer){ clearInterval(st.elapsedTimer); st.elapsedTimer=null; }
}
function nativeWorkAtTop(){
  var m=$("nativemsgs");
  return !m || m.scrollTop < 80;
}
function nativeWorkScrollTop(stick){
  if(!stick) return;
  var m=$("nativemsgs"); if(!m) return;
  requestAnimationFrame(function(){ m.scrollTop=0; nUpdateScrollButton(); });
}
function nativeWorkUpdateElapsed(st){
  if(!st || !st.root || st.elapsedBaseMs==null) return;
  var label=nFmtDur(Date.now()-st.elapsedBaseMs);
  var nodes=st.root.querySelectorAll ? st.root.querySelectorAll(".work-elapsed") : [];
  for(var i=0;i<nodes.length;i++) nodes[i].textContent=label;
}
function nativeWorkSyncElapsed(st, work){
  nativeStopWorkElapsedTimer(st);
  st.elapsedBaseMs=null;
  var ms=nWorkElapsedMs(work);
  if(!(work && work.running && ms!=null)) return;
  st.elapsedBaseMs=Date.now()-ms;
  nativeWorkUpdateElapsed(st);
  st.elapsedTimer=setInterval(function(){ nativeWorkUpdateElapsed(st); }, 1000);
}
function nativeWorkStablePayload(value){
  if(Array.isArray(value)) return value.map(nativeWorkStablePayload);
  if(value && typeof value==="object"){
    var out={};
    Object.keys(value).sort().forEach(function(k){
      if(k==="server_now_ms" || k==="turn_elapsed_ms" || k==="turn_started_at_ms" || k==="elapsed_ms" || k==="last_seq") return;
      out[k]=nativeWorkStablePayload(value[k]);
    });
    return out;
  }
  return value;
}
function nativeWorkRenderSignature(work, pending){
  try{ return JSON.stringify({work:nativeWorkStablePayload(work||{}), pending:nativeWorkStablePayload(pending||[])}); }
  catch(e){ return String(Date.now()); }
}
function nativeWorkRememberOpenDetails(st){
  var open={};
  if(!st || !st.root || !st.root.querySelectorAll) return open;
  var nodes=st.root.querySelectorAll("details[data-work-detail]");
  for(var i=0;i<nodes.length;i++){
    var key=nodes[i].getAttribute ? nodes[i].getAttribute("data-work-detail") : "";
    if(key && nodes[i].open) open[key]=true;
  }
  return open;
}
function nativeWorkRestoreOpenDetails(st, open){
  if(!open || !st || !st.root || !st.root.querySelectorAll) return;
  var nodes=st.root.querySelectorAll("details[data-work-detail]");
  for(var i=0;i<nodes.length;i++){
    var key=nodes[i].getAttribute ? nodes[i].getAttribute("data-work-detail") : "";
    if(key && open[key]) nodes[i].open=true;
  }
}
function nWorkTodosHtml(todos){
  todos=Array.isArray(todos)?todos:[];
  if(!todos.length) return "";
  var done=0; todos.forEach(function(t){ if((t.status||"")==="completed") done++; });
  return '<div class="work-todos"><div class="work-subhead">'+_I('list-checks')+' 任务 '+done+'/'+todos.length+'</div>'+
    todos.map(function(t){
      var st=t.status||"pending";
      var ic=st==="completed"?_I('circle-check'):(st==="in_progress"?_I('circle-dashed'):_I('circle'));
      return '<div class="work-todo '+nWorkSafeStatus(st)+'"><span>'+ic+'</span><b>'+nEsc(t.content||"")+'</b></div>';
    }).join("")+'</div>';
}
function nWorkInt(value, fallback){
  var n=Number(value);
  return isFinite(n) && n>=0 ? n : (fallback||0);
}
function nWorkToolTotal(turn){
  var tools=Array.isArray(turn&&turn.tools)?turn.tools:[];
  return nWorkInt(turn&&turn.tool_total, tools.length);
}
function nWorkFileTotal(turn){
  var files=Array.isArray(turn&&turn.files)?turn.files:[];
  return nWorkInt(turn&&turn.file_total, files.length);
}
function nWorkCountsText(counts, summary){
  var rows=[];
  if(Array.isArray(summary)){
    summary.slice(0,4).forEach(function(item){
      if(item && item.name) rows.push(String(item.name)+" x"+nWorkInt(item.count,0));
    });
  }else{
    Object.keys(counts||{}).slice(0,4).forEach(function(k){ rows.push(k+" x"+nWorkInt(counts[k],0)); });
  }
  return rows.filter(Boolean).join(" / ");
}
function nWorkShort(text, limit){
  text=String(text||"").replace(/\s+/g," ").trim();
  limit=limit||96;
  return text.length>limit ? text.slice(0, Math.max(0, limit-1)).trim()+"…" : text;
}
function nWorkToolBits(tool){
  tool=tool||{};
  var bits=[];
  if(tool.status==="failed") bits.push("failed");
  if(tool.exit_code!=null && tool.exit_code!=="") bits.push("exit "+tool.exit_code);
  if(tool.duration_ms!=null && tool.duration_ms!=="" ) bits.push(nFmtDur(tool.duration_ms));
  if(tool.output_lines) bits.push(tool.output_lines+" lines");
  if(tool.diff) bits.push("diff +"+(tool.diff.added||0)+" -"+(tool.diff.deleted||0));
  return bits.join(" · ");
}
function nWorkTurnElapsedHtml(turn){
  var ms=Number(turn&&turn.elapsed_ms);
  if(!(ms>=0)) return "";
  return ' · <span class="work-turn-elapsed work-elapsed" title="本轮运行时间">'+nEsc(nFmtDur(ms))+'</span>';
}
function nWorkLatestToolInfo(turn){
  turn=turn||{};
  var tools=Array.isArray(turn.tools)?turn.tools:[];
  var tool=turn.latest_tool||tools[tools.length-1];
  var idx=tools.length?tools.length-1:0;
  if(tool && tools.length){
    var id=tool.id, seq=tool.merged_seq||tool.seq;
    var matched=false;
    for(var i=tools.length-1;i>=0;i--){
      var candidate=tools[i]||{};
      if(candidate===tool || (id && candidate.id===id) || (seq && (candidate.merged_seq===seq || candidate.seq===seq))){
        idx=i;
        tool=Object.assign({}, candidate, tool);
        matched=true;
        break;
      }
    }
    if(!matched) tool=Object.assign({}, tools[idx]||{}, tool);
  }
  return {tool:tool, idx:idx, total:nWorkToolTotal(turn)};
}
function nWorkCurrentActionHtml(turn){
  var info=nWorkLatestToolInfo(turn);
  var tool=info.tool;
  if(!tool) return '<div class="work-current-action empty">'+_I('loader')+' <b>等待最近动作</b><em>正在分析，尚未开始工具动作。</em></div>';
  var bits=nWorkToolBits(tool);
  return '<div class="work-current-action '+nWorkSafeStatus(tool.status||"running")+'">'+
    '<span>最近动作</span><b>'+nEsc(tool.name||"Tool")+'</b>'+
    '<em>'+nEsc(nWorkShort(tool.label||"", 110))+'</em>'+
    (bits?'<small>'+nEsc(bits)+'</small>':'')+
  '</div>';
}
function nWorkCompleteHtml(turn, toolTotal, fileTotal, isLatest){
  var bits=[];
  bits.push(toolTotal+" 个动作");
  if(fileTotal) bits.push(fileTotal+" 个文件");
  if(turn&&turn.duration_ms!=null) bits.push(nFmtDur(turn.duration_ms));
  var hidden=turn&&turn.assistant_text ? (isLatest?'<em>AI 总结回复默认展开，可收起。</em>':'<em>AI 总结回复默认折叠，下方可展开查看。</em>') :
    (turn&&turn.assistant_text_hidden&&turn.assistant_text_chars ? '<em>最终回复已折叠（'+nEsc(String(turn.assistant_text_chars))+' 字），可切到 Chat View 查看。</em>' : '<em>详细过程已折叠，可切到 Chat View 查看。</em>');
  var title=(turn&&turn.status)==="error" ? "本轮失败" : "本轮已完成";
  return '<div class="work-complete '+nWorkSafeStatus(turn&&turn.status||"done")+'"><span>'+title+'</span><b>'+nEsc(bits.filter(Boolean).join(" · ")||"无工具动作")+'</b>'+hidden+'</div>';
}
function nWorkTurnKey(turn, idx){
  return String((turn&&(turn.key||turn.seq||turn.merged_seq))||("turn-"+idx));
}
function nWorkChangedFilesHtml(turn, detailKey){
  var rows=Array.isArray(turn&&turn.changed_files)?turn.changed_files:[];
  if(!rows.length) return "";
  var added=nWorkInt(turn&&turn.diff_added,0), deleted=nWorkInt(turn&&turn.diff_deleted,0);
  var total=nWorkInt(turn&&turn.diff_total, added+deleted);
  return '<details class="work-file-details" data-work-detail="'+nEscAttr(detailKey||"files")+'"><summary>改动文件一览 · '+rows.length+' 文件 · '+total+' 行 <span>+'+added+' -'+deleted+'</span></summary>'+
    '<div class="work-file-list">'+rows.map(function(row){
      var a=nWorkInt(row&&row.added,0), d=nWorkInt(row&&row.deleted,0);
      return '<div class="work-file-row"><b>'+nEsc(row&&row.path||"")+'</b><span class="add">+'+a+'</span><span class="del">-'+d+'</span></div>';
    }).join("")+'</div></details>';
}
function nWorkFinalHtml(turn, detailKey, open){
  var text=String((turn&&turn.assistant_text)||"").trim();
  if(!text) return "";
  var chars=turn&&turn.assistant_text_chars ? " · "+turn.assistant_text_chars+" 字" : "";
  var trunc=turn&&turn.assistant_text_truncated ? " · 已截断" : "";
  return '<details class="work-final-details" data-work-detail="'+nEscAttr(detailKey||"final")+'"'+(open?' open':'')+'><summary>AI 总结回复'+nEsc(chars+trunc)+'</summary><div class="work-final">'+renderMd(text)+'</div></details>';
}
function nWorkProgressHtml(turn){
  var text=String((turn&&turn.assistant_text)||"").trim();
  if(!text) return "";
  var chars=turn&&turn.assistant_text_chars ? " · "+turn.assistant_text_chars+" 字" : "";
  var trunc=turn&&turn.assistant_text_truncated ? " · 已截断" : "";
  return '<div class="work-progress"><div class="work-subhead">AI 中途回复'+nEsc(chars+trunc)+'</div><div class="work-progress-body">'+renderMd(text)+'</div></div>';
}
function nWorkErrorHtml(turn){
  if(!turn || turn.status!=="error") return "";
  var err=String(turn.error||"本轮执行失败，未提供详细错误。").trim();
  return '<div class="work-error"><span>错误</span><pre>'+nEsc(err)+'</pre></div>';
}
function nWorkUserTextHtml(turn){
  var full=String((turn&&turn.user_text)||"").trim();
  return '<div class="work-user">'+nEsc(full||"Agent turn")+'</div>';
}
function nWorkTurnHtml(turn, idx, total){
  turn=turn||{};
  var toolTotal=nWorkToolTotal(turn), fileTotal=nWorkFileTotal(turn);
  var running=turn.status==="running";
  var meta=[nWorkTurnStatusText(turn.status), toolTotal?toolTotal+" 动作":"0 动作", fileTotal?fileTotal+" 文件":""].filter(Boolean);
  var clock=nFmtClock(running ? turn.started_ts : turn.finished_ts);
  if(clock) meta.push((running?"开始 ":"完成 ")+clock);
  meta=meta.join(" · ");
  var metaHtml=nEsc(meta)+(running ? nWorkTurnElapsedHtml(turn) : "");
  var isLatest=idx===total-1;
  var detailKey="final-"+nWorkTurnKey(turn, idx);
  var filesKey="files-"+nWorkTurnKey(turn, idx);
  var chatKey=nWorkTurnKey(turn, idx);
  return '<section class="work-turn '+nWorkSafeStatus(turn.status||"done")+'">'+
    '<div class="work-turn-head"><div><span class="work-pill">'+nEsc("#"+(idx+1))+'</span></div><em>'+metaHtml+'</em></div>'+
    nWorkUserTextHtml(turn)+
    (isLatest?'':nWorkTodosHtml(turn.todos||[]))+
    (running?nWorkCurrentActionHtml(turn):nWorkCompleteHtml(turn, toolTotal, fileTotal, isLatest))+
    (running?nWorkProgressHtml(turn):'')+
    nWorkErrorHtml(turn)+
    nWorkChangedFilesHtml(turn, filesKey)+
    (!running?nWorkFinalHtml(turn, detailKey, isLatest):'')+
    '<div class="work-actions"><button type="button" class="ghost" data-work-action="chat-turn" data-work-turn-key="'+nEscAttr(chatKey)+'">查看本卡 Chat View</button></div>'+
    '<div class="work-turn-chat" data-work-chat-key="'+nEscAttr(chatKey)+'" hidden></div>'+
  '</section>';
}
function nWorkPendingHtml(pending){
  pending=(pending||[]).filter(function(ev){ return ev && (ev.type==="pending_approval" || ev.type==="pending_ask" || ev.type==="pending_form"); });
  if(!pending.length) return "";
  return '<div class="work-pending"><b>'+_I('alert')+' 需要处理 '+pending.length+' 项确认</b>'+
    pending.map(function(ev){ return '<div><span>'+nEsc(ev.name||ev.question||ev.message||ev.type)+'</span></div>'; }).join("")+
    '<em>请在输入框工具栏选择 Chat 处理确认。</em></div>';
}
function nativeWorkTurnRows(turns){
  turns=Array.isArray(turns)?turns:[];
  return turns.map(function(t,i){ return {turn:t, idx:i}; }).reverse();
}
function nWorkHistoryHtml(rows, total){
  rows=Array.isArray(rows)?rows:[];
  if(!rows.length) return "";
  return '<details class="work-history" data-work-detail="history"><summary>历史轮次 · '+rows.length+' 轮</summary><div class="work-history-body">'+
    rows.map(function(row){ return nWorkTurnHtml(row.turn,row.idx,total); }).join("")+
    '</div></details>';
}
function nWorkContextHtml(cwd, model){
  var bits=[];
  if(cwd) bits.push('<span class="work-ctx" title="'+nEscAttr(cwd)+'">'+_I('folder')+nEsc(basename(cwd))+'</span>');
  if(model) bits.push('<span class="work-ctx" title="'+nEscAttr("Model: "+model)+'">'+_I('sparkles')+nEsc(nShortModel(model))+'</span>');
  return bits.length?'<span class="work-context">'+bits.join("")+'</span>':"";
}
function nativeRenderWork(sid, payload, force){
  var st=nativeWorkStage(sid), work=(payload&&payload.work)||{}, pending=(payload&&payload.pending)||[];
  var snap=(payload&&payload.snapshot)||{}, s=nFindRunSession(sid);
  var cwd=String(snap.cwd||(s&&s.dir)||"");
  var model=String(snap.model||((nativeStages[sid]||{}).model)||"");
  var sig=nativeWorkRenderSignature(work, pending)+"|"+cwd+"|"+model;
  if(!force && sig===st.lastSig){ nativeWorkSyncElapsed(st, work); return; }
  var stickTop=force || !st.lastSig || nativeWorkAtTop();
  var openDetails=nativeWorkRememberOpenDetails(st);
  st.lastSig=sig;
  var turns=work.turns||[], elapsed=nWorkElapsed(work), status=nWorkStatusText(work.status, work.running);
  var turnRows=nativeWorkTurnRows(turns);
  var latestRow=turnRows.length?turnRows[0]:null, historyRows=turnRows.slice(1);
  var totals={tools:nWorkInt(work.tool_total,0), files:nWorkInt(work.file_total,0)};
  if(!totals.tools) turns.forEach(function(t){ totals.tools+=nWorkToolTotal(t); });
  if(!totals.files) turns.forEach(function(t){ totals.files+=nWorkFileTotal(t); });
  var html='<div class="work-board"><div class="work-hero '+nWorkSafeStatus(work.status||"idle")+'">'+
    '<div><div class="work-head-row"><span class="work-kicker">Work View</span>'+nWorkContextHtml(cwd, model)+'</div><h2>'+nEsc(status)+'</h2><p>过程内容已压缩：运行中显示最近动作和 AI 中途回复，完成后只显示数量概览。</p></div>'+
    '<div class="work-metrics"><span>'+nEsc(String(work.turn_count||turns.length))+' turns</span><span>'+totals.tools+' actions</span><span>'+totals.files+' files</span>'+(elapsed?'<span class="work-elapsed">'+nEsc(elapsed)+'</span>':'')+'</div>'+
    '<button type="button" class="ghost" data-work-action="refresh">刷新</button></div>'+
    nWorkPendingHtml(pending)+
    nWorkTodosHtml(work.latest_todos||[])+
    (latestRow?nWorkTurnHtml(latestRow.turn,latestRow.idx,turns.length):'<div class="work-empty">暂无对话快照。发送消息后这里会显示任务进度。</div>')+
    nWorkHistoryHtml(historyRows, turns.length)+
    '</div>';
  st.root.innerHTML=html;
  nativeWorkRestoreOpenDetails(st, openDetails);
  nativeWorkSyncElapsed(st, work);
  nHljs(st.root);
  nativeWorkScrollTop(stickTop);
}
function nativeWorkPreviewStage(root){
  return {sid:"", root:root, curTxt:null, curThink:null, turnCard:null, shownCount:0, model:"", lastToolGroup:null,
          planMode:null, taskMode:null, todos:null, tasksCollapsed:false, lastPendingResync:0,
          renderedEvents:{}, lastBatchSig:"", lastSeq:0, replayActive:false, replayPending:[], replayCard:null,
          replayTimer:null, replayWaiting:false, replayWaitTimer:null, replayRunId:0, lastReplayBatchSig:"",
          replaySigParts:[], replayFetchId:0, lastCatchupPoll:0, catchupInFlight:false,
          lastWasHumanUser:false, lastHumanText:""};
}
function nativeWorkRenderTurnChat(sid, key, panel, payload){
  var events=(payload&&payload.events)||[];
  if(!events.length){
    panel.innerHTML='<div class="work-chat-empty">这一卡片暂无可展示的 Chat 事件。</div>';
    return;
  }
  var body=document.createElement("div");
  body.className="work-chat-body";
  panel.innerHTML="";
  panel.appendChild(body);
  var previewSid=sid+"::work::"+key;
  var st=nativeWorkPreviewStage(body);
  st.sid=previewSid;
  nativeStages[previewSid]=st;
  try{
    events.forEach(function(ev){
      var obj=Object.assign({}, ev||{});
      obj.replay=true;
      nHandle(previewSid, obj);
    });
  }catch(e){
    body.innerHTML='<div class="work-chat-empty">Chat 预览渲染失败：'+nEsc(e&&e.message||e)+'</div>';
  }finally{
    if(st.thinkTimer){ clearInterval(st.thinkTimer); st.thinkTimer=null; }
    if(st.replayTimer){ clearTimeout(st.replayTimer); st.replayTimer=null; }
    if(st.replayWaitTimer){ clearTimeout(st.replayWaitTimer); st.replayWaitTimer=null; }
    delete nativeStages[previewSid];
  }
  nHljs(body);
}
function nativeWorkToggleTurnChat(sid, btn){
  var key=btn && btn.dataset ? btn.dataset.workTurnKey : "";
  var card=btn && btn.closest ? btn.closest(".work-turn") : null;
  var panel=card && card.querySelector ? card.querySelector(".work-turn-chat") : null;
  if(!key || !panel) return;
  if(!panel.hidden){
    panel.hidden=true;
    btn.textContent="查看本卡 Chat View";
    return;
  }
  panel.hidden=false;
  btn.textContent="收起本卡 Chat View";
  if(panel.dataset.loaded==="1") return;
  panel.innerHTML='<div class="work-chat-empty">正在加载这一卡片的 Chat View…</div>';
  var url="/api/nreplay?sid="+encodeURIComponent(sid)+"&view=turn&turn="+encodeURIComponent(key);
  api(url).then(function(r){
    if(panel.hidden) return;
    if(!r || r.ok===false){
      panel.innerHTML='<div class="work-chat-empty">这一卡片 Chat View 加载失败：'+nEsc(r&&r.error||"unknown error")+'</div>';
      return;
    }
    panel.dataset.loaded="1";
    nativeWorkRenderTurnChat(sid, key, panel, r);
  }).catch(function(e){
    if(panel.hidden) return;
    panel.innerHTML='<div class="work-chat-empty">这一卡片 Chat View 加载失败：'+nEsc(e&&e.message||e)+'</div>';
  });
}
function nativeRenderWorkError(sid){
  var st=nativeWorkStage(sid);
  if(st.root && !st.root.innerHTML){
    st.root.innerHTML='<div class="work-board"><div class="work-empty">Work View 加载失败，稍后会自动重试。</div></div>';
  }
}
