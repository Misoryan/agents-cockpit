"use strict";
function nEventStableKey(e){
  if(!e) return "";
  if(e.event_id) return "id:"+String(e.event_id);
  if(e.seq!=null) return "seq:"+String(e.seq);
  var m=e.message||{}, blocks=m.content||[], key=(e.type||"")+"|"+(m.uuid||m.id||e.uuid||"");
  if(!key || key==="|") key=e.type||"event";
  if(Array.isArray(blocks) && blocks.length){
    var b=blocks[0]||{}; key += "|"+(b.id||b.tool_use_id||b.type||"");
  }
  return key;
}
function nHashText(s){
  s=String(s==null?"":s);
  var h=0;
  for(var i=0;i<s.length;i++){ h=((h<<5)-h+s.charCodeAt(i))|0; }
  return String(h>>>0);
}
function nEvSigPart(e){
  var key=nEventStableKey(e);
  var body="";
  try{ body=JSON.stringify(e||{}); }catch(_e){ body=String(e); }
  return key+"|"+(e&&e.merged_seq!=null?e.merged_seq:"")+"|"+body.length+"|"+nHashText(body);
}
function nSigFromParts(parts){ return parts.length+"#"+parts.join(","); }
function nMarkRendered(st,obj){
  if(!obj || obj.type==="replay_batch" || obj.type==="state_snapshot") return true;
  var id=nReplayEventKey(obj);
  if(!id) return true;
  st.renderedEvents=st.renderedEvents||{};
  if(st.renderedEvents[id]) return false;
  st.renderedEvents[id]=true;
  if(obj.seq!=null || obj.merged_seq!=null){
    st.lastSeq=Math.max(st.lastSeq||0, Number(obj.seq)||0, Number(obj.merged_seq)||0);
  }
  return true;
}
function nResetReplayState(st){
  st.replayRunId=(st.replayRunId||0)+1;
  if(st.thinkTimer){ clearInterval(st.thinkTimer); st.thinkTimer=null; }
  if(st.replayTimer){ clearTimeout(st.replayTimer); st.replayTimer=null; }
  if(st.replayWaitTimer){ clearTimeout(st.replayWaitTimer); st.replayWaitTimer=null; }
  st.thinking=false; st.thinkBubble=null; st.thinkBox=null; st.thinkSum=null; st.thinkStart=null;
  st.turnCard=null; st.curTxt=null; st.curThink=null; st.lastToolGroup=null;
  st.lastWasHumanUser=false; st.lastHumanText="";
  st.renderedEvents={};
  st.lastSeq=0;
  st.todos=null; if(currentSid===st.sid) nRenderTasks(st);
  st.replayCard=null; st.replayWaiting=false;
  st.replayActive=false; st.replayPending=[];
  st.root.innerHTML="";
}
function nReplayIsPendingEvent(e){
  return !!(e && (e.type==="pending_approval" || e.type==="pending_ask" || e.type==="pending_form"));
}
function nReplayRenderableEvents(events){
  return (events||[]).filter(function(e){ return !nReplayIsPendingEvent(e); });
}
function nStageHasReplayContent(st){
  if(!st || !st.root) return false;
  for(var i=0;i<st.root.children.length;i++){
    var el=st.root.children[i];
    if(!el.classList || !el.classList.contains("replay-progress")) return true;
  }
  return false;
}
function nReplayEventKey(e){
  if(!e) return "";
  if(e.event_id) return "id:"+String(e.event_id);
  if(e.seq!=null) return "seq:"+String(e.seq);
  return "";
}
function nReplayUnseenEvents(st, events){
  var seen=Object.assign({}, st.renderedEvents||{});
  return (events||[]).filter(function(e){
    var key=nReplayEventKey(e);
    if(!key) return true;
    if(seen[key]) return false;
    seen[key]=true;
    return true;
  });
}
function nReplayProgressCancel(st){
  if(!st) return;
  if(st.replayWaitTimer){ clearTimeout(st.replayWaitTimer); st.replayWaitTimer=null; }
  if(st.replayWaiting && st.replayCard && st.replayCard.parentNode){
    st.replayCard.parentNode.removeChild(st.replayCard);
    st.replayCard=null;
  }
  st.replayWaiting=false;
}
function nReplayProgressStart(st,total,label,mode){
  if(st.replayWaitTimer){ clearTimeout(st.replayWaitTimer); st.replayWaitTimer=null; }
  if(st.replayCard && st.replayCard.parentNode) st.replayCard.parentNode.removeChild(st.replayCard);
  st.replayCard=null;
  var card=document.createElement("div"); card.className="nmsg replay-progress";
  if(mode) card.classList.add(mode);
  var meta=mode==="waiting"?"waiting":("0/"+total);
  card.innerHTML='<div class="rp-top"><span>'+nEsc(label||"Loading conversation")+'</span><span class="rp-meta">'+nEsc(meta)+'</span></div><div class="rp-bar"><div class="rp-fill"></div></div>';
  st.root.appendChild(card); st.replayCard=card; st.replayWaiting=(mode==="waiting"); nScrollBottom();
  return card;
}
function nReplayProgressUpdate(st,done,total){
  var card=st.replayCard; if(!card) return;
  card.classList.remove("waiting"); st.replayWaiting=false;
  var pct=total?Math.max(1,Math.min(100,Math.round(done*100/total))):100;
  var meta=card.querySelector(".rp-meta"), fill=card.querySelector(".rp-fill");
  if(meta) meta.textContent=done+"/"+total;
  if(fill) fill.style.width=pct+"%";
}
function nReplayProgressDone(st,total,label,mode){
  var card=st.replayCard; if(!card) return;
  if(st.replayWaitTimer){ clearTimeout(st.replayWaitTimer); st.replayWaitTimer=null; }
  nReplayProgressUpdate(st,total,total);
  card.classList.add("done");
  if(mode) card.classList.add(mode);
  var top=card.querySelector(".rp-top span"); if(top) top.textContent=label||"Conversation loaded";
  var meta=card.querySelector(".rp-meta"); if(meta && !total) meta.textContent="0/0";
  setTimeout(function(){ if(card.parentNode) card.parentNode.removeChild(card); if(st.replayCard===card) st.replayCard=null; }, 700);
}
function nReplayProgressWait(st){
  if(!st || !st.replayCard || !st.replayWaiting) return;
  var top=st.replayCard.querySelector(".rp-top span"); if(top) top.textContent="Waiting for conversation replay";
  var meta=st.replayCard.querySelector(".rp-meta"); if(meta) meta.textContent="still connected";
}
function nReplayBatchAsync(sid, st, events, opts){
  opts=opts||{};
  var renderEvents=nReplayUnseenEvents(st, nReplayRenderableEvents(events)), total=renderEvents.length, idx=0, chunk=18;
  if(st.replayTimer){ clearTimeout(st.replayTimer); st.replayTimer=null; }
  var runId=(st.replayRunId||0)+1; st.replayRunId=runId;
  st.replayActive=true; st.replayPending=st.replayPending||[];
  if(!opts.silent) nReplayProgressStart(st,total,total?"Loading conversation":"No replay history",total?"":"empty");
  function pump(){
    if(st.replayRunId!==runId) return;
    var end=Math.min(total, idx+chunk);
    for(; idx<end; idx++){
      if(st.replayRunId!==runId) return;
      var e=renderEvents[idx];
      try{ e.replay=true; nHandle(sid, e); }
      catch(err){ try{ console.warn("[N] replay event skipped", e&&e.type, err); }catch(_e){} }
    }
    if(!opts.silent) nReplayProgressUpdate(st,idx,total);
    if(idx<total){
      st.replayTimer=setTimeout(pump, 0);
      return;
    }
    if(st.replayRunId!==runId) return;
    st.replayTimer=null; st.replayActive=false;
    if(!opts.silent) nReplayProgressDone(st,total,total?"Conversation loaded":"No replay history",total?"":"empty");
    var pending=st.replayPending||[]; st.replayPending=[];
    pending.forEach(function(ev){ nHandle(sid, ev); });
  }
  pump();
}
function nativeReplayAfter(st){
  return Math.max(0, Number((st&&st.lastSeq)||0)||0);
}
function nativeStopPolling(sid){
  if(nativePollTimers[sid]){ clearTimeout(nativePollTimers[sid]); delete nativePollTimers[sid]; }
  delete nativePollBusy[sid];
}
function nativePollDelay(sid){
  var s=nFindRunSession(sid);
  if(s && (s.state==="running" || s.state==="confirm" || s.state==="plan")) return 1500;
  return 4000;
}
function nativeStartPolling(sid, immediate){
  if(!sid || currentSid!==sid || !nativeStages[sid]) return;
  if(nativePollTimers[sid]) return;
  nativePollTimers[sid]=setTimeout(function(){
    delete nativePollTimers[sid];
    nativePollOnce(sid);
  }, immediate?0:nativePollDelay(sid));
}
function nativePollOnce(sid){
  if(!sid || currentSid!==sid || !nativeStages[sid]) return;
  if(nativePollBusy[sid]){ nativeStartPolling(sid,false); return; }
  var st=nativeStage(sid), after=nativeReplayAfter(st);
  nativePollBusy[sid]=true;
  var url="/api/nreplay?sid="+encodeURIComponent(sid)+"&after="+encodeURIComponent(after);
  if(window.NATIVE_DEBUG){ try{ console.log("[N] replay poll", sid, "after="+after, "url="+url); }catch(_e){} }
  api(url).then(function(r){
    nativePollBusy[sid]=false;
    if(!r || r.ok===false){ nativeStartPolling(sid,false); return; }
    var evs=r.events||[];
    if(evs.length){ nReplayBatchAsync(sid, st, evs, {silent:nStageHasReplayContent(st)}); }
    if(r.snapshot){ nHandle(sid, r.snapshot); }
    (r.pending||[]).forEach(function(ev){ nHandle(sid, ev); });
    if(currentSid===sid){
      var ws=nativeWs[sid];
      if(!ws || ws.readyState!==1) nativeStartPolling(sid,false);
    }
  }).catch(function(){
    nativePollBusy[sid]=false;
    nativeStartPolling(sid,false);
  });
}
function nativeCatchupActiveState(s){
  return !!(s && (s.state==="running" || s.state==="confirm" || s.state==="plan"));
}
function nativeMaybeCatchupPoll(s, prevSession, reason){
  if(!s || s.sid!==currentSid || !nativeStages[s.sid]) return;
  var st=nativeStages[s.sid];
  if(!nStageHasReplayContent(st) || st.replayActive || st.replayWaiting) return;
  var active=nativeCatchupActiveState(s);
  var prevState=(prevSession && typeof prevSession==="object") ? prevSession.state : prevSession;
  var justSettled=!!(prevState && prevState!=="idle" && prevState!=="new" && s.state==="idle");
  var activityChanged=!!(
    prevSession && typeof prevSession==="object" &&
    Number(s.last_output_ts||0) > Number(prevSession.last_output_ts||0)
  );
  if(!active && !justSettled && !activityChanged) return;
  nativeCatchupPoll(s.sid, reason || (active?"active":(justSettled?"settled":"activity")));
}
function nativeCatchupPoll(sid, reason){
  if(!sid || currentSid!==sid || !nativeStages[sid]) return;
  var st=nativeStages[sid], ws=nativeWs[sid];
  if(!ws || ws.readyState!==1){
    nativeStartPolling(sid, false);
    return;
  }
  if(st.catchupInFlight || st.replayActive || st.replayWaiting) return;
  var now=Date.now(), minDelay=(reason==="activity" || reason==="foreground" || reason==="switch")?0:((reason==="settled")?1200:6000);
  if(st.lastCatchupPoll && now-st.lastCatchupPoll<minDelay) return;
  st.lastCatchupPoll=now;
  st.catchupInFlight=true;
  var after=nativeReplayAfter(st);
  var url="/api/nreplay?sid="+encodeURIComponent(sid)+"&after="+encodeURIComponent(after);
  if(window.NATIVE_DEBUG){ try{ console.log("[N] catch-up", sid, "reason="+(reason||""), "after="+after, "url="+url); }catch(_e){} }
  api(url).then(function(r){
    st.catchupInFlight=false;
    if(!r || r.ok===false || currentSid!==sid || !nativeStages[sid]) return;
    var evs=r.events||[];
    if(window.NATIVE_DEBUG){ try{ console.log("[N] catch-up result", sid, "events="+evs.length, "snapshot="+(!!r.snapshot), "pending="+((r.pending||[]).length)); }catch(_e){} }
    if(evs.length){ nReplayBatchAsync(sid, st, evs, {silent:true}); }
    if(r.snapshot){ nHandle(sid, r.snapshot); }
    (r.pending||[]).forEach(function(ev){ nHandle(sid, ev); });
  }).catch(function(){
    st.catchupInFlight=false;
  });
}
