"use strict";
/* ---- native agent session (WS, 结构化渲染, 类 claude.ai) ---- */
function nEsc(s){ s=String(s==null?"":s); return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
/* 属性值转义:在 nEsc(&<>) 基础上再封掉引号,供 href= 等属性上下文用,防属性注入。纯字符码,无反斜杠。 */
function nEscAttr(s){ s=String(s==null?"":s); s=nEsc(s); return s.split(String.fromCharCode(34)).join("&quot;").split(String.fromCharCode(39)).join("&#39;"); }
function renderMd(s){
  s=String(s==null?"":s);
  // assistant 文本会复述 WebFetch 抓到的网页/用户代码,内含任意 HTML → 必须经 DOMPurify 过滤再注入。
  // 若 marked 或 DOMPurify 任一未就绪,绝不注入原始 HTML,回退到转义(宁可丢格式不可丢安全)。
  if(window.marked && window.DOMPurify){
    try{ return DOMPurify.sanitize(marked.parse(s)); }catch(e){}
  }
  return nEsc(s).replace(/\n/g,"<br>");
}
/* 从 code.className 里取语言标识(marked 给带围栏语言的代码块加 language-xxx)。
   纯字符遍历,不用正则反斜杠(本文件编辑时反斜杠会被翻倍,故规避)。 */
function nCodeLang(className){
  var s=String(className||""), j=s.indexOf("language-");
  if(j<0) return "";
  s=s.slice(j+9);
  for(var k=0;k<s.length;k++){
    var c=s.charCodeAt(k);
    var letter=(c>=65&&c<=90)||(c>=97&&c<=122)||(c>=48&&c<=57)||c===95||c===43||c===35||c===45;
    if(!letter) return s.slice(0,k);
  }
  return s;
}
/* 给容器内每个 pre>code 上语法高亮 + 工具条(语言标签 / 复制按钮)。
   流式期间 assistant 文本是裸文本节点,真正 markdown 化发生在 assistant 终态事件
   (st.curTxt.innerHTML=renderMd),只在那里调一次,避免逐帧重算高亮。hljs 未就绪则
   只补复制/语言条,不高亮(降级,不报错)。 */
function nHljs(root){
  if(!root) return;
  var pres=root.querySelectorAll("pre");
  for(var i=0;i<pres.length;i++){
    var pre=pres[i];
    if(pre.dataset.hlenabled) continue;
    pre.dataset.hlenabled="1";
    var code=pre.querySelector("code");
    var lang="";
    if(code){
      lang=nCodeLang(code.className);
      if(window.hljs){ try{ hljs.highlightElement(code); }catch(e){} }
    }
    var bar=document.createElement("div"); bar.className="codebar";
    var lab=document.createElement("span"); lab.className="codelang"; lab.textContent=lang||"text";
    var cp=document.createElement("button"); cp.type="button"; cp.className="codecopy"; cp.textContent="复制";
    (function(thePre,theBtn){
      theBtn.addEventListener("click",function(e){
        e.preventDefault();
        var txt=(thePre.innerText||thePre.textContent||"");
        if(navigator.clipboard&&navigator.clipboard.writeText){
          var oldt=theBtn.textContent; theBtn.disabled=true; theBtn.textContent="…";
          navigator.clipboard.writeText(txt).then(function(){ theBtn.textContent="已复制 ✓"; setTimeout(function(){theBtn.disabled=false;theBtn.textContent=oldt;},1100); },function(){ theBtn.textContent="复制失败"; setTimeout(function(){theBtn.disabled=false;theBtn.textContent=oldt;},1100); });
        } else { theBtn.textContent="不支持"; setTimeout(function(){theBtn.textContent="复制";},1100); }
      });
    })(pre,cp);
    bar.appendChild(lab); bar.appendChild(cp);
    pre.parentNode.insertBefore(bar,pre);
  }
}
/* token / cost 数字格式化(供 result 元信息条用)。无反斜杠。 */
function nFmtTok(n){ n=Number(n)||0; if(n>=1000) return (n/1000).toFixed(n>=10000?0:1)+"k"; return ""+n; }
function nFmtCost(v){ v=Number(v); if(!(v>0)) return "0"; var s=v.toFixed(4); while(s.length>1&&s.slice(-1)==="0") s=s.slice(0,-1); if(s.slice(-1)===".") s=s.slice(0,-1); return s; }
/* 把模型 id 精简成徽标用短名:去掉尾部日期快照(如 -20250929)。纯字符码判断数字,无反斜杠。 */
function nShortModel(m){
  m=String(m||""); var dash=m.lastIndexOf("-");
  if(dash>4){
    var tail=m.slice(dash+1), allnum=tail.length===8;
    for(var k=0; allnum && k<8;k++){ var c=tail.charCodeAt(k); if(c<48||c>57) allnum=false; }
    if(allnum) m=m.slice(0,dash);
  }
  return m;
}
/* 顶栏模型徽标:写文本 + title 挂完整模型/版本;空则隐藏。 */
function nRenderModelBadge(m, ver){
  var el=$("nativemodel"); if(!el) return;
  m=String(m||"");
  if(!m){ el.style.display="none"; el.textContent=""; el.title="Model"; return; }
  el.textContent=nShortModel(m);
  el.title="Model: "+m+(ver?(" (CLI "+ver+")"):"");
  el.style.display="";
  if(typeof renderSessionTabs==="function"){ try{ renderSessionTabs(); }catch(e){} }
}
function nSyncModes(st){
  var bp=$("nmode-plan"), bt=$("nmode-task");
  if(bp){ bp.classList.toggle("active", !!st.planMode); bp.setAttribute("aria-pressed", st.planMode?"true":"false"); }
  if(bt){ bt.classList.toggle("active", !!st.taskMode); bt.setAttribute("aria-pressed", st.taskMode?"true":"false"); }
}
/* 持久任务进度面板:从 st.todos(最新 TodoWrite 快照)重建,显示进度条 + 实时清单。空则隐藏。 */
function nRenderTasks(st){
  var el=$("nativetasks"); if(!el) return;
  if(st.taskHideTimer){ clearTimeout(st.taskHideTimer); st.taskHideTimer=null; }
  var todos=st.todos||[];
  if(!todos.length){ el.style.display="none"; el.innerHTML=""; return; }
  var done=0; todos.forEach(function(x){ if((x.status||"")==="completed") done++; });
  var pct=todos.length?Math.round(done*100/todos.length):0;
  el.style.display="";
  el.innerHTML='<div class="nt-head"><div class="nt-toggle"><span>'+_I('list-checks')+' 任务进度</span><div class="nt-bar"><div class="nt-fill" style="width:'+pct+'%"></div></div></div><span class="nt-cnt">'+done+'/'+todos.length+'</span></div>'+
    (st.tasksCollapsed?'':'<div class="nt-list">'+todos.map(function(x){
      var _st=x.status||"pending", _ic=_st==="completed"?_I('circle-check'):(_st==="in_progress"?_I('circle-dashed'):_I('circle'));
      return '<div class="nt-item '+_st+'"><span class="todo-ic">'+_ic+'</span><span>'+nEsc(x.content||x.activeForm||"")+'</span></div>';
    }).join("")+'</div>');
  el.querySelector(".nt-toggle").addEventListener("click", function(){
    st.tasksCollapsed=!st.tasksCollapsed; nRenderTasks(st);
  });
}
function nTasksAllCompleted(st){
  var todos=(st&&st.todos)||[];
  return !!todos.length && todos.every(function(x){ return (x.status||"")==="completed"; });
}
function nSettleActiveTasks(st){
  var todos=(st&&st.todos)||[];
  if(!todos.length) return false;
  var hasPending=false, changed=false;
  st.todos=todos.map(function(x){
    var status=x.status||"pending";
    if(status==="pending") hasPending=true;
    if(status==="in_progress"){
      changed=true;
      var y=Object.assign({}, x);
      y.status="completed";
      return y;
    }
    return x;
  });
  if(hasPending || !changed){ return false; }
  nRenderTasks(st);
  return true;
}
function nMaybeCompleteTasks(st){
  if(!nTasksAllCompleted(st)) return false;
  nRenderTasks(st);
  var el=$("nativetasks");
  if(el) el.classList.add("done");
  st.taskHideTimer=setTimeout(function(){
    st.todos=null;
    if(el){ el.classList.remove("done"); el.style.display="none"; el.innerHTML=""; }
  }, 1400);
  return true;
}
function nAtBottom(){ var m=$("nativemsgs"); if(!m) return true; return (m.scrollHeight - m.scrollTop - m.clientHeight) < 120; }
function nUpdateScrollButton(){
  var b=$("scrollbottom"), m=$("nativemsgs"); if(!b||!m) return;
  var at=nAtBottom(); m._nativeStickBottom=at;
  b.classList.toggle("show", currentSid && !at);
}
function nJumpBottom(){ var m=$("nativemsgs"); if(!m) return; m._nativeStickBottom=true; m.scrollTop=m.scrollHeight; nUpdateScrollButton(); }
function nScrollBottom(){ var m=$("nativemsgs"); if(!m) return;
  var stick=(m._nativeStickBottom!==false) || nAtBottom();
  requestAnimationFrame(function(){ if(stick){ m.scrollTop = m.scrollHeight; m._nativeStickBottom=true; } nUpdateScrollButton(); }); }
function nCoerceEpochMs(v){
  var n=Number(v);
  if(!isFinite(n) || n<=0) return 0;
  if(n<100000000000) n*=1000;
  return Math.round(n);
}
function nThinkingBaseMs(src){
  if(src && typeof src==="object"){
    var elapsed=src.turn_elapsed_ms;
    if(elapsed==null) elapsed=src.elapsed_ms;
    elapsed=Number(elapsed);
    if(isFinite(elapsed) && elapsed>=0) return Date.now()-elapsed;
    return nCoerceEpochMs(src.turn_started_at_ms || src.started_at_ms || src.turn_started_at || src.started_at);
  }
  return nCoerceEpochMs(src);
}
function nThinkingSeconds(st){
  return Math.max(0, Math.floor((Date.now()-(st.thinkStart||Date.now()))/1000));
}
function nThinkingLabel(st){ return "\u601d\u8003\u4e2d... "+nThinkingSeconds(st)+"s"; }
function nSetThinkingStart(st, src){
  var base=nThinkingBaseMs(src);
  if(base) st.thinkStart=base;
  else if(!st.thinkStart) st.thinkStart=Date.now();
  nUpdateThinkingLabel(st);
}
function nUpdateThinkingLabel(st){
  var label=nThinkingLabel(st);
  var t=st.thinkBubble&&st.thinkBubble.querySelector(".ti-txt");
  if(t) t.textContent=label;
  if(st.thinkSum) st.thinkSum.innerHTML=_I('message-circle')+" "+label;
}
function nTurnHasContent(card){
  if(!card || !card.children) return false;
  for(var i=0;i<card.children.length;i++){
    var ch=card.children[i];
    if(ch.classList && ch.classList.contains("thinking-ind")) continue;
    if((ch.textContent||"").trim()) return true;
    if(ch.querySelector && ch.querySelector("pre,button,input,textarea,select,svg")) return true;
  }
  return false;
}
function nPruneEmptyTurn(st, card){
  card=card||st.turnCard;
  if(!card || !card.classList || !card.classList.contains("turn")) return;
  if(nTurnHasContent(card)) return;
  if(card.parentNode) card.parentNode.removeChild(card);
  if(st.turnCard===card) st.turnCard=null;
}
function nTurnCard(st){
  if(st.turnCard) return st.turnCard;
  var d=document.createElement("div"); d.className="nmsg turn";
  st.root.appendChild(d); st.turnCard=d; nScrollBottom();
  return d;
}
function nEndTurn(st){
  nFinalizeThinking(st);
  nStopThinking(st);
  if(st.turnCard) st.turnCard.classList.add("done");
  st.turnCard=null; st.curTxt=null; st.curThink=null; st.lastToolGroup=null;
}
function nSettleIdleSnapshot(st, obj){
  if(!st || !obj || obj.running) return false;
  if(obj.state==="confirm" || obj.state==="plan") return false;
  if(!(st.thinking || st.thinkBubble || st.curThink || st.curTxt || st.turnCard)) return false;
  nEndTurn(st);
  return true;
}
/* result 事件的轻量元信息条:补齐 CLI 底栏的「用量/收尾」层。
   显示:收尾图标(随 stop_reason / is_error 变化)、轮数、token 用量(入/出/缓存)、耗时。
   stop_reason 异常(max_tokens / refusal)或 is_error → 红框警示,补 CLI 里限流/拒绝/截断的感知。
   必须在 nEndTurn 之前调用(此时 turnCard 还在,信息条挂在 turn 卡尾部)。 */
function nFmtDur(ms){var s=Math.max(0,Math.round(Number(ms)/1000));if(s<60)return s+"秒";var m=Math.floor(s/60),r=s%60;return r?(m+"分"+r+"秒"):(m+"分钟");}
function _msgTime(){var d=new Date();function z(n){return(n<10?"0":"")+n;}return z(d.getHours())+":"+z(d.getMinutes());}
/* 事件真实时间戳(epoch ms)→ 时钟串:当天 HH:MM,跨天补 M-D。无 ts 返回空串,调用方回退 _msgTime()。 */
function nFmtClock(ts){
  var n=Number(ts); if(!(n>0)) return "";
  var d=new Date(n); if(isNaN(d.getTime())) return "";
  function z(x){return(x<10?"0":"")+x;}
  var t=z(d.getHours())+":"+z(d.getMinutes());
  var now=new Date();
  if(d.getFullYear()!==now.getFullYear()||d.getMonth()!==now.getMonth()||d.getDate()!==now.getDate()){
    t=(d.getMonth()+1)+"-"+d.getDate()+" "+t;
  }
  return t;
}
function nMetaRow(st,obj){
  var sr=String(obj.stop_reason||""), isErr=obj.is_error||obj.error;
  var ic=_I('circle-check'), title="完成";
  if(isErr){ ic=_I('alert'); title="出错"; }
  else if(sr==="max_tokens"){ ic=_I('scissors'); title="已达输出上限"; }
  else if(sr==="refusal"){ ic=_I('ban'); title="拒绝回答"; }
  else if(sr==="pause_turn"){ ic=_I('pause'); title="已暂停"; }
  else if(sr==="tool_use"){ ic=_I('wrench'); title="工具调用收尾"; }
  var warn=!!(isErr||sr==="max_tokens"||sr==="refusal");
  var parts=[];
  parts.push(ic+" "+nEsc(title));
  if(obj.num_turns!=null) parts.push(nEsc(String(obj.num_turns)+" 轮"));
  var u=obj.usage||{}, tk=[];
  if(u.input_tokens) tk.push("入 "+nFmtTok(u.input_tokens));
  if(u.output_tokens) tk.push("出 "+nFmtTok(u.output_tokens));
  var cache=(Number(u.cache_read_input_tokens)||0)+(Number(u.cache_creation_input_tokens)||0);
  if(cache) tk.push("缓存 "+nFmtTok(cache));
  if(tk.length) parts.push(nEsc(tk.join(" / ")));
  if(obj.duration_ms!=null) parts.push(nEsc(nFmtDur(obj.duration_ms)));
  var doneAt=nFmtClock(obj.ts);
  if(doneAt) parts.push(nEsc("完成 "+doneAt));
  var d=document.createElement("div"); d.className="nmsg meta"+(warn?" warn":"");
  d.innerHTML=parts.join('<span class="msep">·</span>');
  (st.turnCard||st.root).appendChild(d); nScrollBottom();
}
