"use strict";
function nRenderToolUseBlock(sid, st, b){
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
  var _structured=_special?"":nStructuredToolBody(b.name, _inp);
  if(_special){
    _body=_special;
  } else if(_structured){
    _body=_structured;
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
}
