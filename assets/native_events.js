"use strict";
function nPostTerminal(processId, action, input, closeStdin, cols, rows, card){
  var payload={sid:currentSid, process_id:processId, action:action};
  if(input!=null) payload.input=input;
  if(closeStdin) payload.close=true;
  if(cols) payload.cols=cols;
  if(rows) payload.rows=rows;
  postJSON("/api/nterminal", payload).then(function(r){
    if(r && r.error){ alert("终端交互失败: "+r.error); return; }
    if(action==="write" && !closeStdin && card){
      var ta=card.querySelector("textarea"); if(ta) ta.value="";
    }
  }).catch(function(e){ alert("终端交互网络错误: "+(e&&e.message||e)); });
}
function nHandle(sid, obj){
  if(window.NATIVE_DEBUG){ try{ console.log("[N]", obj.type, obj.subtype || (obj.event&&obj.event.delta&&obj.event.delta.type) || ""); }catch(e){} }
  var t=obj.type;
  var st=nativeStages[sid]; if(!st) return;
  if(t==="replay_batch"){
    var _evs=obj.events||[];
    var _parts=_evs.map(nEvSigPart), _sig=nSigFromParts(_parts), _hasContent=nStageHasReplayContent(st);
    if(_sig && _sig===st.lastReplayBatchSig && _hasContent){ nReplayProgressCancel(st); return; }
    if(_hasContent){
      st.replaySigParts=_parts; st.lastReplayBatchSig=_sig; st.sigParts=_parts; st.lastBatchSig=_sig;
      var _unseen=nReplayUnseenEvents(st,_evs);
      if(_unseen.length){ nReplayBatchAsync(sid, st, _unseen, {silent:true}); }
      else { nReplayProgressCancel(st); }
      return;
    }
    st.replaySigParts=_parts; st.lastReplayBatchSig=_sig; st.sigParts=_parts; st.lastBatchSig=_sig;
    nResetReplayState(st);
    nReplayBatchAsync(sid, st, _evs);
    return;
  }
  if(t==="replay_replace"){
    nReplayProgressCancel(st);
    nResetReplayState(st);
    nReplayBatchAsync(sid, st, obj.events||[]);
    return;
  }
  if(st.replayActive && !obj.replay){
    st.replayPending=(st.replayPending||[]); st.replayPending.push(obj);
    return;
  }
  if(!nMarkRendered(st,obj)) return;
  if(!obj.replay && t!=="state_snapshot"){
    st.sigParts=(st.sigParts||[]); st.sigParts.push(nEvSigPart(obj));
    st.lastBatchSig=nSigFromParts(st.sigParts);
  }
  if(t==="state_snapshot"){
    if(st.replayWaiting && !st.replayActive){
      if(nStageHasReplayContent(st)) nReplayProgressCancel(st);
      else nReplayProgressDone(st,0,"Connected","empty");
    }
    st.planMode=!!obj.plan; st.taskMode=!!obj.task;
    st.lastSeq=Math.max(st.lastSeq||0, Number(obj.last_seq)||0);
    if(currentSid===sid){
      nSyncModes(st);
      nSetGen(!!obj.running);
      if(obj.running && !st.curTxt && !st.curThink){ nStartThinking(st, obj); }
      else if(!obj.running && (st.thinking || st.thinkBubble || st.curThink)){
        nEndTurn(st);
      }
    }
    if(obj.route_debug){ try{ console.debug("[Codex route]", obj.route_debug); }catch(_e){} }
    if(obj.state==="confirm" || obj.state==="plan"){
      st.lastPendingResync=0;
      st.pendingExpectedAt=Date.now();
      setTimeout(function(){ nEnsurePendingVisible(nFindRunSession(sid)); }, 2200);
    }else{
      st.pendingExpectedAt=0;
    }
    return;
  }
  if(t==="system"){
    // system 初始事件含 model(及 version 等)。把模型写到顶栏徽标,让用户知道当前跑的是哪个模型。
    // 存进 st.model:切会话时 showNativeSession 据此刷新徽标(重连/恢复时不重发 system)。
    if(obj.model){ st.model=obj.model; if(currentSid===sid){ nRenderModelBadge(obj.model, obj.version); } }
    return;
  }
  if(t==="mode_state"){
    // 后端计划/任务模式变更(自己切换 / 批准计划后自动退出 / 多端同步)→ 更新 stage + 开关 UI + 持久化
    st.planMode=!!obj.plan; st.taskMode=!!obj.task;
    if(currentSid===sid){ nSyncModes(st); }
    localStorage.setItem("acPlan_"+sid, obj.plan?"1":"0");
    localStorage.setItem("acTask_"+sid, obj.task?"1":"0");
    return;
  }
  if(t==="turn_started"){
    nStartThinking(st, obj);
    if(currentSid===sid) nSetGen(true);
    return;
  }
  if(t==="stream_event"){ if(currentSid===sid) nSetGen(true);
    var dl=(obj.event||{}).delta||{};
    if(dl.type==="text_delta" && dl.text){
      st.lastToolGroup=null;
      nFinalizeThinking(st);
      nStopThinking(st);
      if(!st.curTxt) nNewTextBubble(st);
      st.curTxt.appendChild(document.createTextNode(dl.text));
      nScrollBottom();
    } else if(dl.type==="thinking_delta" && dl.thinking){
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
      st.curThink.appendChild(document.createTextNode(dl.thinking));
      nScrollBottom();
    }
    return;
  }
  if(t==="assistant"){
    nFinalizeThinking(st);
    nStopThinking(st);
    st.lastWasHumanUser=false;
    var blocks=(obj.message&&obj.message.content)||[];
    blocks.forEach(function(b){
      if(b.type==="text"){
        nRenderAssistantText(sid, st, b.text);
      } else if(b.type==="tool_use"){
        var _tu=document.createElement("div"); _tu.className="nmsg tool"; _tu.dataset.tuid=b.id||"";
        _tu.dataset.tname=b.name||"";
        var _inp=b.input||{};
        var _n=(b.name||"").toLowerCase();
        if(_n==="mcp__cockpit__ask_user"){ return; }
        if((_n==="agentmessage"||_n==="reasoning") && (_inp.type===_n || _inp.type===b.name)){ return; }
        var _cmd = _inp.command || _inp.cmd;
        var _isEdit = (_n==="edit"||_n==="str_replace_edit"||_n==="write"||_n==="write_file") && b.input;
        var _isShell = (_n==="bash"||_n==="powershell"||_n==="grep");
        var _isTodo = (_n==="todo_write"||_n==="todowrite");
        var _todoList = _isTodo ? (_inp.todos||[]) : [];
        var _todoDone = _todoList.filter(function(x){ return (x.status||"")==="completed"; }).length;
        // 任务模式:TodoWrite 每次更新都刷新顶栏持久进度面板(最新快照)。仅当前可见会话渲染。
        if(_isTodo && _todoList.length){ st.todos=_todoList; if(currentSid===sid) nRenderTasks(st); }
        var _body;
        var _special=nSpecialToolBody(_n, _inp);
        if(_special){
          _body=_special;
        } else if(_n==="bash"||_n==="powershell"){
          _body='<div class="tcmd">$ '+nEsc(_cmd||"")+'</div>';
        } else if(_isTodo){
          _body='<div class="todo">'+_todoList.map(function(x){
            var _st=x.status||"pending", _ic=_st==="completed"?_I('circle-check'):(_st==="in_progress"?_I('circle-dashed'):_I('circle'));
            return '<div class="todo-item '+_st+'"><span class="todo-ic">'+_ic+'</span><span>'+nEsc(x.content||x.activeForm||"")+'</span></div>';
          }).join("")+'</div>';
        } else if(_isEdit){
          _body='<div class="diff"><div class="diff-file">'+nEsc(_inp.file_path||_inp.path||"")+'</div>';
          if(_inp.old_str||_inp.old_string){
            _body+='<pre class="diff-del">'+nEsc("- "+(_inp.old_str||_inp.old_string||""))+'</pre>';
          }
          if(_inp.new_str||_inp.new_string||_inp.content){
            _body+='<pre class="diff-add">'+nEsc("+ "+(_inp.new_str||_inp.new_string||_inp.content||""))+'</pre>';
          }
          _body+='</div>';
        } else if(_n==="multiedit"){
          // MultiEdit:edits[] 多段替换 → 逐段红绿 diff + 处数,替代原先整块 JSON
          var _medits=_inp.edits||[];
          _body='<div class="diff"><div class="diff-file">'+nEsc(_inp.file_path||_inp.path||"")+
                ' <span class="diff-cnt">'+_medits.length+' 处</span></div>';
          _medits.forEach(function(ed,i){
            _body+='<div class="diff-sec"><span class="diff-idx">#'+(i+1)+(ed.replace_all?' 全部':'')+'</span>';
            if(ed.old_string){ _body+='<pre class="diff-del">'+nEsc("- "+ed.old_string)+'</pre>'; }
            _body+='<pre class="diff-add">'+nEsc("+ "+(ed.new_string||""))+'</pre></div>';
          });
          _body+='</div>';
        } else if(_n==="webfetch"){
          // WebFetch:url + 抓取目的 → 链接卡(仅 http(s) 可点,杜绝 javascript: 等协议注入)
          var _wurl=_inp.url||"";
          var _wsafe=(_wurl.indexOf("http://")===0||_wurl.indexOf("https://")===0);
          _body='<div class="web-card">'+(_wsafe
                  ? '<a class="web-url" href="'+nEscAttr(_wurl)+'" target="_blank" rel="noopener">'+nEsc(_wurl)+'</a>'
                  : '<div class="web-url">'+nEsc(_wurl)+'</div>');
          if(_inp.prompt){ _body+='<div class="web-q">“'+nEsc(_inp.prompt)+'”</div>'; }
          _body+='</div>';
        } else if(_n==="websearch"){
          // WebSearch:查询词卡
          _body='<div class="web-card"><div class="web-q">'+_I('search')+' '+nEsc(_inp.query||"")+'</div></div>';
        } else if(_n==="glob"){
          // Glob:pattern(+可选 path)
          _body='<div class="glob-card">'+_I('folder')+' '+nEsc(_inp.pattern||"")+(_inp.path?' <span class="tcdesc">in '+nEsc(_inp.path)+'</span>':'')+'</div>';
        } else if(_n==="exitplanmode"){
          // ExitPlanMode(非门控路径,如未走 gate)→ 计划展示卡(markdown)
          _body='<div class="plan-body">'+renderMd(_inp.plan||"")+'</div>';
        } else if(_n==="read"){
          _body='';  // 路径/范围已在摘要灰色提示展示,不再重复输出 JSON
        } else {
          _body='<pre>'+nEsc(JSON.stringify(_inp,null,2))+'</pre>';
        }
        var _icons={bash:_I('terminal'),powershell:_I('terminal'),read:_I('book-open'),edit:_I('pencil'),str_replace_edit:_I('pencil'),
                    write:_I('file-text'),write_file:_I('file-text'),multiedit:_I('pencil'),webfetch:_I('globe'),websearch:_I('search'),
                    glob:_I('folder'),grep:_I('search'),todowrite:_I('clipboard-list'),todo_write:_I('clipboard-list'),exitplanmode:_I('clipboard-list'),
                    sleep:_I('hourglass'),contextcompaction:_I('archive'),imagegeneration:_I('sparkles'),imageview:_I('file-text')};
        var _ic=_icons[_n]||_I('wrench');
        var _sum=_isTodo?(_I('clipboard-list')+' 待办 ('+_todoDone+'/'+_todoList.length+')'):(_ic+' '+nEsc(b.name||""));
        var _hint=_inp.description||"";
        if(!_hint){
          if(_n==="grep" && _inp.pattern){ _hint='/'+_inp.pattern+'/'; }
          else if(_n==="read" && _inp.file_path){
            _hint=_inp.file_path;
            var _ro=_inp.offset, _rl=_inp.limit;
            if(_ro!=null && _rl!=null){ _hint+=' (第 '+_ro+'-'+(Number(_ro)+Number(_rl)-1)+' 行)'; }
            else if(_ro!=null){ _hint+=' (从第 '+_ro+' 行)'; }
            else if(_rl!=null){ _hint+=' (前 '+_rl+' 行)'; }
          }
          else if(_n==="multiedit" && (_inp.file_path||_inp.path)){ _hint=_inp.file_path||_inp.path; }
          else if(_n==="websearch" && _inp.query){ _hint=_inp.query; }
          else if(_n==="glob" && _inp.pattern){ _hint=_inp.pattern; }
          else if(_n==="sleep"){ _hint=_inp.reason||_inp.message||""; }
          else if(_n==="imagegeneration"){ _hint=_inp.prompt||_inp.description||""; }
          else if(_n==="imageview"){ _hint=_inp.path||_inp.file||_inp.url||""; }
          else if(_n==="contextcompaction"){ _hint=_inp.status||_inp.summary||_inp.message||""; }
        }
        if(_hint){ _sum+=' <span class="tcdesc">'+nEsc(_hint)+'</span>'; }
        if(_isTodo){
          // 折叠本 turn 内上一版待办快照,只展开最新一版(避免历史快照刷屏)
          var _pv=(st.turnCard||st.root).querySelectorAll('details.todo-det');
          for(var _i=0;_i<_pv.length;_i++){ _pv[_i].open=false; }
        }
        if(nShellGroupKey(b.name)){ nAppendShellGroupEntry(st, b, _sum, _body); return; }
        st.lastToolGroup=null;
        var _detAttr=(_isShell?"":" open")+(_isTodo?' class="todo-det"':'');
        _tu.innerHTML='<details'+_detAttr+'><summary>'+_sum+'</summary>'+_body+'<div class="tres">'+_I('hourglass')+' 运行中…</div></details>';
        nTurnCard(st).appendChild(_tu); st.curTxt=null; nScrollBottom();
      } else if(b.type==="thinking"){
        st.lastToolGroup=null;
        if(obj.replay){
          var _th=document.createElement("details");
          _th.innerHTML='<summary>'+_I('message-circle')+' 思考</summary><pre>'+nEsc(b.thinking||"")+'</pre>';
          nTurnCard(st).appendChild(_th); nScrollBottom();
        }
      }
    });
    st.curThink=null; st.curTxt=null;
    nScrollBottom(); return;
  }
  if(t==="user"){
    var bs=((obj.message||{}).content);
    if(typeof bs==="string"){ nAddHumanRow(st,bs); return; }
    if(!Array.isArray(bs)) bs = bs?[bs]:[];
    var humanParts=[], humanImages=[];
    bs.forEach(function(b){
      if(b && b.type==="text"){
        humanParts.push(b.text||"");
      } else if(b && (b.type==="image" || b.type==="localImage")){
        humanImages.push(b);
      } else if(b && b.type==="tool_result"){
        var c=b.content; var txt=typeof c==="string"?c:JSON.stringify(c,null,2);
        nRenderToolResult(st, b.tool_use_id, txt);
      }
    });
    if(humanParts.length || humanImages.length){ nAddHumanContent(st,humanParts.join("\n"), humanImages, sid); }
    return;
  }
  if(t==="pending_approval"){
    nFinalizeThinking(st); nStopThinking(st);
    st.lastPendingResync=0; st.pendingExpectedAt=0;
    // ExitPlanMode(计划模式提交计划)→ 计划审批卡:markdown 计划 + 批准/拒绝。
    // 批准后后端自动退出计划模式并广播 mode_state(同步前端开关),与 claude cli 行为一致。
    if(obj.name==="ExitPlanMode"){
      emitAndroidSessionNotice("plan", sid, "Codex plan needs review", "Tap to review and decide whether to continue.");
      var oldPlan=(st.turnCard||st.root).querySelector('.nmsg.plan[data-tuid="'+obj.tool_use_id+'"],.nmsg.approval[data-tuid="'+obj.tool_use_id+'"]');
      if(oldPlan) oldPlan.remove();
      var pcard=document.createElement("div"); pcard.className="nmsg plan"; pcard.dataset.tuid=obj.tool_use_id;
      var _planMd=(obj.input&&obj.input.plan)||"";
      pcard.innerHTML='<div class="plan-head">'+_I('clipboard-list')+' 计划方案 · 请审阅后决定</div><div class="plan-body">'+renderMd(_planMd)+'</div>'+
        '<div class="abtns"><button class="allow">'+_I('circle-check')+' 批准并执行</button><button class="deny">'+_I('pencil')+' 让它继续完善</button></div>';
      nHljs(pcard.querySelector(".plan-body"));
      pcard.querySelector(".allow").addEventListener("click", function(){ nApprove(sid, obj.tool_use_id, true); pcard.remove(); });
      pcard.querySelector(".deny").addEventListener("click", function(){ nApprove(sid, obj.tool_use_id, false); pcard.remove(); });
      nTurnCard(st).appendChild(pcard); st.curTxt=null; nScrollBottom(); return;
    }
    emitAndroidSessionNotice("confirm", sid, (obj.danger?"Dangerous action needs confirmation":"Action needs confirmation"), obj.preview||obj.name||"Tap to confirm.");
    var old=(st.turnCard||st.root).querySelector('.nmsg.approval[data-tuid="'+obj.tool_use_id+'"],.nmsg.plan[data-tuid="'+obj.tool_use_id+'"]');
    if(old) old.remove();
    var dng=obj.danger?" danger":"";
    var card=document.createElement("div"); card.className="nmsg approval"+dng; card.dataset.tuid=obj.tool_use_id;
    var _btns='<div class="abtns"><button class="allow">允许</button>';
    // 高危命令不能被「不再询问」(后端对高危仍强制审批,按钮也无意义),故高危卡不显示此项
    if(!obj.danger){ _btns+='<button class="always" title="本会话内同类操作自动放行(高危命令仍会确认)">允许并不再询问</button>'; }
    _btns+='<button class="deny">拒绝</button></div>';
    card.innerHTML=(obj.danger?_I('alert')+" <b>高危命令,请仔细确认</b> ":"")+nEsc(obj.name||"")+"<pre>"+nEsc(obj.preview||JSON.stringify(obj.input||{}))+"</pre>"+_btns;
    card.querySelector(".allow").addEventListener("click", function(){ nApprove(sid, obj.tool_use_id, true); card.remove(); });
    var _al=card.querySelector(".always");
    if(_al){ _al.addEventListener("click", function(){ nApprove(sid, obj.tool_use_id, true, true); card.remove(); }); }
    card.querySelector(".deny").addEventListener("click", function(){ nApprove(sid, obj.tool_use_id, false); card.remove(); });
    nTurnCard(st).appendChild(card); st.curTxt=null; nScrollBottom(); return;
  }
  if(t==="pending_ask"){
    nFinalizeThinking(st); nStopThinking(st);
    emitAndroidSessionNotice("confirm", sid, "Agent waits for input", obj.question||"Tap to answer.");
    st.lastPendingResync=0; st.pendingExpectedAt=0;
    nRenderAsk(sid, st, obj);
    return;
  }
  if(t==="pending_form"){
    nFinalizeThinking(st); nStopThinking(st);
    emitAndroidSessionNotice("confirm", sid, "Form input required", obj.message||"Tap to fill the form.");
    st.lastPendingResync=0; st.pendingExpectedAt=0;
    nRenderForm(sid, st, obj);
    return;
  }
  if(t==="approval_decision"){
    var c2=(st.turnCard||st.root).querySelector('.nmsg.approval[data-tuid="'+obj.tool_use_id+'"]');
    if(c2) c2.remove();
    return;
  }
  if(t==="ask_answered"){
    var a2=(st.turnCard||st.root).querySelector('.nmsg.ask[data-tuid="'+obj.tool_use_id+'"]');
    if(a2) a2.remove();
    return;
  }
  if(t==="form_answered"){
    var f2=(st.turnCard||st.root).querySelector('.nmsg.form[data-tuid="'+obj.tool_use_id+'"]');
    if(f2) f2.remove();
    return;
  }
  if(t==="auto_allow_added"){
    // 用户点了「允许并不再询问」→ 该工具已加入本会话允许集,后续同类门控自动放行。给条反馈确认生效。
    nAddRow(st, "sys", _I('lock')+' 本会话不再询问 '+nEsc(obj.tool||"")+" 类操作(同类自动放行,高危命令仍会确认)");
    return;
  }
  if(t==="compacted"){
    nAddRow(st, "sys", _I('archive')+' 对话历史已压缩(早期摘要、近期保留,可继续长任务)');
    return;
  }
  if(t==="thread_forked"){
    var frow=document.createElement("div");
    frow.className="nmsg sys";
    var ftitle=obj.title||"Forked Codex thread", fid=obj.thread_id||"";
    frow.innerHTML='Codex: '+_I('git-branch')+' 已 fork 新线程 <span class="tcdesc">'+nEsc(fid)+'</span> ';
    var fbtn=document.createElement("button");
    fbtn.type="button";
    fbtn.className="cbtn ghost";
    fbtn.textContent="打开 fork";
    fbtn.addEventListener("click", function(){ openForkedCodexThread(fid, ftitle, obj.cwd||""); });
    frow.appendChild(fbtn);
    (st.turnCard||st.root).appendChild(frow);
    nScrollBottom();
    return;
  }
  if(t==="terminal_interaction"){
    var pid=obj.process_id||"", existing=(st.turnCard||st.root).querySelector('.nmsg.terminal[data-pid="'+nEscAttr(pid)+'"]');
    if(existing) existing.remove();
    var term=document.createElement("div");
    term.className="nmsg terminal";
    term.setAttribute("data-pid", pid);
    term.innerHTML='<div class="aq">'+_I('terminal')+' 命令需要终端输入 <span class="tcdesc">'+nEsc(pid)+'</span></div>'+
      (obj.stdin?'<pre>'+nEsc(obj.stdin)+'</pre>':'')+
      '<textarea class="ainp" rows="2" placeholder="输入要发送到 stdin 的内容…"></textarea>'+
      '<div class="abtns"><button class="tsend">发送</button><button class="tclose">发送并关闭 stdin</button><button class="tkill">终止</button></div>';
    var ta=term.querySelector("textarea");
    term.querySelector(".tsend").addEventListener("click", function(){
      var text=ta.value||""; if(text && text.charAt(text.length-1)!=="\n") text+="\n";
      nPostTerminal(pid, "write", text, false, 0, 0, term);
    });
    term.querySelector(".tclose").addEventListener("click", function(){
      var text=ta.value||""; if(text && text.charAt(text.length-1)!=="\n") text+="\n";
      nPostTerminal(pid, "write", text, true, 0, 0, term);
    });
    term.querySelector(".tkill").addEventListener("click", function(){ nPostTerminal(pid, "terminate", "", false, 0, 0, term); });
    (st.turnCard||st.root).appendChild(term);
    nScrollBottom();
    return;
  }
  if(t==="terminal_input_sent"){
    var sent=(st.turnCard||st.root).querySelector('.nmsg.terminal[data-pid="'+nEscAttr(obj.process_id||"")+'"] textarea');
    if(sent) sent.value="";
    return;
  }
  if(t==="terminal_closed"){
    var closed=(st.turnCard||st.root).querySelector('.nmsg.terminal[data-pid="'+nEscAttr(obj.process_id||"")+'"]');
    if(closed) closed.remove();
    nAddRow(st, "sys", _I('terminal')+' 终端交互已'+(obj.terminated?'终止':'关闭'));
    return;
  }
  if(t==="codex_notice"){
    if(obj.silent){ return; }
    if(obj.level==="debug"){
      try{ console.debug("[Codex notice]", obj.method||"", obj.message||"", obj.detail||""); }catch(e){}
      return;
    }
    var cmsg="Codex: "+nEsc(obj.message||"notice");
    if(obj.method){ cmsg+=' <span class="tcdesc">'+nEsc(obj.method)+'</span>'; }
    if(obj.detail){ cmsg+='<details><summary>详情</summary><pre>'+nEsc(obj.detail)+'</pre></details>'; }
    nAddRow(st, "sys", cmsg);
    return;
  }
  if(t==="codex_usage"){
    return;
  }
  if(t==="rate_limited"){
    // 账号被 z.ai 限流(529/1305):冷却期内重发只会延长冷却,后端已停止重试。提示用户稍候,
    // 并把"同账号 CLI 是否也失败"的对照实验交给用户(判定账号级冷却 vs web 独有特征)。
    nFinalizeThinking(st); nStopThinking(st);
    nAddRow(st, "sys", _I('circle-alert')+' 账号被限流(529/1305),冷却期内重发只会延长冷却 → 请稍候片刻(约半分钟~几分钟)再试。同时段用同账号 CLI 发一条:也失败=账号级冷却(需压低 web 并发);正常=web 独有特征待查。详情见 manager 日志。');
    nEndTurn(st);
    nSetGen(false);
    return;
  }
  if(t==="result"){
    st.lastWasHumanUser=false;
    if(obj.error) nAddRow(st, "sys", _I('alert')+" "+nEsc(obj.error));
    nMetaRow(st, obj);
    nEndTurn(st);
    nSetGen(false);
    return;
  }
  if(t==="interrupted"){
    // 用户点了「打断」→ 后端 kill 当前 claude 子进程但保留会话/历史。收尾这一轮:
    // 停思考计时、补一条系统提示、复位发送按钮。(result 不会来,所以这里手动收尾)
    nFinalizeThinking(st); nStopThinking(st);
    nAddRow(st, "sys", _I('square')+' 已打断本轮 · agent 停止生成,会话与历史保留,可继续发送(下次自动 --resume)');
    nEndTurn(st);
    nSetGen(false);
    return;
  }
}
