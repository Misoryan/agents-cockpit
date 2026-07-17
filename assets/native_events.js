"use strict";
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
    nReconcilePendingSnapshot(st, obj);
    nSettleIdleSnapshot(st, obj);
    if(!obj.running) nMaybeCompleteTasks(st);
    if(currentSid===sid){
      nSyncModes(st);
      nSetGen(!!obj.running);
      if(obj.running && !st.curTxt && !st.curThink){ nStartThinking(st, obj); }
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
  if(t==="stream_event"){
    nHandleStreamEvent(sid, st, obj);
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
        nRenderToolUseBlock(sid, st, b);
      } else if(b.type==="thinking"){
        nRenderAssistantThinkingBlock(sid, st, obj, b);
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
        nRenderToolResult(st, b.tool_use_id, txt, b);
      }
    });
    if(humanParts.length || humanImages.length){ nAddHumanContent(st,humanParts.join("\n"), humanImages, sid); }
    return;
  }
  if(t==="pending_approval"){
    nHandlePendingApproval(sid, st, obj);
    return;
  }
  if(t==="pending_ask"){
    nHandlePendingAsk(sid, st, obj);
    return;
  }
  if(t==="pending_form"){
    nHandlePendingForm(sid, st, obj);
    return;
  }
  if(t==="approval_decision" || t==="ask_answered" || t==="form_answered"){
    nHandlePendingResolved(sid, st, obj, t);
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
    var ftitle=obj.title||"\u5206\u53c9\u7684 Codex \u4f1a\u8bdd", fid=obj.thread_id||"";
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
    nHandleTerminalInteraction(st, obj);
    return;
  }
  if(t==="terminal_input_sent"){
    nHandleTerminalInputSent(st, obj);
    return;
  }
  if(t==="terminal_closed"){
    nHandleTerminalClosed(st, obj);
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
    nMaybeCompleteTasks(st);
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
