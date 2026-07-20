"use strict";
function nativeViewIsWork(){ return true; }
function nativeSetViewMode(_mode, persist){
  nativeViewMode = "work";
  nativeRenderViewToggle();
  if(currentSid){
    var s=nFindRunSession(currentSid);
    showNativeSession(currentSid, s&&(s.title||basename(s.dir)));
  }
}
function nativeRenderViewToggle(){
  nativeViewMode = "work";
  if(document && document.body) document.body.classList.add("work-only");
}
function nativeWorkStage(sid){
  if(nativeWorkStages[sid]) return nativeWorkStages[sid];
  var d=document.createElement("div");
  d.className="work-stage";
  d.style.cssText="display:none;width:100%;flex-direction:column;gap:16px";
  d.dataset.sid=sid;
  d.addEventListener("click", function(e){
    var btn=e.target && e.target.closest ? e.target.closest("[data-work-action]") : null;
    if(!btn) return;
    var action=btn.dataset ? btn.dataset.workAction : "";
    if(action==="trace-turn") nativeWorkToggleTurnTrace(sid, btn);
    if(action==="file-diff") nativeWorkToggleFileDiff(sid, btn);
    if(action==="refresh") nativeWorkPollOnce(sid, true);
  });
  $("nativemsgs").appendChild(d);
  nativeWorkStages[sid]={sid:sid, root:d, lastSig:"", pollTimer:null, elapsedTimer:null, elapsedBaseMs:null, fetchId:0, lastPrompt:"", lastSignalPollAt:0, turnPayloads:{}};
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
function nativeCloseLiveTransport(sid){
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
  nativeCloseLiveTransport(sid);
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
  if(s && (s.state==="running" || s.state==="confirm" || s.state==="plan")) return 2200;
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
  var st=s.state||"", prevState=prevSession&&prevSession.state;
  var stateChanged=!prevSession || st!==prevState;
  var outputAdvanced=Number(s.last_output_ts||0)>Number(prevSession&&prevSession.last_output_ts||0);
  if(!stateChanged && outputAdvanced && (st==="running" || st==="confirm" || st==="plan")){
    nativeStartWorkPolling(s.sid, false);
    return;
  }
  if(!stateChanged && !outputAdvanced) return;
  var stage=nativeWorkStages[s.sid], now=Date.now();
  if(stage && stage.lastSignalPollAt && now-stage.lastSignalPollAt<1200) return;
  if(stage) stage.lastSignalPollAt=now;
  nativeWorkPollOnce(s.sid);
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
  if(status==="error") return "需要处理";
  if(status==="new") return "新任务";
  return "空闲";
}
function nWorkTurnStatusText(status){
  if(status==="running") return "运行中";
  if(status==="error") return "失败";
  if(status==="interrupted") return "已中断";
  return "已完成";
}
function nWorkSafeStatus(status){
  status=String(status||"");
  return /^(running|done|error|interrupted|pending|in_progress|completed|confirm|plan|idle|new|failed|empty)$/.test(status) ? status : "pending";
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
function nWorkTodosHtml(todos, opts){
  todos=Array.isArray(todos)?todos:[];
  if(!todos.length) return "";
  opts=opts||{};
  var done=0; todos.forEach(function(t){ if((t.status||"")==="completed") done++; });
  var complete=done===todos.length;
  var open=opts.open!=null ? !!opts.open : !complete;
  var state=complete?"completed":"active";
  var title='任务 '+done+'/'+todos.length+(complete?' 已完成':'');
  return '<details class="work-todos '+state+'" data-work-detail="'+nEscAttr(opts.key||"tasks")+'"'+(open?' open':'')+'><summary><span class="work-subhead">'+_I('list-checks')+' '+title+'</span></summary><div class="work-todo-list">'+todos.map(function(t){
    var st=t.status||"pending";
    var ic=st==="completed"?_I('circle-check'):(st==="in_progress"?_I('circle-dashed'):_I('circle'));
    return '<div class="work-todo '+nWorkSafeStatus(st)+'"><span>'+ic+'</span><b>'+nEsc(t.content||"")+'</b></div>';
  }).join("")+'</div></details>';
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
    summary.slice(0,4).forEach(function(item){ if(item && item.name) rows.push(String(item.name)+" x"+nWorkInt(item.count,0)); });
  }else{
    Object.keys(counts||{}).slice(0,4).forEach(function(k){ rows.push(k+" x"+nWorkInt(counts[k],0)); });
  }
  return rows.filter(Boolean).join(" / ");
}
function nWorkShort(text, limit){
  text=String(text||"").replace(/\s+/g," ").trim();
  limit=limit||96;
  return text.length>limit ? text.slice(0, Math.max(0, limit-1)).trim()+"..." : text;
}
function nWorkToolBits(tool){
  tool=tool||{};
  var bits=[];
  if(tool.status==="failed") bits.push("失败");
  if(tool.exit_code!=null && tool.exit_code!=="") bits.push("退出码 "+tool.exit_code);
  if(tool.duration_ms!=null && tool.duration_ms!=="" ) bits.push(nFmtDur(tool.duration_ms));
  if(tool.output_lines) bits.push(tool.output_lines+" 行");
  if(tool.diff) bits.push("diff +"+(tool.diff.added||0)+" -"+(tool.diff.deleted||0));
  return bits.join(" · ");
}
function nWorkTurnElapsedHtml(turn){
  var ms=Number(turn&&turn.elapsed_ms);
  if(!(ms>=0)) return "";
  return ' · <span class="work-turn-elapsed work-elapsed" title="本轮耗时">'+nEsc(nFmtDur(ms))+'</span>';
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
  if(!tool) return '<div class="work-current-action empty">'+_I('loader')+' <b>等待下一步动作</b><em>Agent 正在整理上下文，还没有开始工具操作。</em></div>';
  var bits=nWorkToolBits(tool);
  return '<div class="work-current-action '+nWorkSafeStatus(tool.status||"running")+'">'+
    '<span>当前动作</span><b>'+nEsc(tool.name||"工具")+'</b>'+
    '<em>'+nEsc(nWorkShort(tool.label||"", 110))+'</em>'+
    (bits?'<small>'+nEsc(bits)+'</small>':'')+
  '</div>';
}
function nWorkCompleteHtml(turn, toolTotal, fileTotal, isLatest){
  var bits=[];
  bits.push(toolTotal+" 次操作");
  if(fileTotal) bits.push(fileTotal+" 个文件");
  if(turn&&turn.duration_ms!=null) bits.push(nFmtDur(turn.duration_ms));
  var hidden=turn&&turn.assistant_text ? (isLatest?'<em>最终回复已展开，旧记录会自动收进历史。</em>':'<em>最终回复已折叠，可按需展开。</em>') :
    (turn&&turn.assistant_text_hidden&&turn.assistant_text_chars ? '<em>最终回复已折叠（'+nEsc(String(turn.assistant_text_chars))+' 字）。</em>' : '<em>原始事件已收起，可按需查看。</em>');
  var title=(turn&&turn.status)==="error" ? "本轮失败" : "本轮完成";
  return '<div class="work-complete '+nWorkSafeStatus(turn&&turn.status||"done")+'"><span>'+title+'</span><b>'+nEsc(bits.filter(Boolean).join(" · ")||"无工具操作")+'</b>'+hidden+'</div>';
}
function nWorkTurnKey(turn, idx){
  return String((turn&&(turn.key||turn.seq||turn.merged_seq))||("turn-"+idx));
}
function nWorkChangedFilesHtml(turn, detailKey, turnKey){
  var rows=Array.isArray(turn&&turn.changed_files)?turn.changed_files:[];
  if(!rows.length) return "";
  var added=nWorkInt(turn&&turn.diff_added,0), deleted=nWorkInt(turn&&turn.diff_deleted,0);
  var total=nWorkInt(turn&&turn.diff_total, added+deleted);
  return '<details class="work-file-details" data-work-detail="'+nEscAttr(detailKey||"files")+'"><summary>变更文件 · '+rows.length+' 个 · '+total+' 行 <span>+'+added+' -'+deleted+'</span></summary>'+ '<div class="work-file-list">'+rows.map(function(row){
    var a=nWorkInt(row&&row.added,0), d=nWorkInt(row&&row.deleted,0);
    var path=String(row&&row.path||"");
    return '<div class="work-file-entry"><div class="work-file-row"><b>'+nEsc(path)+'</b><span class="add">+'+a+'</span><span class="del">-'+d+'</span><button type="button" class="work-file-diff-btn" data-work-action="file-diff" data-work-turn-key="'+nEscAttr(turnKey||"")+'" data-work-file-path="'+nEscAttr(path)+'" aria-expanded="false">查看 diff</button></div><div class="work-file-diff" data-work-file-diff-panel hidden></div></div>';
  }).join("")+'</div></details>';
}
function nativeWorkContentText(value){
  if(value==null) return "";
  if(typeof value==="string") return value;
  if(Array.isArray(value)) return value.map(nativeWorkContentText).filter(Boolean).join("\n");
  if(typeof value==="object"){
    if(typeof value.text==="string") return value.text;
    if(value.content!=null) return nativeWorkContentText(value.content);
    if(value.output!=null) return nativeWorkContentText(value.output);
    if(value.stdout!=null || value.stderr!=null) return [nativeWorkContentText(value.stdout),nativeWorkContentText(value.stderr)].filter(Boolean).join("\n");
  }
  return "";
}
function nativeWorkEventBlocks(event){
  var msg=(event&&event.message)||{}, content=msg.content;
  if(Array.isArray(content)) return content.filter(function(block){ return block && typeof block==="object"; });
  if(content && typeof content==="object") return [content];
  if(typeof content==="string") return [{type:"text", text:content}];
  return [];
}
function nativeWorkToolMayHaveDiff(name){
  name=String(name||"").toLowerCase();
  return !name || /^(bash|powershell|toolresult|edit|str_replace_edit|write|write_file|multiedit)$/.test(name);
}
function nativeWorkDiffForFile(events, filePath){
  filePath=typeof nDiffCleanPath==="function" ? nDiffCleanPath(filePath) : String(filePath||"");
  var out={path:filePath, sections:[]}, toolNames={};
  (Array.isArray(events)?events:[]).forEach(function(ev){
    nativeWorkEventBlocks(ev).forEach(function(block){
      if(block && block.type==="tool_use" && block.id) toolNames[String(block.id)]=String(block.name||"");
    });
  });
  (Array.isArray(events)?events:[]).forEach(function(ev){
    nativeWorkEventBlocks(ev).forEach(function(block){
      if(!block || block.type!=="tool_result") return;
      if(!nativeWorkToolMayHaveDiff(toolNames[String(block.tool_use_id||"")])) return;
      var txt=nativeWorkContentText(block.content);
      if(!txt) return;
      var looks=typeof nLooksLikeDiff==="function" ? nLooksLikeDiff(txt) : (txt.indexOf("diff --git ")>=0);
      if(!looks || typeof nDiffFileSections!=="function") return;
      nDiffFileSections(txt).forEach(function(sec){
        var path=typeof nDiffCleanPath==="function" ? nDiffCleanPath(sec&&sec.path) : String(sec&&sec.path||"");
        if(path===filePath) out.sections.push(sec);
      });
    });
  });
  return out;
}
function nWorkFileDiffHtml(filePath, diff){
  filePath=String(filePath||"");
  diff=diff||{};
  var sections=Array.isArray(diff.sections)?diff.sections:[];
  if(!sections.length){
    return '<div class="work-file-diff-empty">这一轮原始事件里没有找到 <b>'+nEsc(filePath)+'</b> 的 diff。可能只是读取文件、二进制变更，或历史只保存了摘要。</div>';
  }
  var added=0, deleted=0, lines=0;
  sections.forEach(function(sec){ added+=nWorkInt(sec&&sec.add,0); deleted+=nWorkInt(sec&&sec.del,0); lines+=(sec&&sec.lines&&sec.lines.length)||0; });
  var isLarge=lines>260 || sections.length>4;
  var body=typeof nDiffBodyHtml==="function" ? nDiffBodyHtml(sections, isLarge) : '<pre class="diff-unified">'+sections.map(function(sec){ return nDiffRowsHtml(sec.lines||[]); }).join("")+'</pre>';
  return '<div class="work-file-diff-head"><div><span>修改详情</span><b>'+nEsc(filePath)+'</b></div><em>+'+added+' -'+deleted+' · '+lines+' 行</em></div><div class="work-file-diff-body">'+body+'</div>';
}
function nWorkFinalHtml(turn, detailKey, open){
  var text=String((turn&&turn.assistant_text)||"").trim();
  if(!text) return "";
  var chars=turn&&turn.assistant_text_chars ? " · "+turn.assistant_text_chars+" 字" : "";
  var trunc=turn&&turn.assistant_text_truncated ? " · 已截断" : "";
  return '<details class="work-final-details" data-work-detail="'+nEscAttr(detailKey||"final")+'"'+(open?' open':'')+'><summary>最终回复'+nEsc(chars+trunc)+'</summary><div class="work-final">'+renderMd(text)+'</div></details>';
}
function nWorkProgressHtml(turn){
  var text=String((turn&&turn.assistant_text)||"").trim();
  if(!text) return "";
  var chars=turn&&turn.assistant_text_chars ? " · "+turn.assistant_text_chars+" 字" : "";
  var trunc=turn&&turn.assistant_text_truncated ? " · 已截断" : "";
  return '<div class="work-progress"><div class="work-subhead">AI 正在回复'+nEsc(chars+trunc)+'</div><div class="work-progress-body">'+renderMd(text)+'</div></div>';
}
function nWorkErrorHtml(turn){
  if(!turn || turn.status!=="error") return "";
  var err=String(turn.error||"本轮失败，但没有返回详细错误。").trim();
  return '<div class="work-error"><span>错误</span><pre>'+nEsc(err)+'</pre></div>';
}
function nWorkUserTextHtml(turn){
  var full=String((turn&&turn.user_text)||"").trim();
  return '<div class="work-user">'+nEsc(full||"Agent 回合")+'</div>';
}
function nWorkTurnHtml(turn, idx, total){
  turn=turn||{};
  var toolTotal=nWorkToolTotal(turn), fileTotal=nWorkFileTotal(turn);
  var running=turn.status==="running";
  var meta=[nWorkTurnStatusText(turn.status), toolTotal?toolTotal+" 次操作":"0 次操作", fileTotal?fileTotal+" 个文件":""].filter(Boolean);
  var clock=nFmtClock(running ? turn.started_ts : turn.finished_ts);
  if(clock) meta.push((running?"开始 ":"完成 ")+clock);
  meta=meta.join(" · ");
  var metaHtml=nEsc(meta)+(running ? nWorkTurnElapsedHtml(turn) : "");
  var isLatest=idx===total-1;
  var detailKey="final-"+nWorkTurnKey(turn, idx);
  var filesKey="files-"+nWorkTurnKey(turn, idx);
  var traceKey=nWorkTurnKey(turn, idx);
  return '<section class="work-turn '+nWorkSafeStatus(turn.status||"done")+(isLatest?' latest':'')+'">'+
    '<div class="work-turn-head"><div><span class="work-pill">#'+nEsc(String(idx+1))+'</span><b>'+(isLatest?'最新结果':'历史记录')+'</b></div><em>'+metaHtml+'</em></div>'+
    nWorkUserTextHtml(turn)+
    (isLatest?'':nWorkTodosHtml(turn.todos||[], {key:"tasks-"+nWorkTurnKey(turn, idx)}))+
    (running?nWorkCurrentActionHtml(turn):nWorkCompleteHtml(turn, toolTotal, fileTotal, isLatest))+
    (running?nWorkProgressHtml(turn):'')+
    nWorkErrorHtml(turn)+
    nWorkChangedFilesHtml(turn, filesKey, traceKey)+
    (!running?nWorkFinalHtml(turn, detailKey, isLatest):'')+
    '<div class="work-actions"><button type="button" class="ghost" data-work-action="trace-turn" data-work-turn-key="'+nEscAttr(traceKey)+'">显示原始事件</button></div>'+
    '<div class="work-turn-trace" data-work-trace-key="'+nEscAttr(traceKey)+'" hidden></div>'+
  '</section>';
}
function nWorkPendingEvents(pending){
  return (pending||[]).filter(function(ev){ return ev && (ev.type==="pending_approval" || ev.type==="pending_ask" || ev.type==="pending_form"); });
}
function nWorkPendingHtml(pending){
  pending=nWorkPendingEvents(pending);
  if(!pending.length) return "";
  return '<div class="work-pending"><b>'+_I('alert')+' 需要处理：'+pending.length+' 个待确认项</b>'+ '<div class="work-pending-cards" data-work-pending></div></div>';
}
function nativeWorkRenderPendingCards(sid, st, pending){
  var host=st && st.root && st.root.querySelector ? st.root.querySelector("[data-work-pending]") : null;
  if(!host) return;
  // Reuse the existing pending-card renderers so approval behavior stays identical in Work mode.
  var pseudo={root:host, turnCard:host, curTxt:null, curThink:null, thinkBubble:null, thinkBox:null, thinkSum:null, thinkTimer:null, thinking:false, lastWasHumanUser:false};
  var m=$("nativemsgs"); if(m) m._nativeStickBottom=false;
  nWorkPendingEvents(pending).forEach(function(ev){
    try{
      if(ev.type==="pending_ask") nHandlePendingAsk(sid, pseudo, ev);
      else if(ev.type==="pending_approval") nHandlePendingApproval(sid, pseudo, ev);
      else if(ev.type==="pending_form") nHandlePendingForm(sid, pseudo, ev);
    }catch(e){
      var warn=document.createElement("div");
      warn.className="work-trace-empty";
      warn.textContent="Pending card render failed: "+(e&&e.message||e);
      host.appendChild(warn);
    }
  });
}
function nativeWorkTurnRows(turns){
  turns=Array.isArray(turns)?turns:[];
  return turns.map(function(t,i){ return {turn:t, idx:i}; }).reverse();
}
function nWorkHistoryHtml(rows, total){
  rows=Array.isArray(rows)?rows:[];
  if(!rows.length) return "";
  return '<details class="work-history" data-work-detail="history"><summary>历史记录 · '+rows.length+' 轮</summary><div class="work-history-body">'+ rows.map(function(row){ return nWorkTurnHtml(row.turn,row.idx,total); }).join("")+'</div></details>';
}
function nWorkNoticeLevel(level){
  level=String(level||"info").toLowerCase();
  return /^(info|warning|warn|error)$/.test(level) ? level : "info";
}
function nWorkNoticesHtml(notices){
  notices=Array.isArray(notices)?notices.filter(function(n){ return n && n.text; }).slice(-5):[];
  if(!notices.length) return "";
  return '<div class="work-notices" role="status">'+notices.map(function(n){
    var level=nWorkNoticeLevel(n.level);
    var icon=(level==="error" || level==="warning" || level==="warn") ? "alert" : "circle-alert";
    return '<div class="work-notice '+level+'">'+_I(icon)+'<div><b>系统提示</b><p>'+nEsc(n.text||"")+'</p></div></div>';
  }).join("")+'</div>';
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
  st.turnPayloads={};
  st.lastSig=sig;
  var turns=work.turns||[], elapsed=nWorkElapsed(work), status=nWorkStatusText(work.status, work.running);
  var turnRows=nativeWorkTurnRows(turns);
  var latestRow=turnRows.length?turnRows[0]:null, historyRows=turnRows.slice(1);
  var totals={tools:nWorkInt(work.tool_total,0), files:nWorkInt(work.file_total,0)};
  if(!totals.tools) turns.forEach(function(t){ totals.tools+=nWorkToolTotal(t); });
  if(!totals.files) turns.forEach(function(t){ totals.files+=nWorkFileTotal(t); });
  var metricText=[nEsc(String(work.turn_count||turns.length))+' 轮', totals.tools+' 次操作', totals.files+' 个文件'].concat(elapsed?['<span class="work-elapsed">'+nEsc(elapsed)+'</span>']:[]).join(' · ');
  var html='<div class="work-board"><div class="work-hero work-status-strip '+nWorkSafeStatus(work.status||"idle")+'">'+
    '<div class="work-hero-copy"><div class="work-head-row"><span class="work-kicker">Work</span>'+nWorkContextHtml(cwd, model)+'</div><h2>'+nEsc(status)+'</h2><p>'+metricText+'</p></div>'+
    '<div class="work-hero-side"><button type="button" class="ghost work-refresh" data-work-action="refresh" title="刷新">'+_I('refresh-cw')+'<span>刷新</span></button></div></div>'+
    nWorkNoticesHtml(work.notices||[])+
    nWorkPendingHtml(pending)+
    nWorkTodosHtml(work.latest_todos||[], {key:"latest-tasks"})+
    (latestRow?nWorkTurnHtml(latestRow.turn,latestRow.idx,turns.length):'<div class="work-empty">还没有工作快照。输入任务后，进度、确认项和最终回复会显示在这里。</div>')+
    nWorkHistoryHtml(historyRows, turns.length)+
    '</div>';
  st.root.innerHTML=html;
  if(st.root.classList) st.root.classList.add("work-mounted");
  nativeWorkRestoreOpenDetails(st, openDetails);
  nativeWorkRenderPendingCards(sid, st, pending);
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
function nativeWorkRenderTurnTrace(sid, key, panel, payload){
  var events=(payload&&payload.events)||[];
  if(!events.length){
    panel.innerHTML='<div class="work-trace-empty">这一轮没有可用的原始事件。</div>';
    return;
  }
  var body=document.createElement("div");
  body.className="work-trace-body";
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
    body.innerHTML='<div class="work-trace-empty">原始事件渲染失败：'+nEsc(e&&e.message||e)+'</div>';
  }finally{
    if(st.thinkTimer){ clearInterval(st.thinkTimer); st.thinkTimer=null; }
    if(st.replayTimer){ clearTimeout(st.replayTimer); st.replayTimer=null; }
    if(st.replayWaitTimer){ clearTimeout(st.replayWaitTimer); st.replayWaitTimer=null; }
    delete nativeStages[previewSid];
  }
  nHljs(body);
}
function nativeWorkToggleTurnTrace(sid, btn){
  var key=btn && btn.dataset ? btn.dataset.workTurnKey : "";
  var card=btn && btn.closest ? btn.closest(".work-turn") : null;
  var panel=card && card.querySelector ? card.querySelector(".work-turn-trace") : null;
  if(!key || !panel) return;
  if(!panel.hidden){
    panel.hidden=true;
    btn.textContent="显示原始事件";
    return;
  }
  panel.hidden=false;
  btn.textContent="隐藏原始事件";
  if(panel.dataset.loaded==="1") return;
  panel.innerHTML='<div class="work-trace-empty">正在加载这一轮的原始事件…</div>';
  var url="/api/nreplay?sid="+encodeURIComponent(sid)+"&view=turn&turn="+encodeURIComponent(key);
  api(url).then(function(r){
    if(panel.hidden) return;
    if(!r || r.ok===false){
      panel.innerHTML='<div class="work-trace-empty">原始事件加载失败：'+nEsc(r&&r.error||"unknown error")+'</div>';
      return;
    }
    panel.dataset.loaded="1";
    nativeWorkRenderTurnTrace(sid, key, panel, r);
  }).catch(function(e){
    if(panel.hidden) return;
    panel.innerHTML='<div class="work-trace-empty">原始事件加载失败：'+nEsc(e&&e.message||e)+'</div>';
  });
}
function nativeWorkToggleFileDiff(sid, btn){
  var key=btn && btn.dataset ? btn.dataset.workTurnKey : "";
  var path=btn && btn.dataset ? btn.dataset.workFilePath : "";
  var entry=btn && btn.closest ? btn.closest(".work-file-entry") : null;
  var panel=entry && entry.querySelector ? entry.querySelector("[data-work-file-diff-panel]") : null;
  if(!key || !path || !panel) return;
  if(!panel.hidden){
    panel.hidden=true;
    btn.textContent="查看 diff";
    btn.setAttribute("aria-expanded","false");
    return;
  }
  panel.hidden=false;
  btn.textContent="隐藏 diff";
  btn.setAttribute("aria-expanded","true");
  if(panel.dataset.loaded==="1") return;
  var st=nativeWorkStages[sid], cached=st&&st.turnPayloads&&st.turnPayloads[key];
  if(cached){
    panel.dataset.loaded="1";
    panel.innerHTML=nWorkFileDiffHtml(path, nativeWorkDiffForFile(cached.events||[], path));
    nHljs(panel);
    return;
  }
  btn.setAttribute("aria-busy","true");
  panel.innerHTML='<div class="work-file-diff-empty">正在加载 '+nEsc(path)+' 的修改详情…</div>';
  var url="/api/nreplay?sid="+encodeURIComponent(sid)+"&view=turn&turn="+encodeURIComponent(key);
  api(url).then(function(r){
    btn.setAttribute("aria-busy","false");
    if(panel.hidden) return;
    if(!r || r.ok===false){
      panel.innerHTML='<div class="work-file-diff-empty">diff 加载失败：'+nEsc(r&&r.error||"unknown error")+'</div>';
      return;
    }
    if(st && st.turnPayloads) st.turnPayloads[key]=r;
    panel.dataset.loaded="1";
    panel.innerHTML=nWorkFileDiffHtml(path, nativeWorkDiffForFile(r.events||[], path));
    nHljs(panel);
  }).catch(function(e){
    btn.setAttribute("aria-busy","false");
    if(panel.hidden) return;
    panel.innerHTML='<div class="work-file-diff-empty">diff 加载失败：'+nEsc(e&&e.message||e)+'</div>';
  });
}
function nativeRenderWorkError(sid){
  var st=nativeWorkStage(sid);
  if(st.root && !st.root.innerHTML){
    st.root.innerHTML='<div class="work-board"><div class="work-empty">Work 视图加载失败，稍后会自动重试。</div></div>';
  }
}
