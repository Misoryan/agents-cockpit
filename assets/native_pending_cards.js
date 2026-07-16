"use strict";

function nHandlePendingApproval(sid, st, obj){
  nFinalizeThinking(st); nStopThinking(st);
  st.lastPendingResync=0; st.pendingExpectedAt=0;
  // ExitPlanMode becomes a dedicated plan review card instead of a generic approval.
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
  // Dangerous commands always require explicit confirmation, so "always allow" is hidden.
  if(!obj.danger){ _btns+='<button class="always" title="本会话内同类操作自动放行(高危命令仍会确认)">允许并不再询问</button>'; }
  _btns+='<button class="deny">拒绝</button></div>';
  card.innerHTML=(obj.danger?_I('alert')+" <b>高危命令,请仔细确认</b> ":"")+nEsc(obj.name||"")+"<pre>"+nEsc(obj.preview||JSON.stringify(obj.input||{}))+"</pre>"+_btns;
  card.querySelector(".allow").addEventListener("click", function(){ nApprove(sid, obj.tool_use_id, true); card.remove(); });
  var _al=card.querySelector(".always");
  if(_al){ _al.addEventListener("click", function(){ nApprove(sid, obj.tool_use_id, true, true); card.remove(); }); }
  card.querySelector(".deny").addEventListener("click", function(){ nApprove(sid, obj.tool_use_id, false); card.remove(); });
  nTurnCard(st).appendChild(card); st.curTxt=null; nScrollBottom();
}

function nHandlePendingAsk(sid, st, obj){
  nFinalizeThinking(st); nStopThinking(st);
  emitAndroidSessionNotice("confirm", sid, "Agent waits for input", obj.question||"Tap to answer.");
  st.lastPendingResync=0; st.pendingExpectedAt=0;
  nRenderAsk(sid, st, obj);
}

function nHandlePendingForm(sid, st, obj){
  nFinalizeThinking(st); nStopThinking(st);
  emitAndroidSessionNotice("confirm", sid, "Form input required", obj.message||"Tap to fill the form.");
  st.lastPendingResync=0; st.pendingExpectedAt=0;
  nRenderForm(sid, st, obj);
}

function nHandlePendingResolved(sid, st, obj, type){
  var root=st.turnCard||st.root;
  if(type==="approval_decision"){
    var c2=root.querySelector('.nmsg.approval[data-tuid="'+obj.tool_use_id+'"],.nmsg.plan[data-tuid="'+obj.tool_use_id+'"]');
    if(c2) c2.remove();
    return;
  }
  if(type==="ask_answered"){
    var a2=root.querySelector('.nmsg.ask[data-tuid="'+obj.tool_use_id+'"]');
    if(a2) a2.remove();
    return;
  }
  if(type==="form_answered"){
    var f2=root.querySelector('.nmsg.form[data-tuid="'+obj.tool_use_id+'"]');
    if(f2) f2.remove();
  }
}
