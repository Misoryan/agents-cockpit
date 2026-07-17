"use strict";
function nativeStage(sid){
  if(nativeStages[sid]) return nativeStages[sid];
  var d=document.createElement("div");
  d.style.cssText="display:none;width:100%;flex-direction:column;gap:10px";
  d.dataset.sid=sid; $("nativemsgs").appendChild(d);
  nativeStages[sid]={sid:sid, root:d, curTxt:null, curThink:null, turnCard:null, shownCount:0, model:"", lastToolGroup:null,
                      planMode:null, taskMode:null, todos:null, tasksCollapsed:false, lastPendingResync:0,
                      renderedEvents:{}, lastBatchSig:"", lastSeq:0, replayActive:false, replayPending:[], replayCard:null, replayTimer:null,
                      replayWaiting:false, replayWaitTimer:null, replayRunId:0, lastReplayBatchSig:"", replaySigParts:[],
                      replayFetchId:0, lastCatchupPoll:0, catchupInFlight:false};
  return nativeStages[sid];
}
function dropNativeStage(sid){
  var st=nativeStages[sid]; if(!st) return;
  if(typeof nResetReplayState==="function") nResetReplayState(st);
  if(st.thinkTimer){ clearInterval(st.thinkTimer); st.thinkTimer=null; }
  if(st.replayTimer){ clearTimeout(st.replayTimer); st.replayTimer=null; }
  if(st.replayWaitTimer){ clearTimeout(st.replayWaitTimer); st.replayWaitTimer=null; }
  st.replayRunId=(st.replayRunId||0)+1;
  if(st.root.parentNode) st.root.parentNode.removeChild(st.root);
  delete nativeStages[sid];
  if(typeof nativeDropWorkStage==="function") nativeDropWorkStage(sid);
  if(nativeReconnectTimers[sid]){ clearTimeout(nativeReconnectTimers[sid]); delete nativeReconnectTimers[sid]; }
  delete nativeReconnectState[sid];
  if(nativePollTimers[sid]){ clearTimeout(nativePollTimers[sid]); delete nativePollTimers[sid]; }
  delete nativePollBusy[sid];
  if(nativeWs[sid]){ try{ nativeWs[sid].close(); }catch(e){} delete nativeWs[sid]; }
  if(currentSid===sid) hideNative();
}
function hideNative(){
  var sid=currentSid;
  currentSid=null;
  if(sid && typeof nativeStopWorkPolling==="function") nativeStopWorkPolling(sid);
  nSetGen(false); setMainView("landing"); renderSessionTabs(); nUpdateScrollButton();
}
function nAddRow(st, cls, html, ts){
  if(cls!=="result") st.lastToolGroup=null;
  st.curTxt=null;
  var d=document.createElement("div"); d.className="nmsg "+cls;
  d.innerHTML=html; if(cls==="user"){var _mt=document.createElement("div");_mt.className="mtime";_mt.textContent=nFmtClock(ts)||_msgTime();d.appendChild(_mt);} (st.turnCard||st.root).appendChild(d); nScrollBottom();
}
